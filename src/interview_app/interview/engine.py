"""The interview loop: start a session, take an answer, get the next interviewer turn.

Division of labour ("the model judges, code computes"):
- The model decides *what* to say next (follow-up or new topic) and writes it.
- Code counts main questions and follow-ups, enforces limits (turns, budget), decides when the
  interview must close, runs the security guards, and stores every turn immediately — so a browser
  refresh or a crash never loses an interview.

The engine is stateless between calls: everything it needs is re-read from the database.

Coaching mode adds one pause per answer: `answer` stores the answer and scores it live (Jev), but does
not call the interviewer. The candidate then either `retry`s (the old attempt is marked superseded and
disappears from every transcript the models see) or calls `continue_interview` (= `respond`).
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, timedelta

from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import col, func, select

from interview_app.applications import get_application
from interview_app.config import Settings
from interview_app.db import InterviewSession, LLMCall, Turn, session_scope, utcnow
from interview_app.evaluation.live import LiveFeedback, live_score
from interview_app.evaluation.rubric import load_rubric
from interview_app.ingest import DocKind
from interview_app.interview.persona import Mode, Persona, SessionConfig, derive_persona
from interview_app.interview.plan import make_plan
from interview_app.interview.prompting import (
    TURN_SCHEMA,
    USES_PLAN,
    PromptContext,
    assistant_turn_content,
    control_message,
    guideline_excerpt,
    interviewer_system_prompt,
)
from interview_app.interview.schemas import AnyTurn, InterviewPlan, Stage, private_fields
from interview_app.llm.client import LLMClient, LLMError
from interview_app.llm.decide import DecisionClient
from interview_app.security import (
    GuardResult,
    InjectionGuard,
    check_answer_length,
    check_budget,
    check_turns,
    wrap_answer,
)

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("preparing", "active")


class InterviewError(Exception):
    """Something the user should see (a model failure, a missing application...)."""


@dataclass
class EngineDeps:
    """Everything the engine needs, passed in so tests can swap the model for a fake."""

    engine: Engine
    settings: Settings
    # Builds an LLM client whose call log is bound to (user_id, session_id).
    make_llm: Callable[[int, int | None], LLMClient]
    guard: InjectionGuard | None = None
    # Jev client for live scores in coaching mode. None -> coaching still works, just without scores.
    decider: DecisionClient | None = None
    # Builds a Jev client whose call log is bound to (user_id, session_id), like make_llm. When set, the
    # guard and live scoring use it, so their (small) cost counts towards that interview's cost and budget.
    make_decider: Callable[[int, int | None], DecisionClient] | None = None


def _session_guard(deps: EngineDeps, user_id: int, session_id: int) -> InjectionGuard | None:
    if deps.guard is not None and deps.make_decider is not None:
        return InjectionGuard(deps.settings, deps.make_decider(user_id, session_id))
    return deps.guard


def _session_decider(deps: EngineDeps, user_id: int, session_id: int) -> DecisionClient | None:
    return deps.make_decider(user_id, session_id) if deps.make_decider is not None else deps.decider


@dataclass
class TurnView:
    idx: int
    speaker: str
    text: str
    stage: str | None
    question_id: str | None
    is_followup: bool
    is_final: bool
    live: LiveFeedback | None = None  # coaching mode: live scores + tip for a candidate answer


@dataclass
class Progress:
    main_asked: int  # interviewer turns that opened a new topic (follow-ups excluded)
    followups: int  # consecutive follow-ups since the last main question
    candidate_turns: int
    in_candidate_questions: bool  # the interviewer has invited the candidate's questions
    last_speaker: str | None


@dataclass
class SessionView:
    id: int
    application_id: int
    company: str
    role: str
    config: SessionConfig
    persona: Persona
    status: str
    turns: list[TurnView]
    progress: Progress
    cost_usd: float
    # Coaching mode: retried attempts, kept for display only (never part of `turns`).
    superseded: list[TurnView] = field(default_factory=list)
    retries_used: int = 0  # retries of the current (latest) answer


@dataclass
class AnswerOutcome:
    accepted: bool  # False: the answer was blocked by a guard and not sent anywhere
    guard: GuardResult | None
    interviewer: TurnView | None
    finished: bool
    # Coaching mode: the answer's live feedback (None if scoring is off or failed), and whether the
    # engine is now waiting for the candidate to choose Retry or Continue.
    live: LiveFeedback | None = None
    awaiting_choice: bool = False


# --- Pure logic (no database, no model): easy to test and to explain ----------------------------

_NOT_MAIN = {Stage.CANDIDATE_QUESTIONS.value, Stage.CLOSE.value}


def compute_progress(turns: list[TurnView]) -> Progress:
    main_asked = followups = candidate_turns = 0
    in_cq = False
    for t in turns:
        if t.speaker == "candidate":
            candidate_turns += 1
            continue
        if t.stage == Stage.CANDIDATE_QUESTIONS.value:
            in_cq = True
        if t.is_followup:
            followups += 1
        elif t.stage not in _NOT_MAIN and t.question_id != "NONE":
            main_asked += 1
            followups = 0
    return Progress(main_asked, followups, candidate_turns, in_cq, turns[-1].speaker if turns else None)


def next_directive(progress: Progress, config: SessionConfig, force_close: bool) -> str:
    """What the app tells the interviewer to do next. Code decides the *phase*; the model the wording."""
    if force_close:
        return (
            "Close the interview now: thank the candidate, describe next steps in one sentence, "
            "set is_final true."
        )
    if progress.last_speaker is None:
        return (
            "Open the interview: introduce yourself and the format in one or two sentences, "
            "then ask a warm-up question."
        )
    if progress.in_candidate_questions:
        return (
            "You are in the candidate-questions stage. Answer their question in character using only the "
            "documents and company notes (say you'd need to check anything else). If they have no more "
            "questions, close the interview and set is_final true."
        )
    if progress.main_asked >= config.main_questions:
        # The last main question deserves the same chance of a follow-up as the others.
        if progress.followups < config.max_followups:
            return (
                "All planned main questions are asked. Either one follow-up on the last answer (if it was "
                "vague, unowned or unevidenced) or invite the candidate's own questions "
                "(stage candidate_questions)."
            )
        return (
            "All planned main questions are done. "
            "Invite the candidate's own questions now (stage candidate_questions)."
        )
    if progress.followups >= config.max_followups:
        return "No more follow-ups on this topic. Ask the next main question."
    return (
        "Decide the single best next move: one follow-up on the last answer (if it was vague, unowned or "
        "unevidenced) or the next main question (if it was complete)."
    )


def must_close(turn_count: int, cost_usd: float, settings: Settings) -> bool:
    """Hard limits (OWASP LLM10): past these the interview closes no matter what the model wants."""
    limits = settings.limits
    return not check_turns(turn_count, limits).allowed or not check_budget(cost_usd, limits).allowed


# --- Database helpers ---------------------------------------------------------------------------


def _turn_view(t: Turn) -> TurnView:
    live = LiveFeedback.model_validate_json(t.live_json) if t.live_json else None
    return TurnView(t.idx, t.speaker, t.text, t.stage, t.question_id, t.is_followup, t.is_final, live)


def _load_all(engine: Engine, user_id: int, session_id: int) -> tuple[InterviewSession, list[Turn]] | None:
    """The session and ALL its turns, superseded attempts included. Only for display and numbering."""
    with session_scope(engine) as s:
        row = s.exec(
            select(InterviewSession).where(
                InterviewSession.id == session_id, InterviewSession.user_id == user_id
            )
        ).first()
        if row is None:
            return None
        turns = s.exec(select(Turn).where(Turn.session_id == session_id).order_by(col(Turn.idx))).all()
        return row, list(turns)


def _load(engine: Engine, user_id: int, session_id: int) -> tuple[InterviewSession, list[Turn]] | None:
    """The session and its transcript *without* superseded attempts.

    Everything that reasons about the interview (the interviewer's messages, progress counting, limits,
    the final evaluation via get_session) goes through here, so a discarded attempt can never leak in.
    """
    loaded = _load_all(engine, user_id, session_id)
    if loaded is None:
        return None
    row, turns = loaded
    return row, [t for t in turns if not t.superseded]


def _next_idx(engine: Engine, session_id: int) -> int:
    # Not len(turns): superseded attempts keep their idx, so the kept transcript can have gaps.
    with session_scope(engine) as s:
        top = s.exec(select(func.max(Turn.idx)).where(Turn.session_id == session_id)).one()
    return 0 if top is None else top + 1


def _retries_used(all_turns: list[Turn]) -> int:
    """Superseded candidate attempts since the last interviewer turn (= retries of the current answer)."""
    used = 0
    for t in reversed(all_turns):
        if t.speaker == "interviewer":
            break
        used += t.superseded
    return used


def session_cost(engine: Engine, session_id: int) -> float:
    with session_scope(engine) as s:
        total = s.exec(select(func.sum(LLMCall.cost_usd)).where(LLMCall.session_id == session_id)).one()
    return float(total or 0.0)


def get_session(engine: Engine, user_id: int, session_id: int) -> SessionView | None:
    loaded = _load_all(engine, user_id, session_id)
    if loaded is None:
        return None
    row, all_turns = loaded
    config = SessionConfig.model_validate_json(row.config_json)
    views = [_turn_view(t) for t in all_turns if not t.superseded]
    return SessionView(
        id=row.id,
        application_id=row.application_id,
        company=row.company,
        role=row.role,
        config=config,
        persona=derive_persona(config),
        status=row.status,
        turns=views,
        progress=compute_progress(views),
        cost_usd=session_cost(engine, row.id),
        superseded=[_turn_view(t) for t in all_turns if t.superseded],
        retries_used=_retries_used(all_turns),
    )


def _is_stale_start(row: InterviewSession, settings: Settings) -> bool:
    """A "preparing" session older than the start timeout was interrupted (crash, closed tab mid-plan)."""
    if row.status != "preparing":
        return False
    # SQLite drops the timezone on read, so a stored UTC time comes back naive.
    started = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=UTC)
    return utcnow() - started > timedelta(minutes=settings.limits.start_timeout_minutes)


def active_session(engine: Engine, user_id: int, settings: Settings | None = None) -> SessionView | None:
    """The user's unfinished interview, if any (so a refresh resumes it).

    An interrupted start would otherwise lock the user out forever, so it is marked failed here.
    """
    settings = settings or Settings()
    with session_scope(engine) as s:
        rows = s.exec(
            select(InterviewSession)
            .where(InterviewSession.user_id == user_id, col(InterviewSession.status).in_(ACTIVE_STATUSES))
            .order_by(col(InterviewSession.id).desc())
        ).all()
        stale = [r.id for r in rows if _is_stale_start(r, settings)]
        live = [r.id for r in rows if r.id not in stale]
    for session_id in stale:
        _set_status(engine, session_id, "failed")
    return get_session(engine, user_id, live[0]) if live else None


def _add_turn(
    engine: Engine, row: InterviewSession, idx: int, speaker: str, text: str, turn: AnyTurn | None = None
):
    with session_scope(engine) as s:
        record = Turn(session_id=row.id, user_id=row.user_id, idx=idx, speaker=speaker, text=text)
        if turn is not None:
            record.stage = turn.stage.value
            record.question_id = turn.question_id
            record.is_followup = turn.is_followup
            record.is_final = turn.is_final
            extra = private_fields(turn)
            record.private_json = json.dumps(extra) if extra else None
        s.add(record)
        s.flush()
        return _turn_view(record)


def _set_status(engine: Engine, session_id: int, status: str) -> None:
    with session_scope(engine) as s:
        row = s.get(InterviewSession, session_id)
        row.status = status
        if status not in ACTIVE_STATUSES:
            row.ended_at = utcnow()
        s.add(row)


# --- Model calls --------------------------------------------------------------------------------


def _messages(deps: EngineDeps, row: InterviewSession, turns: list[Turn], directive: str) -> list[dict]:
    config = SessionConfig.model_validate_json(row.config_json)
    documents = {DocKind(k): v for k, v in json.loads(row.documents_json).items()}
    plan = InterviewPlan.model_validate_json(row.plan_json) if row.plan_json else None
    ctx = PromptContext(
        company=row.company,
        role=row.role,
        documents=documents,
        config=config,
        persona=derive_persona(config),
        guideline=guideline_excerpt(deps.settings.guideline_path),
        plan=plan,
    )
    messages = [{"role": "system", "content": interviewer_system_prompt(ctx)}]
    if not turns:
        # Anthropic and Gemini reject a request with no user message (OpenAI accepts one), so the opening
        # turn gets a neutral cue. It is fixed text, not candidate input, so it needs no wrapping.
        messages.append({"role": "user", "content": "(The candidate has joined the interview.)"})
    for t in turns:
        if t.speaker == "interviewer":
            payload = {
                **(json.loads(t.private_json) if t.private_json else {}),
                "stage": t.stage,
                "question_id": t.question_id,
                "is_followup": t.is_followup,
                "message": t.text,
                "is_final": t.is_final,
            }
            messages.append({"role": "assistant", "content": assistant_turn_content(payload)})
        else:
            messages.append({"role": "user", "content": wrap_answer(t.text)})
    progress = compute_progress([_turn_view(t) for t in turns])
    messages.append(
        control_message(
            main_asked=progress.main_asked,
            main_target=config.main_questions,
            followups=progress.followups,
            max_followups=config.max_followups,
            candidate_turns=progress.candidate_turns,
            directive=directive,
        )
    )
    return messages


def _interviewer_turn(
    deps: EngineDeps, row: InterviewSession, turns: list[Turn], force_close: bool
) -> AnyTurn:
    config = SessionConfig.model_validate_json(row.config_json)
    llm = deps.make_llm(row.user_id, row.id)
    schema = TURN_SCHEMA[config.prompt_variant]
    settings = config.llm
    call = {
        "model": settings.model or deps.settings.models.interviewer,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "reasoning_effort": settings.reasoning_effort,
    }
    progress = compute_progress([_turn_view(t) for t in turns])
    directive = next_directive(progress, config, force_close)
    try:
        turn, _ = llm.chat_json("interviewer", _messages(deps, row, turns, directive), schema, **call)
        # Guideline rule: never end without offering the candidate a chance to ask questions.
        # One corrective retry; code, not the prompt alone, guarantees this.
        if turn.is_final and not progress.in_candidate_questions and not force_close:
            directive = (
                "Do not close yet. First invite the candidate's own questions (stage candidate_questions)."
            )
            turn, _ = llm.chat_json("interviewer", _messages(deps, row, turns, directive), schema, **call)
            turn.is_final = False
    except (LLMError, ValidationError) as e:
        log.warning("Interviewer turn failed for session %s: %r", row.id, e)
        raise InterviewError("The interviewer could not respond. Please try again.") from e
    if force_close:
        turn.is_final = True  # the limit is hard even if the model forgot the flag
    return turn


# --- Public API ---------------------------------------------------------------------------------


def start_interview(deps: EngineDeps, user_id: int, application_id: int, config: SessionConfig) -> int:
    """Create a session (with a plan, if the prompt variant uses one) and the interviewer's opening turn."""
    application = get_application(deps.engine, user_id, application_id)
    if application is None:
        raise InterviewError("That application no longer exists.")
    # One interview at a time: a second active session would be hidden behind the first on resume.
    if active_session(deps.engine, user_id, deps.settings) is not None:
        raise InterviewError("Another interview is still in progress. Finish or end it first.")
    documents = {kind: doc.text for kind, doc in application.documents.items()}
    with session_scope(deps.engine) as s:
        row = InterviewSession(
            user_id=user_id,
            application_id=application_id,
            company=application.company,
            role=application.role,
            config_json=config.model_dump_json(),
            documents_json=json.dumps({k.value: v for k, v in documents.items()}),
        )
        s.add(row)
        s.flush()
        session_id = row.id

    try:
        if config.prompt_variant in USES_PLAN:
            llm = deps.make_llm(user_id, session_id)  # the planning call is billed to this session
            plan = make_plan(llm, deps.settings, application.company, application.role, documents, config)
            with session_scope(deps.engine) as s:
                stored = s.get(InterviewSession, session_id)
                stored.plan_json = plan.model_dump_json()
                s.add(stored)
        row, turns = _load(deps.engine, user_id, session_id)
        turn = _interviewer_turn(deps, row, turns, force_close=False)
    except Exception as e:
        # Any failure (not only model errors) must not leave a "preparing" row that blocks the next start.
        _set_status(deps.engine, session_id, "failed")
        log.warning("Start failed for session %s: %r", session_id, e)
        raise InterviewError("Could not start the interview. Please try again.") from e

    _add_turn(deps.engine, row, 0, "interviewer", turn.message, turn)
    with session_scope(deps.engine) as s:
        # The user may have ended the session (another tab) while planning ran; don't revive it.
        still_preparing = s.get(InterviewSession, session_id).status == "preparing"
    if still_preparing:
        _set_status(deps.engine, session_id, "finished" if turn.is_final else "active")
    return session_id


