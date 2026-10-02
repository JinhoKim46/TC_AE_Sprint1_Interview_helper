"""Turn templates (src/interview_app/prompts/*.md) + session data into chat messages.

Message roles, as the course asks us to explain them:
- system    — our instructions: persona, rules, documents (wrapped as data), output format.
- user      — the candidate's answers (wrapped as data, after passing the guards).
- assistant — the interviewer's earlier turns, so the model sees the conversation so far.
- A second, short system message at the END carries the live status the app computed (questions
  asked, follow-ups used, what to do next). It sits last so the long system prompt above stays
  byte-identical between turns, which lets the provider's prompt cache reuse it (cheaper, faster).
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from interview_app.ingest import KIND_LABELS, DocKind
from interview_app.interview.persona import TYPE_LABELS, Persona, PromptVariant, SessionConfig
from interview_app.interview.schemas import CotTurn, CritiqueTurn, InterviewerTurn, InterviewPlan
from interview_app.security import ANSWER_DATA_NOTE, UNTRUSTED_DATA_NOTE, wrap_untrusted

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Which JSON shape each variant answers in (see schemas.py for why field order matters).
TURN_SCHEMA: dict[PromptVariant, type] = {
    PromptVariant.P1_ZERO_SHOT: InterviewerTurn,
    PromptVariant.P2_FEW_SHOT: InterviewerTurn,
    PromptVariant.P3_COT_PLAN: CotTurn,
    PromptVariant.P4_ROLE_RICH: InterviewerTurn,
    PromptVariant.P5_SELF_CRITIQUE: CritiqueTurn,
}

# Only P4 receives the plan made by the separate planning call (prompt chaining). P3 plans in its own
# `notes` instead, and P1/P2/P5 get no plan, so each variant differs from the baseline by one technique.
USES_PLAN: frozenset[PromptVariant] = frozenset({PromptVariant.P4_ROLE_RICH})

# Guideline sections given to P4: types, stages, question rules, follow-ups, behaviours, persona,
# coverage, prohibited behaviours. §1 (preparation) is the planner's job; §9 is replaced by our JSON format.
GUIDELINE_SECTIONS = (2, 3, 4, 5, 6, 7, 8, 10)


@lru_cache
def _env() -> Environment:
    # StrictUndefined: a missing variable is an error, not silently empty text in a prompt.
    return Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        autoescape=False,  # these are prompts, not HTML
    )


def render(template: str, **context) -> str:
    text = _env().get_template(template).render(**context)
    return re.sub(r"\n{3,}", "\n\n", text).strip()  # tidy blank lines left by template tags


def guideline_excerpt(path: Path, sections=GUIDELINE_SECTIONS) -> str:
    """Pick numbered '## N.' sections from the interviewer guideline (the single source of truth)."""
    parts = re.split(r"(?m)^(?=## \d+\.)", path.read_text())
    keep = [p for p in parts if (m := re.match(r"## (\d+)\.", p)) and int(m.group(1)) in sections]
    return "\n".join(p.strip().removesuffix("---").strip() for p in keep)


def document_blocks(company: str, role: str, documents: dict[DocKind, str]) -> tuple[list[str], str]:
    """Every user-supplied text, including company and role labels, is wrapped as data."""
    blocks = [wrap_untrusted("application", f"Company: {company}\nRole: {role}")]
    blocks += [wrap_untrusted(kind.value, documents[kind]) for kind in DocKind if kind in documents]
    missing = ", ".join(KIND_LABELS[k] for k in DocKind if k not in documents)
    return blocks, missing


def focus_block(focus) -> str:
    """Drill targets as a data block. They come from the judge's reading of the JD and the answers,
    so text that started in an untrusted document could reach them: they are wrapped like any document."""
    if focus is None:
        return ""
    lines = [f"- Requirement to probe: {r}" for r in focus.requirements]
    lines += [f"- Answer quality to test: {s}" for s in focus.skills]
    return wrap_untrusted("practice_targets", "\n".join(lines))


def _contract_fields(schema: type) -> list[tuple[str, str]]:
    props = schema.model_json_schema()["properties"]
    return [(name, prop.get("description", name.replace("_", " "))) for name, prop in props.items()]


@dataclass
class PromptContext:
    company: str
    role: str
    documents: dict[DocKind, str]
    config: SessionConfig
    persona: Persona
    guideline: str = ""
    plan: InterviewPlan | None = None
    extra: dict = field(default_factory=dict)


def interviewer_system_prompt(ctx: PromptContext) -> str:
    variant = ctx.config.prompt_variant
    blocks, missing = document_blocks(ctx.company, ctx.role, ctx.documents)
    if variant in USES_PLAN and ctx.plan is None:
        raise ValueError(f"{variant} needs an interview plan")
    return render(
        f"interviewer_{variant.value}.md",
        persona=ctx.persona,
        type_label=TYPE_LABELS[ctx.config.interview_type],
        difficulty=ctx.config.difficulty.value,
        max_followups=ctx.config.max_followups,
        data_note=UNTRUSTED_DATA_NOTE,
        answer_note=ANSWER_DATA_NOTE,
        documents=blocks,
        missing=missing,
        fields=_contract_fields(TURN_SCHEMA[variant]),
        guideline=ctx.guideline,
        plan_json=ctx.plan.model_dump_json(indent=1) if ctx.plan else "",
        # A weak-spot drill's targets (None for a normal interview); every variant gets them via _base.md.
        focus=ctx.config.focus,
        focus_block=focus_block(ctx.config.focus),
    )


def control_message(
    *,
    main_asked: int,
    main_target: int,
    followups: int,
    max_followups: int,
    candidate_turns: int,
    directive: str,
) -> dict:
    content = render(
        "control.md",
        main_asked=main_asked,
        main_target=main_target,
        followups=followups,
        max_followups=max_followups,
        candidate_turns=candidate_turns,
        directive=directive,
    )
    return {"role": "system", "content": content}


def plan_messages(
    company: str, role: str, documents: dict[DocKind, str], config: SessionConfig
) -> list[dict]:
    blocks, missing = document_blocks(company, role, documents)
    prompt = render(
        "plan.md",
        type_label=TYPE_LABELS[config.interview_type],
        main_questions=config.main_questions,
        data_note=UNTRUSTED_DATA_NOTE,
        documents=blocks,
        missing=missing,
        focus=config.focus,
        focus_block=focus_block(config.focus),
    )
    return [
        {"role": "system", "content": "You are an experienced interviewer preparing for an interview."},
        {"role": "user", "content": prompt},
    ]


def assistant_turn_content(turn_json: dict) -> str:
    """Earlier interviewer turns go back to the model in the same JSON shape it answers in."""
    return json.dumps(turn_json, ensure_ascii=False)
