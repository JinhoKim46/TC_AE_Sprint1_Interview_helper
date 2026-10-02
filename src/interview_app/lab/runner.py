"""Run one whole interview between the real engine and the simulated candidate.

The runner goes through the same public engine API as the Interview page (`start_interview`,
`answer`), with the guards ON, so the lab measures the app as users get it, not a lab-only copy.
"""

import logging

from interview_app.applications import get_application
from interview_app.interview import engine as eng
from interview_app.interview.engine import EngineDeps
from interview_app.interview.persona import SessionConfig
from interview_app.lab.candidate import CandidatePersona, simulate_answer

log = logging.getLogger(__name__)


def run_session(
    deps: EngineDeps,
    user_id: int,
    app_id: int,
    config: SessionConfig,
    persona: CandidatePersona,
    max_candidate_turns: int = 16,
    *,
    blocked: list[str] | None = None,
) -> int:
    """Play one interview to the end and return its session id.

    Stops when the interviewer closes (`is_final`) or after `max_candidate_turns` answers; at the cap
    the session is ended the way a user would end it (`end_interview`), so its status shows that it
    did not close on its own. If a guard blocks a simulated answer (it never should: the simulator
    writes ordinary answers), the guard's reason is appended to `blocked` and the answer is
    re-simulated once; a second block ends the session.
    """
    application = get_application(deps.engine, user_id, app_id)
    if application is None:
        raise ValueError(f"application {app_id} not found")
    documents = {kind: doc.text for kind, doc in application.documents.items()}

    session_id = eng.start_interview(deps, user_id, app_id, config)
    # Simulator calls are billed to the same session, so the call log shows the full cost of a run.
    sim_llm = deps.make_llm(user_id, session_id)

    for _ in range(max_candidate_turns):
        view = eng.get_session(deps.engine, user_id, session_id)
        if view.status != "active":
            return session_id
        outcome = None
        for _attempt in range(2):
            reply = simulate_answer(sim_llm, persona, documents, view.turns)
            outcome = eng.answer(deps, user_id, session_id, reply)
            if outcome.accepted:
                break
            reason = outcome.guard.reason if outcome.guard else "blocked"
            checks = ",".join(outcome.guard.checks) if outcome.guard else ""
            log.warning("Simulated answer blocked in session %s: %s", session_id, checks)
            if blocked is not None:
                blocked.append(f"session {session_id}: {checks} {reason}")
        if not outcome.accepted:
            break
        if outcome.finished:
            return session_id

    eng.end_interview(deps, user_id, session_id)
    return session_id