def _check_answer(deps: EngineDeps, user_id: int, session_id: int, text: str) -> GuardResult | None:
    """Run the limits and the injection guard. Returns the blocking result, or None if the answer is ok."""
    length = check_answer_length(text, deps.settings.limits)
    if not length.allowed:
        return length
    guard = _session_guard(deps, user_id, session_id)
    if guard is not None:
        verdict = guard.check_answer(text)
        if not verdict.allowed:
            # The blocked text is never stored or sent to any model.
            log.info("Blocked answer in session %s: %s", session_id, verdict.checks)
            return verdict
    return None


def _is_coaching(row: InterviewSession) -> bool:
    return SessionConfig.model_validate_json(row.config_json).mode == Mode.COACHING


def _live_feedback(
    deps: EngineDeps, row: InterviewSession, turns: list[Turn], text: str
) -> LiveFeedback | None:
    """Live scores for the answer to the latest interviewer turn, or None if scoring is off or fails."""
    decider = _session_decider(deps, row.user_id, row.id)
    if decider is None or not deps.settings.features.live_scoring:
        return None
    # Imported here, not at the top: exchanges.py imports this module (for TurnView), so a top-level
    # import would be circular.
    from interview_app.evaluation.exchanges import build_exchanges

    exchanges = build_exchanges([_turn_view(t) for t in turns])
    if not exchanges:
        return None
    # The category comes from the exchange's *main* question (a follow-up on an EXP question is still
    # EXP); the question text is what the candidate is answering right now (the latest interviewer turn).
    question = next(t.text for t in reversed(turns) if t.speaker == "interviewer")
    documents = json.loads(row.documents_json)
    return live_score(
        decider,
        load_rubric(deps.settings.rubric_path),
        category=exchanges[-1].category,
        question=question,
        answer=text,
        jd_text=documents.get(DocKind.JD.value, ""),
        cv_text=documents.get(DocKind.CV.value, ""),
        cover_letter_text=documents.get(DocKind.COVER_LETTER.value, ""),
    )


