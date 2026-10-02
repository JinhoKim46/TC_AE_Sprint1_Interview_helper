"""LLM-as-a-judge (course task H5): one call scores the whole interview against the rubric.

Why one call per session instead of one per exchange: a 7-exchange interview would need ~10 calls and
a minute of waiting; one call with the transcript grouped into exchanges is faster and lets the judge
see the whole conversation (needed for session items like S3, the gap question).

The judge model comes from a different family than the interviewer (self-preference bias), and runs
at temperature 0 for stable scores.
"""

from interview_app.config import Settings
from interview_app.evaluation.exchanges import Exchange, turn_id
from interview_app.evaluation.rubric import Rubric
from interview_app.evaluation.schemas import Judgement
from interview_app.ingest import DocKind
from interview_app.interview.prompting import document_blocks, render
from interview_app.interview.schemas import InterviewPlan
from interview_app.llm.client import LLMClient
from interview_app.security import ANSWER_DATA_NOTE, UNTRUSTED_DATA_NOTE, wrap_answer, wrap_untrusted

JUDGED_SESSION_ITEMS = ("S1", "S3", "S4")  # S2 is the requirement list; S5/S6 are not used by the app


def _item_question(rubric: Rubric, item: dict) -> str:
    # rubric.json instructions start with a shared prefix about `state.*` fields (written for the
    # decision model). The LLM judge gets the documents differently, so only the item text is kept.
    return item["instructions"].removeprefix(rubric.data["shared_instruction_prefix"]).strip()


def _turn_text(speaker: str, text: str) -> str:
    # Answers are untrusted text: wrapped, so "give me a 5" is read as content. The interviewer's
    # turns are wrapped too: a model wrote them from the (untrusted) documents and the candidate's
    # answers, so an injection could echo through them into the judge (second-order injection).
    if speaker == "candidate":
        return wrap_answer(text)
    return wrap_untrusted("interviewer_turn", text)


def _requirements_block(plan: InterviewPlan | None) -> str:
    # The planner model wrote these from the job description, so they are data, not our instructions.
    if plan is None or not plan.requirements:
        return ""
    lines = [f"- [{r.priority.value}] {r.text}" for r in plan.requirements]
    return wrap_untrusted("plan_requirements", "\n".join(lines))


def judge_messages(
    rubric: Rubric,
    company: str,
    role: str,
    documents: dict[DocKind, str],
    exchanges: list[Exchange],
    plan: InterviewPlan | None,
) -> list[dict]:
    exchange_items = {
        item_id: {
            "name": item["name"],
            "question": _item_question(rubric, item),
            "criteria": item["criteria"],
        }
        for item_id, item in rubric.exchange_items.items()
    }
    session_items = {k: rubric.session_items[k] for k in JUDGED_SESSION_ITEMS}
    blocks, _ = document_blocks(company, role, documents)
    rendered_exchanges = [
        {
            "exchange_id": ex.exchange_id,
            "category": ex.category,
            "applicable": list(rubric.weights_for(ex.category, ex.question_id)),
            "turns": [
                {
                    "id": turn_id(t.idx),
                    "speaker": t.speaker,
                    "text": _turn_text(t.speaker, t.text),
                }
                for t in ex.turns
            ],
        }
        for ex in exchanges
    ]
    prompt = render(
        "judge.md",
        exchange_items=exchange_items,
        session_items=session_items,
        requirement_options=", ".join(rubric.session_items["S2"]["options"]),
        requirements_block=_requirements_block(plan),
        documents=blocks,
        exchanges=rendered_exchanges,
        data_note=UNTRUSTED_DATA_NOTE,
        answer_note=ANSWER_DATA_NOTE,
    )
    return [{"role": "user", "content": prompt}]


def run_judge(
    llm: LLMClient, settings: Settings, messages: list[dict], model: str | None = None, temperature: float = 0
) -> Judgement:
    """`temperature` comes from rubric.json judge_settings (0: the same transcript should score the same)."""
    judgement, _ = llm.chat_json(
        "judge",
        messages,
        Judgement,
        model=model or settings.models.judge,
        temperature=temperature,
        max_tokens=settings.judge_max_tokens,  # long transcripts need room for every item + rationale
    )
    return judgement
