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
        # Planning is a reasoning task done once per session, so a bit more effort is worth it.
        reasoning_effort="medium",
    )
    return plan
