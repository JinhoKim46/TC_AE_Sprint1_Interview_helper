"""Session settings and the interviewer persona derived from them.

The user picks only two things that matter for realism: the interview *type* (who is interviewing
and why) and the *difficulty* (how hard they probe). The persona — name, background, personality,
seniority — follows from those, so the user isn't asked to combine five dropdowns that can
contradict each other (an HR recruiter running a deep technical round). An optional override
exists for people who want a specific mix (course task E7: strict / neutral / friendly personas).
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class InterviewType(StrEnum):
    RECRUITER_SCREEN = "recruiter_screen"
    HIRING_MANAGER = "hiring_manager"
    TECHNICAL_DEEP_DIVE = "technical_deep_dive"
    ML_CASE = "ml_case"  # also covers system design
    BEHAVIORAL = "behavioral"
    FINAL_ROUND = "final_round"


TYPE_LABELS: dict[InterviewType, str] = {
    InterviewType.RECRUITER_SCREEN: "Recruiter screen",
    InterviewType.HIRING_MANAGER: "Hiring manager",
    InterviewType.TECHNICAL_DEEP_DIVE: "Technical deep-dive",
    InterviewType.ML_CASE: "Case / system design",
    InterviewType.BEHAVIORAL: "Behavioral",
    InterviewType.FINAL_ROUND: "Final round (panel)",
}


class Difficulty(StrEnum):
    FRIENDLY = "friendly"
    STANDARD = "standard"
    TOUGH = "tough"


class Mode(StrEnum):
    REALISTIC = "realistic"  # no feedback until the end, like a real interview
    COACHING = "coaching"  # a short tip after each answer


class PromptVariant(StrEnum):
    """The five interviewer system prompts compared for course requirement R4."""

    P1_ZERO_SHOT = "p1_zero_shot"
    P2_FEW_SHOT = "p2_few_shot"
    P3_COT_PLAN = "p3_cot_plan"
    P4_ROLE_RICH = "p4_role_rich"
    P5_SELF_CRITIQUE = "p5_self_critique"


VARIANT_LABELS: dict[PromptVariant, str] = {
    PromptVariant.P1_ZERO_SHOT: "P1 · Zero-shot",
    PromptVariant.P2_FEW_SHOT: "P2 · Few-shot",
    PromptVariant.P3_COT_PLAN: "P3 · Chain-of-thought (plan first)",
    PromptVariant.P4_ROLE_RICH: "P4 · Role-rich persona",
    PromptVariant.P5_SELF_CRITIQUE: "P5 · Self-critique",
}

# Main questions (not counting follow-ups) that fit a realistic slot for each type.
DEFAULT_MAIN_QUESTIONS: dict[InterviewType, int] = {
    InterviewType.RECRUITER_SCREEN: 6,
    InterviewType.HIRING_MANAGER: 7,
    InterviewType.TECHNICAL_DEEP_DIVE: 6,
    InterviewType.ML_CASE: 4,
    InterviewType.BEHAVIORAL: 6,
    InterviewType.FINAL_ROUND: 8,
}

# From the interviewer guideline §5: how many follow-ups per main question each difficulty allows.
MAX_FOLLOWUPS: dict[Difficulty, int] = {Difficulty.FRIENDLY: 1, Difficulty.STANDARD: 2, Difficulty.TOUGH: 3}


class PersonaOverride(BaseModel):
    personality: str | None = None  # e.g. "strict", "warm", "skeptical"
    background: str | None = None  # e.g. "HR", "engineering", "research"
    seniority: str | None = None  # e.g. "team lead", "principal engineer"


class SessionConfig(BaseModel):
    interview_type: InterviewType = InterviewType.HIRING_MANAGER
    difficulty: Difficulty = Difficulty.STANDARD
    mode: Mode = Mode.REALISTIC
    main_questions: int = Field(default=7, ge=2, le=15)
    prompt_variant: PromptVariant = PromptVariant.P4_ROLE_RICH
    override: PersonaOverride = PersonaOverride()

    @property
    def max_followups(self) -> int:
        return MAX_FOLLOWUPS[self.difficulty]


class Persona(BaseModel):
    name: str
    title: str
    background: str
    personality: str
    seniority: str
    focus: str  # what this interviewer cares about, in one line


# Fictional names; one fixed person per type keeps sessions recognisable and avatars cacheable.
_BASE: dict[InterviewType, Persona] = {
    InterviewType.RECRUITER_SCREEN: Persona(
        name="Lena Brandt",
        title="Senior Talent Acquisition Partner",
        background="HR / recruiting",
        personality="organized and friendly",
        seniority="senior recruiter",
        focus="motivation, CV walk-through, logistics and red flags",
    ),
    InterviewType.HIRING_MANAGER: Persona(
        name="Daniel Okafor",
        title="Engineering Manager",
        background="engineering management",
        personality="pragmatic and direct",
        seniority="team lead",
        focus="impact, ownership, how you work, and fit with this team",
    ),
    InterviewType.TECHNICAL_DEEP_DIVE: Persona(
        name="Dr. Mira Castellano",
        title="Principal Engineer",
        background="senior engineer / scientist",
        personality="curious, precise and skeptical of hand-waving",
        seniority="principal",
        focus="depth on your projects, fundamentals, decisions, trade-offs and failure modes",
    ),
    InterviewType.ML_CASE: Persona(
        name="Jonas Weber",
        title="Staff Engineer",
        background="ML systems",
        personality="collaborative but demanding",
        seniority="staff",
        focus="scoping, data, modelling, evaluation, deployment and risks in the company's domain",
    ),
    InterviewType.BEHAVIORAL: Persona(
        name="Aisha Rahman",
        title="Head of People Development",
        background="HR / organizational psychology",
        personality="warm, attentive and structured",
        seniority="department head",
        focus="concrete STAR stories for the competencies the job description names",
    ),
    InterviewType.FINAL_ROUND: Persona(
        name="Sofia Lindgren",
        title="Director of Engineering (leading a panel)",
        background="engineering leadership",
        personality="calm and thorough",
        seniority="director",
        focus="a blend: motivation, depth, behaviour and fit; hands over to panelists explicitly",
    ),
}

_DIFFICULTY_TONE: dict[Difficulty, str] = {
    Difficulty.FRIENDLY: "supportive",
    Difficulty.STANDARD: "",
    Difficulty.TOUGH: "challenging (pushes on assumptions and gaps, still polite)",
}


def derive_persona(config: SessionConfig) -> Persona:
    """Type sets who the interviewer is; difficulty adjusts the tone; an override wins over both."""
    persona = _BASE[config.interview_type].model_copy()
    tone = _DIFFICULTY_TONE[config.difficulty]
    if tone:
        persona.personality = f"{persona.personality}; {tone}"
    o = config.override
    if o.personality:
        persona.personality = o.personality
    if o.background:
        persona.background = o.background
    if o.seniority:
        persona.seniority = o.seniority
    return persona
