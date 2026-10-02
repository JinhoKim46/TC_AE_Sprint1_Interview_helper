"""Real Jev live scoring. Run with `uv run pytest -m live -s` (needs OPENROUTER_API_KEY). ~$0.0001."""

import pytest

from interview_app.config import Settings
from interview_app.evaluation.live import live_score
from interview_app.evaluation.rubric import load_rubric
from interview_app.llm.client import CallRecord
from interview_app.llm.decide import DecisionClient

pytestmark = pytest.mark.live

# Fictional role and candidate (the repo is public).
JD = "ML Engineer at Northwind Robotics: ship perception models to edge devices under tight latency."
CV = "ML engineer at Fieldsight (2021-2025): quantised a segmentation model for phones."
QUESTION = "Tell me about a project where you made a model faster on device."
STRONG = (
    "At Fieldsight I owned the on-device segmentation model. Latency on a Pixel 6 was 180 ms, too slow for "
    "live video. I tried int8 post-training quantisation, which cost 4 mIoU points, so I switched to "
    "quantisation-aware training: latency fell to 112 ms (38% faster, measured as p95 over 1,000 frames) "
    "with mIoU from 0.74 to 0.73 on our held-out field set."
)
VAGUE = "I usually try to optimise things when they are slow. I'm good at making models faster in general."


def test_strong_answer_scores_higher_than_vague_on_specificity():
    settings = Settings()
    records: list[CallRecord] = []
    decider = DecisionClient(settings, recorder=records.append)
    rubric = load_rubric(settings.rubric_path)

    def score(answer):
        return live_score(
            decider, rubric, category="EXP", question=QUESTION, answer=answer, jd_text=JD, cv_text=CV
        )

    strong, vague = score(STRONG), score(VAGUE)
    print("\nstrong:", [(i.item, i.score) for i in strong.items], strong.tip)
    print("vague: ", [(i.item, i.score) for i in vague.items], vague.tip)
    print("latency:", [round(r.latency_s, 2) for r in records], "cost:", sum(r.cost_usd for r in records))

    assert strong.items[0].item == vague.items[0].item == "A3"  # EXP's first live item
    assert strong.items[0].score > vague.items[0].score
    assert len(records) == 2  # one request per answer
