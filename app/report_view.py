"""Render a feedback report (shared by the Interview and History pages)."""

import streamlit as st

from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import Report

# Above this spread between judge runs, the overall score (0-100) is flagged as approximate. This is not a
# copy of rubric.json's `unstable_spread` (2 levels on one item's 1-5 scale); it measures whole runs.
UNSTABLE_SPREAD = 15

BAND_LABELS = {
    "strong_yes": ("Strong hire signal", ":material/verified:"),
    "yes": ("Hire signal", ":material/thumb_up:"),
    "lean_no": ("Leaning no", ":material/trending_flat:"),
    "no": ("Not yet", ":material/school:"),
}
COMPONENT_LABELS = {
    "requirement_coverage": "Job requirements evidenced",
    "experience_technical": "Experience & technical depth",
    "behavioral": "Behavioral answers",
    "S1": "Motivation for this company",
    "S3": "Handling the tough question",
    "S4": "Your questions to the interviewer",
    "communication": "Communication",
    "logistics": "Logistics",
}
LEVEL_LABELS = {
    "not_addressed": "Not discussed",
    "not_demonstrated": "Not demonstrated",
    "claimed": "Claimed only",
    "partially_demonstrated": "Partly shown",
    "convincingly_demonstrated": "Convincingly shown",
}


def render_report(report: Report, rubric_path) -> None:
    rubric = load_rubric(rubric_path)
    names = {k: v["name"] for k, v in {**rubric.exchange_items, **rubric.session_items}.items()}

    label, icon = BAND_LABELS.get(report.band or "", ("No overall score", ":material/help:"))
    col1, col2 = st.columns([1, 3])
    col1.metric("Overall", f"{report.overall:.0f} / 100" if report.overall is not None else "—")
    col2.markdown(f"### {label}")
    col2.write(report.summary)
    runs = [r for r in report.runs if r is not None]
    if len(runs) > 1:
        scores = " · ".join(f"{r:.0f}" for r in report.runs if r is not None)
        st.caption(f"Median of {len(runs)} independent judge runs ({scores}).")
        if report.spread is not None and report.spread > UNSTABLE_SPREAD:
            st.warning(
                f"The judge's runs differ by {report.spread:.0f} points, so treat the overall score as "
                "approximate and rely on the written feedback."
            )
    for p in report.penalties:
        st.warning(p)

    st.subheader("Score breakdown")
    for key, value in report.components.items():
        if value is not None:
            st.progress(value / 100, text=f"{COMPONENT_LABELS.get(key, key)}: {value:.0f}")

    left, right = st.columns(2)
    with left:
        st.subheader("What went well")
        for s in report.strengths:
            st.markdown(
                f"- {s.point}  \n  <small>“{s.quote}” ({', '.join(s.evidence)})</small>",
                unsafe_allow_html=True,
            )
        if not report.strengths:
            st.caption("No strengths with clear evidence in this interview.")
    with right:
        st.subheader("What to improve")
        for imp in report.improvements:
            ref = f" ({imp.example_turn})" if imp.example_turn else ""
            st.markdown(f"- **{imp.area}**{ref}: {imp.advice}")

    if report.better_answer:
        with st.expander(
            f"A stronger answer for {report.better_answer.exchange_id}", icon=":material/edit_note:"
        ):
            st.caption(report.better_answer.why)
            st.markdown(report.better_answer.rewrite)

    st.subheader("Job requirements")
    st.dataframe(
        [
            {
                "Requirement": r.requirement,
                "Priority": r.priority,
                "Shown in the interview": LEVEL_LABELS[r.level],
                "Evidence": ", ".join(r.evidence),
            }
            for r in report.requirements
        ],
        hide_index=True,
        width="stretch",
    )

    st.subheader("Answer by answer")
    for ex in report.exchanges:
        score = f"{ex.score:.0f}" if ex.score is not None else "—"
        with st.expander(f"{ex.exchange_id} · {ex.category} · {score}  —  {ex.question[:90]}"):
            st.caption(
                f"{ex.answer_words} words · {ex.followups} follow-up(s)"
                + (f" · {', '.join(ex.flags)}" if ex.flags else "")
            )
            for item in ex.items:
                st.markdown(f"**{names.get(item.item, item.item)}: {item.score}/5** — {item.rationale}")

    st.caption(
        f"Judged by {report.judge_model} against rubric v{report.rubric_version}. "
        f"Talk ratio {report.talk_ratio}. "
        "AI feedback for practice: scores can vary by several points between runs."
    )