def _store_scored_answer(
    deps: EngineDeps, row: InterviewSession, turns: list[Turn], text: str, replaces: Turn | None = None
) -> AnswerOutcome:
    """Coaching mode: store the answer with its live feedback and wait for Retry / Continue.

    `replaces` is the attempt a retry supersedes. Scoring runs first (it is a network call), then the
    swap happens in one transaction, so a crash can never leave the question with no kept answer.
    """
    live = _live_feedback(deps, row, turns, text)
    idx = _next_idx(deps.engine, row.id)
    with session_scope(deps.engine) as s:
        if replaces is not None:
            old = s.get(Turn, replaces.id)
            old.superseded = True
            s.add(old)
        s.add(
            Turn(
                session_id=row.id,
                user_id=row.user_id,
                idx=idx,
                speaker="candidate",
                text=text,
                live_json=live.model_dump_json() if live is not None else None,
            )
        )
    return AnswerOutcome(True, None, None, False, live=live, awaiting_choice=True)


def answer(deps: EngineDeps, user_id: int, session_id: int, text: str) -> AnswerOutcome:
    """Take the candidate's answer, run the guards, and get the next interviewer turn.

    Coaching mode stops after storing (and live-scoring) the answer; see `retry` / `continue_interview`.
    """
    loaded = _load(deps.engine, user_id, session_id)
    if loaded is None or loaded[0].status != "active":
        raise InterviewError("This interview is not active.")
    row, turns = loaded
    if not turns or turns[-1].speaker != "interviewer":
        # e.g. a double submit, or coaching mode waiting for Retry / Continue: two answers in a row
        # would confuse the interviewer and the evaluation.
        raise InterviewError("The interviewer hasn't asked the next question yet.")

    if (blocked := _check_answer(deps, user_id, session_id, text)) is not None:
        return AnswerOutcome(False, blocked, None, False)

    if _is_coaching(row):
        return _store_scored_answer(deps, row, turns, text.strip())
    _add_turn(deps.engine, row, _next_idx(deps.engine, session_id), "candidate", text.strip())
    return respond(deps, user_id, session_id)


