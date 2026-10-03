"""Render a feedback report (shared by the Interview and History pages)."""

import streamlit as st
from ui_common import form_row, panel, safe_md, short

from interview_app.evaluation.rubric import load_rubric
from interview_app.evaluation.schemas import Report
from interview_app.interview.persona import Channel, SessionConfig, length_channel_label

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
# Badge colour per hiring signal; the badge always carries the label and icon too (BAND_LABELS).
BAND_COLORS = {"strong_yes": "green", "yes": "green", "lean_no": "orange", "no": "red"}
PRIORITY_LABELS = {"must": "Must have", "nice": "Nice to have"}
LEVEL_LABELS = {
    "not_addressed": "Not discussed",
    "not_demonstrated": "Not demonstrated",
    "claimed": "Claimed only",
    "partially_demonstrated": "Partly shown",
    "convincingly_demonstrated": "Convincingly shown",
}


def band_badge(band: str | None) -> str:
    """The hiring signal as a coloured badge with an icon and words, so colour is never the only cue.
    Static text only (labels from BAND_LABELS), so it is safe in markdown as it is."""
    if band not in BAND_LABELS:
        return ""
    label, icon = BAND_LABELS[band]
    return f":{BAND_COLORS[band]}-badge[{icon} {label}]"


# The icon tells the channel apart without relying on the badge colour.
CHANNEL_ICONS = {Channel.TEXT: ":material/chat:", Channel.VOICE: ":material/record_voice_over:"}


def session_badge(config: SessionConfig) -> str:
    """The session's Length and Channel as one badge, e.g. "Quick · Voice" (interview screen, History,
    report header). Static text only (enum labels), so it is safe in markdown as it is."""
    return f":blue-badge[{CHANNEL_ICONS[config.channel]} {length_channel_label(config)}]"


def render_report(report: Report, rubric_path, config: SessionConfig | None = None) -> None:
    """`config`: the interviewed session's settings, shown as a Length · Channel badge in the header so
    the reader knows what kind of session the score came from (a Quick score is not a Full one)."""
    rubric = load_rubric(rubric_path)
    names = {k: v["name"] for k, v in {**rubric.exchange_items, **rubric.session_items}.items()}

    # --- Verdict first: score, hiring signal and the judge's summary in one panel -------------------
    with panel(key="report-head"):
        col1, col2 = form_row([1, 3], key="report-head", align="center")
        col1.metric("Overall", f"{report.overall:.0f} / 100" if report.overall is not None else "—")
        with col2:
            badges = band_badge(report.band) or ":gray-badge[:material/help: No overall score]"
            if config is not None:
                badges += f" {session_badge(config)}"
            st.markdown(badges)
            st.markdown(safe_md(report.summary))
        runs = [r for r in report.runs if r is not None]
        if len(runs) > 1:
            scores = " · ".join(f"{r:.0f}" for r in report.runs if r is not None)
            st.caption(f"Median of {len(runs)} independent judge runs ({scores}).")
    if len(runs) > 1 and report.spread is not None and report.spread > UNSTABLE_SPREAD:
        st.warning(
            f"The judge's runs differ by {report.spread:.0f} points, so treat the overall score as "
            "approximate and rely on the written feedback.",
            icon=":material/balance:",
        )
    for p in report.penalties:
        st.warning(safe_md(p))

    # --- Where the score comes from ------------------------------------------------------------------
    parts = [(key, value) for key, value in report.components.items() if value is not None]
    if parts:
        st.subheader("Score breakdown")
        # Two aligned columns of bars (one grid, so the bars of a row start and end at the same x).
        cols = form_row(2, key="breakdown", align="top")
        for i, (key, value) in enumerate(parts):
            cols[i % 2].progress(value / 100, text=f"{COMPONENT_LABELS.get(key, key)} · {value:.0f} / 100")

    # --- Strengths and improvements side by side, evidence quoted -----------------------------------
    # Two panels in one top-aligned row, each as tall as its own list: the lists often differ a lot in length
    # (none vs three long points), and stretching the short one to match left a large empty box.
    left, right = form_row(2, key="report-notes", align="top")
    with left, panel(key="report-good"):
        st.markdown("#### :material/thumb_up: What went well")
        for s in report.strengths:
            # No unsafe_allow_html: the quote is the candidate's own text, and raw HTML from it would run
            # in the app's origin (stored XSS). Escaped markdown italics give the same look safely.
            evidence = safe_md(", ".join(s.evidence), inline=True)
            quote = f"  \n  *“{safe_md(s.quote, inline=True)}”*" if s.quote else ""
            st.markdown(f"- {safe_md(s.point, inline=True)}{quote} ({evidence})")
        if not report.strengths:
            st.caption("No strengths with clear evidence in this interview.")
    with right, panel(key="report-improve"):
        st.markdown("#### :material/trending_up: What to improve")
        for imp in report.improvements:
            ref = f" ({safe_md(imp.example_turn, inline=True)})" if imp.example_turn else ""
            st.markdown(f"- **{safe_md(imp.area, inline=True)}**{ref}: {safe_md(imp.advice, inline=True)}")
        if not report.improvements:
            st.caption("No specific improvements were suggested.")

    if report.better_answer:
        with st.expander(
            f"A stronger answer for {safe_md(short(report.better_answer.exchange_id, 40))}",
            icon=":material/edit_note:",
        ):
            st.caption(safe_md(report.better_answer.why))
            st.markdown(safe_md(report.better_answer.rewrite))

    if report.requirements:
        st.subheader("Job requirements")
        st.dataframe(
            [
                {
                    "Requirement": r.requirement,
                    "Priority": PRIORITY_LABELS.get(r.priority, r.priority),
                    "Shown in the interview": LEVEL_LABELS[r.level],
                    "Evidence": ", ".join(r.evidence),
                }
                for r in report.requirements
            ],
            hide_index=True,
            width="stretch",
        )

    st.subheader("Answer by answer")
    st.caption("Each answer's score (0-100) and the rubric items behind it. Open one to see why.")
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
