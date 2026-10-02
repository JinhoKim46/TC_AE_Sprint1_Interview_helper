"""Render a feedback report (shared by the Interview and History pages)."""

import streamlit as st
from ui_common import safe_md, short

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
    col2.markdown(safe_md(report.summary))
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
        st.warning(safe_md(p))

    st.subheader("Score breakdown")
    for key, value in report.components.items():
        if value is not None:
            st.progress(value / 100, text=f"{COMPONENT_LABELS.get(key, key)}: {value:.0f}")

    left, right = st.columns(2)
    with left:
        st.subheader("What went well")
        for s in report.strengths:
            # No unsafe_allow_html: the quote is the candidate's own text, and raw HTML from it would run
            # in the app's origin (stored XSS). Escaped markdown italics give the same look safely.
            evidence = safe_md(", ".join(s.evidence), inline=True)
            st.markdown(
                f"- {safe_md(s.point, inline=True)}  \n  *“{safe_md(s.quote, inline=True)}”* ({evidence})"
            )
        if not report.strengths:
            st.caption("No strengths with clear evidence in this interview.")
    with right:
        st.subheader("What to improve")
        for imp in report.improvements:
            ref = f" ({safe_md(imp.example_turn, inline=True)})" if imp.example_turn else ""
            st.markdown(f"- **{safe_md(imp.area, inline=True)}**{ref}: {safe_md(imp.advice, inline=True)}")

    if report.better_answer:
        with st.expander(
            f"A stronger answer for {safe_md(short(report.better_answer.exchange_id, 40))}",
            icon=":material/edit_note:",
        ):
            st.caption(safe_md(report.better_answer.why))
            st.markdown(safe_md(report.better_answer.rewrite))

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
        label = f"{ex.exchange_id} · {ex.category} · {score}  —  {short(ex.question)}"
        with st.expander(safe_md(label, inline=True)):
            st.caption(
                f"{ex.answer_words} words · {ex.followups} follow-up(s)"
                + (f" · {safe_md(', '.join(ex.flags), inline=True)}" if ex.flags else "")
            )
            for item in ex.items:
                name = safe_md(names.get(item.item, item.item), inline=True)
                st.markdown(f"**{name}: {item.score}/5** — {safe_md(item.rationale)}")

    st.caption(
        f"Judged by {safe_md(report.judge_model)} against rubric v{report.rubric_version}. "
        f"Talk ratio {report.talk_ratio}. "
        "AI feedback for practice: scores can vary by several points between runs."
    )