def retry(deps: EngineDeps, user_id: int, session_id: int, text: str) -> AnswerOutcome:
    """Coaching mode: replace the latest answer with a new attempt (same guards), and score it.

    The old attempt is kept but marked superseded, so the interviewer and the final judge only ever see
    the last attempt — like a real second take, not a transcript with two answers in a row.
    """
    loaded = _load_all(deps.engine, user_id, session_id)
    if loaded is None or loaded[0].status != "active":
        raise InterviewError("This interview is not active.")
    row, all_turns = loaded
    turns = [t for t in all_turns if not t.superseded]
    if not _is_coaching(row):
        raise InterviewError("Retries are only available in coaching mode.")
    if not turns or turns[-1].speaker != "candidate":
        raise InterviewError("There is no answer to retry.")
    if _retries_used(all_turns) >= deps.settings.limits.max_retries_per_answer:
        raise InterviewError("You've used all retries for this answer. Press Continue.")

    if (blocked := _check_answer(deps, user_id, session_id, text)) is not None:
        return AnswerOutcome(False, blocked, None, False)  # the earlier attempt stays as it was

    return _store_scored_answer(deps, row, turns[:-1], text.strip(), replaces=turns[-1])


def respond(deps: EngineDeps, user_id: int, session_id: int, force_close: bool = False) -> AnswerOutcome:
    """Generate the interviewer's next turn. Also used to retry after a model failure, because the
    candidate's answer is already stored at that point."""
    loaded = _load(deps.engine, user_id, session_id)
    if loaded is None or loaded[0].status != "active":
        raise InterviewError("This interview is not active.")
    row, turns = loaded
    if not turns or turns[-1].speaker != "candidate":
        raise InterviewError("There is no answer to respond to.")  # e.g. Continue pressed twice
    force_close = force_close or must_close(len(turns), session_cost(deps.engine, session_id), deps.settings)
    turn = _interviewer_turn(deps, row, turns, force_close)
    view = _add_turn(deps.engine, row, _next_idx(deps.engine, session_id), "interviewer", turn.message, turn)
    if turn.is_final:
        _set_status(deps.engine, session_id, "finished")
    return AnswerOutcome(True, None, view, turn.is_final)


# Coaching mode's "Continue" button: the answer is already stored, so this is just the next turn.
continue_interview = respond


def end_interview(deps: EngineDeps, user_id: int, session_id: int) -> None:
    """The candidate stops early. No closing model call: ending must always work, even offline."""
    loaded = _load(deps.engine, user_id, session_id)
    if loaded is not None and loaded[0].status in ACTIVE_STATUSES:
        _set_status(deps.engine, session_id, "ended_early")
