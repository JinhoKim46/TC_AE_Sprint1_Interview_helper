"""A simulated candidate, so the five interviewer prompts can be compared on the same input (R4).

Why simulate: comparing prompts needs many interviews with the *same* candidate behaviour. A human
can't give the same answers 15 times; a model playing a fixed persona can, close enough.

Why three personas: a good interviewer behaves differently with each, and that is what we want to
see. A strong answer should get a new topic (no over-drilling), a vague one should get a targeted
follow-up, and an evasive one should get a polite, persistent probe on the gap.

Why a different model family (Gemini) than the interviewer (GPT-5): if the same family played both
sides, the two would share habits and phrasing, and the conversations would look smoother than a real
one. The judge is a third model (Jev) for the same reason.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from interview_app.ingest import DocKind
from interview_app.interview.prompting import render
from interview_app.llm.client import LLMClient
from interview_app.security import UNTRUSTED_DATA_NOTE, wrap_untrusted


class CandidatePersona(StrEnum):
    STRONG = "strong"
    WEAK = "weak"
    EVASIVE = "evasive"


# What makes each persona strong or weak is taken from the candidate rubric (A3 specificity,
# A4 ownership, A6 depth): the interviewer should be able to *tell* them apart.
PERSONA_INSTRUCTIONS: dict[CandidatePersona, str] = {
    CandidatePersona.STRONG: (
        "You are a well-prepared, strong candidate.\n"
        "- Answer behavioural and experience questions as a short STAR story: situation, task, what YOU "
        "did, and the result.\n"
        '- Own your work: say "I" for what you did, and name what the team did separately.\n'
        "- Give concrete numbers from the CV and say how they were measured (which test set, which "
        "device, which baseline).\n"
        "- Explain your reasoning and the trade-offs you considered.\n"
        "- If a question touches something the CV doesn't show (a skill gap), admit it honestly and say "
        "how you would close the gap or what is closest in your experience."
    ),
    CandidatePersona.WEAK: (
        "You are an under-prepared, weak candidate (but friendly and honest).\n"
        '- Speak in generalities: say "we" for almost everything, so it is unclear what you did yourself.\n'
        "- Give no numbers and no concrete results; use words like 'improved a lot' or 'it went well'.\n"
        "- Drift: after a sentence or two on the question, wander into a related topic.\n"
        "- Don't structure answers as stories; no clear situation, action or result."
    ),
    CandidatePersona.EVASIVE: (
        "You are an evasive candidate.\n"
        "- Keep answers short and polished-sounding but thin.\n"
        "- Deflect: answer a slightly different, easier question than the one asked.\n"
        "- Avoid the gap questions: when asked about something the CV doesn't show, or a weak spot, change "
        "the subject to a strength without admitting the gap.\n"
        "- If pressed a second time on the same point, give a minimal, vague concession."
    ),
}

# Word ranges inside the 40-150 band the lab uses: evasive answers are short on purpose.
WORD_RANGE: dict[CandidatePersona, tuple[int, int]] = {
    CandidatePersona.STRONG: (60, 150),
    CandidatePersona.WEAK: (40, 130),
    CandidatePersona.EVASIVE: (40, 80),
}

# Some variety between sessions makes the comparison less dependent on one lucky phrasing; the
# persona instructions keep the behaviour itself stable.
SIM_TEMPERATURE = 0.7


class TranscriptTurn(Protocol):
    speaker: str  # "interviewer" or "candidate"
    text: str


def candidate_system_prompt(persona: CandidatePersona, documents: dict[DocKind, str]) -> str:
    """The simulator's instructions. The CV and cover letter are wrapped as data, like everywhere else."""
    # The simulator only needs what a real candidate knows about themself and the job.
    kinds = [DocKind.JD, DocKind.CV, DocKind.COVER_LETTER]
    blocks = [wrap_untrusted(k.value, documents[k]) for k in kinds if k in documents]
    low, high = WORD_RANGE[persona]
    return render(
        "candidate_sim.md",
        data_note=UNTRUSTED_DATA_NOTE,
        documents=blocks,
        persona_instructions=PERSONA_INSTRUCTIONS[persona],
        min_words=low,
        max_words=high,
    )


def candidate_messages(
    persona: CandidatePersona, documents: dict[DocKind, str], transcript: Sequence[TranscriptTurn]
) -> list[dict]:
    """Roles are mirrored compared with the interviewer's view: here the *interviewer* is the `user`
    and the simulated candidate's own earlier answers are `assistant` turns."""
    messages = [{"role": "system", "content": candidate_system_prompt(persona, documents)}]
    for t in transcript:
        role = "user" if t.speaker == "interviewer" else "assistant"
        messages.append({"role": role, "content": t.text})
    return messages


def simulate_answer(
    llm: LLMClient,
    persona: CandidatePersona,
    documents: dict[DocKind, str],
    transcript: Sequence[TranscriptTurn],
) -> str:
    """The candidate's next reply to the last interviewer turn in `transcript`."""
    result = llm.chat(
        "candidate_sim",
        candidate_messages(persona, documents, transcript),
        model=llm.settings.models.candidate_sim,
        temperature=SIM_TEMPERATURE,
    )
    # Models sometimes wrap a spoken reply in quotes despite the instruction.
    return result.text.strip().strip('"').strip()
