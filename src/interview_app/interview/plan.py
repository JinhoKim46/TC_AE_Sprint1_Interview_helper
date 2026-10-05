"""The planning step (prompt chaining): one model call before the interview turns the JD, CV and
cover letter into an `InterviewPlan`. The P4 interviewer then follows the plan instead of working
it out while it talks, which keeps each interview turn short and focused."""

from interview_app.config import Settings
from interview_app.ingest import DocKind
from interview_app.interview.persona import SessionConfig
from interview_app.interview.prompting import plan_messages
from interview_app.interview.schemas import InterviewPlan
from interview_app.llm.client import LLMClient


def make_plan(
    llm: LLMClient,
    settings: Settings,
    company: str,
    role: str,
    documents: dict[DocKind, str],
    config: SessionConfig,
) -> InterviewPlan:
    plan, _ = llm.chat_json(
        "planner",
        plan_messages(company, role, documents, config),
        InterviewPlan,
        model=settings.models.planner,
        # Measured on the sample application: "low" took ~21 s and $0.006 for the same plan structure
        # (7 requirements, 7 probes) that "medium" produced in ~36 s for $0.012. The user waits for
        # this call before the interview starts, so latency wins (default "low", see config.py).
        reasoning_effort=effort if (effort := settings.planner_reasoning_effort) != "default" else None,
    )
    return plan
