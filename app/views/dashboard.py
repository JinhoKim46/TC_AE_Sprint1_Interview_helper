"""Dashboard: how practice is going across all applications, on one page.

Read-only over what is stored, like History: no model is called, so opening it costs nothing. The numbers
come from interview_app.dashboard, which uses History's rules, so both pages agree.
"""

from contextlib import suppress
from datetime import timedelta

import streamlit as st
from report_view import BAND_LABELS
from streamlit.errors import StreamlitAPIException
from ui_common import (
    button_row,
    card_row,
    current_user_id,
    form_row,
    get_engine,
    go_button,
    page_link,
    panel,
    safe_md,
)

from interview_app.config import get_settings
from interview_app.cost import CHART_GROUP_ORDER, chart_group
from interview_app.dashboard import ApplicationRow, Attempt, CompanyPoint, dashboard, interview_attempts
from interview_app.interview.persona import TYPE_LABELS, InterviewType, SessionConfig, length_channel_label

engine = get_engine()
user_id = current_user_id()

st.title("Dashboard")
st.caption("How your practice is going across all your applications.")

# The chart's colours come from the theme (chartCategoricalColors in .streamlit/config.toml). Its first
# four slots pass the colour-vision checks as a set; the fifth is a gray that reads as "no data", so the
# chart draws at most four applications, and the table below always lists all of them.
MAX_LINES = 4
COUNTED_ONLY = "Standard and Full interviews only: Quick and Custom sessions (and drills) are practice."

board = dashboard(engine, user_id, get_settings().rubric_path)

if board.applications == 0:
    st.info("No applications yet. Add one (a job description and your CV) to start practising.")
    page_link("views/applications.py", label="Add an application", icon=":material/folder_open:")
    st.stop()
if board.kpis.interviews == 0:
    st.info("No interviews yet. Your progress across applications will appear here after the first one.")
    page_link("views/interview.py", label="Start an interview", icon=":material/forum:")
    st.stop()


def duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    # Short ("1h 48m"): five cards share one row, and a longer value was cut off with an ellipsis.
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def money(usd: float) -> str:
    # Four decimals for small amounts (a typical interview costs a few cents, and $0.00 would hide it),
    # two from 10 cents up: "$0.9654" did not fit the narrow KPI card and was cut to "$0.9…".
    return f"${usd:.2f}" if usd >= 0.1 else f"${usd:.4f}"


def unassigned_note() -> str:
    extra = board.cost.unassigned_usd
    return f" Includes {money(extra)} not tied to an interview (document checks, lab runs)." if extra else ""


def kpi_row() -> None:
    k = board.kpis
    cards = card_row(5, key="kpis", per_row=5)
    cards[0].metric("Interviews", k.interviews, help="Every interview you started, practice included.")
    cards[1].metric(
        "Practice time",
        duration(k.practised_seconds),
        help="From the first to the last message of each interview, added up.",
    )
    cards[2].metric(
        "Average score",
        f"{k.average_score:.0f}" if k.average_score is not None else "—",
        help=f"Over {k.scored} scored interview(s). {COUNTED_ONLY}",
    )
    cards[3].metric(
        "Best score", f"{k.best_score:.0f}" if k.best_score is not None else "—", help=COUNTED_ONLY
    )
    cards[4].metric(
        "Cost",
        money(k.cost_usd),
        help=f"All model spend, the same total as Settings → Usage and cost.{unassigned_note()}",
    )


def chart_series(rows: list[ApplicationRow], trend: list[CompanyPoint]) -> list[str]:
    """The labels to draw, in a fixed order (oldest application first), so an application keeps its
    colour from one visit to the next. Past MAX_LINES, the most recently practised ones are drawn."""
    scored = {p.application_id for p in trend}
    recent = [r for r in rows if r.application_id in scored][:MAX_LINES]
    return [r.label for r in sorted(recent, key=lambda r: r.application_id)]


def date_axis(interval: str) -> dict:
    """A time axis with at most one tick per `interval` ("day" or "week").

    Why: left to itself Vega-Lite puts ticks every few hours on a short range, and with a date-only label
    every tick of one day read "Oct 03", so one date repeated across the axis. `labelOverlap` drops
    labels that would collide on a long range. UTC, like the stored times and the tables' "(UTC)".
    """
    return {
        "labelAngle": 0,
        # A label expression, not `format`: with a time-interval tickCount Vega fell back to its mixed
        # default labels ("Sat 03", "Oct 04"). Every tick now reads the same way, e.g. "Oct 03".
        "labelExpr": "utcFormat(datum.value, '%b %d')",
        "tickCount": {"interval": interval, "step": 1},
        "labelOverlap": "greedy",
    }


def score_chart(series: list[str]) -> None:
    points = [
        {"Date": p.started_at.isoformat(), "Score": p.score, "Application": p.label}
        for p in board.trend
        if p.label in series
    ]
    x = {
        "field": "Date",
        "type": "temporal",
        "title": None,
        "scale": {"type": "utc"},
        "axis": date_axis("day"),
    }
    y = {"field": "Score", "type": "quantitative", "scale": {"domain": [0, 100]}, "title": "Score"}
    # Colour and shape both carry the application (one legend entry each), so the lines can be told apart
    # without colour vision. No labels at the line ends: several interviews on one day put the ends on
    # the same spot, and the names were drawn on top of each other.
    color = {"field": "Application", "type": "nominal", "scale": {"domain": series}, "title": None}
    st.vega_lite_chart(
        points,
        {
            "height": 300,
            "encoding": {"x": x, "y": y},
            "layer": [
                {"mark": {"type": "line", "strokeWidth": 2}, "encoding": {"color": color}},
                {
                    "mark": {"type": "point", "filled": True, "size": 80},
                    "encoding": {
                        # The same field on colour and shape merges them into one legend entry each.
                        "color": color,
                        "shape": color,
                        "tooltip": [
                            {"field": "Application"},
                            {
                                "field": "Date",
                                "type": "temporal",
                                "format": "%Y-%m-%d %H:%M",
                                "title": "Date (UTC)",
                            },
                            {"field": "Score", "format": ".0f"},
                        ],
                    },
                },
            ],
            # Vertical, so long application names never run off a phone-width chart.
            "config": {"legend": {"orient": "top", "direction": "vertical"}},
        },
        width="stretch",
    )


def applications_table() -> None:
    def open_in_history(rows: list[ApplicationRow]) -> None:
        picked = st.session_state.dashboard_table.selection.rows
        if picked:
            # The switch happens after the table is drawn: st.switch_page can't run inside a callback.
            st.session_state.dashboard_open = rows[picked[0]].application_id

    rows = board.rows
    st.dataframe(
        [
            {
                "Application": r.company,
                "Interviews": r.interviews,
                "Latest": r.latest,
                "Best": r.best,
                "Trend": f"{r.change:+.0f}" if r.change is not None else "—",
                "Cost": r.cost_usd,
                "Cost per interview": r.cost_per_interview,
                "Last practised": r.last_practised,
                "Weakest skill": r.weakest_skill or "—",
                "Role": r.role,
            }
            for r in rows
        ],
        column_config={
            "Latest": st.column_config.ProgressColumn("Latest", min_value=0, max_value=100, format="%.0f"),
            "Best": st.column_config.NumberColumn("Best", format="%.0f"),
            "Trend": st.column_config.TextColumn(
                "Trend", help="Latest minus the previous counted interview."
            ),
            "Last practised": st.column_config.DatetimeColumn("Last practised (UTC)", format="YYYY-MM-DD"),
            "Cost": st.column_config.NumberColumn(
                "Cost", format="$%.4f", help="Model spend of its interviews."
            ),
            "Cost per interview": st.column_config.NumberColumn(
                "Cost per interview",
                format="$%.4f",
                help="Its cost divided by its interviews that made a model call.",
            ),
        },
        hide_index=True,
        width="stretch",
        key="dashboard_table",
        on_select=lambda: open_in_history(rows),
        selection_mode="single-row",
    )
    st.caption(
        f"Click a row to open that application in History. Scores: {COUNTED_ONLY}"
        f" Cost: every interview of the application, practice included.{unassigned_note()}"
    )


def theme_color(name: str) -> str:
    mode = "dark" if st.context.theme.type == "dark" else "light"
    return st.get_option(f"theme.{mode}.{name}")


def group_colors() -> list[str]:
    """The theme's first three categorical colours plus its gray (the fifth slot), so "Guard and other"
    reads as the minor rest. The fourth (a red) is skipped: red means "error" in this app."""
    palette = st.get_option("theme.chartCategoricalColors")
    return [palette[0], palette[1], palette[2], palette[4]]


def spend_chart() -> None:
    cost = board.cost
    week = cost.bucket == "week"
    span = timedelta(days=7 if week else 1)
    points = [
        {
            "Date": b.start.isoformat(),
            "End": (b.start + span).isoformat(),
            "Label": b.start.isoformat(),
            "Purpose": b.purpose,
            "Group": chart_group(b.purpose),
            "Order": CHART_GROUP_ORDER.index(chart_group(b.purpose)),
            "Cost": b.cost_usd,
        }
        for b in cost.over_time
    ]
    period = "Week of" if week else "Day"
    st.vega_lite_chart(
        points,
        {
            "height": 260,
            # Aggregated per group, so a stack has at most four segments with fixed colours.
            "mark": {
                "type": "bar",
                # A 2px background-coloured outline keeps touching segments and bars apart.
                "stroke": theme_color("backgroundColor"),
                "strokeWidth": 2,
            },
            "encoding": {
                # A time axis (not one slot per bucket), so a day or week without spend shows as a gap.
                # Each bar spans its bucket, Date to End; UTC, because the buckets are UTC days.
                "x": {
                    "field": "Date",
                    "type": "temporal",
                    "title": None,
                    "scale": {"type": "utc"},
                    "axis": date_axis("week" if week else "day"),
                },
                "x2": {"field": "End"},
                "y": {
                    "aggregate": "sum",
                    "field": "Cost",
                    "type": "quantitative",
                    "title": "USD",
                    "axis": {"format": "$.2~f", "tickCount": 4},
                },
                "color": {
                    "field": "Group",
                    "type": "nominal",
                    "title": None,
                    "scale": {"domain": CHART_GROUP_ORDER, "range": group_colors()},
                },
                "order": {"aggregate": "min", "field": "Order"},
                "tooltip": [
                    {"field": "Label", "title": f"{period} (UTC)"},
                    {"field": "Group", "title": "Purpose"},
                    {"aggregate": "sum", "field": "Cost", "title": "Cost", "format": "$.4f"},
                ],
            },
            # The four groups on one row (owner's request): short names, so the row fits the chart width.
            "config": {
                "legend": {"orient": "top", "direction": "horizontal", "columns": len(CHART_GROUP_ORDER)}
            },
        },
        width="stretch",
    )
    st.caption(
        ("One bar per week (Monday start)" if week else "One bar per day")
        + ", UTC. Interview = interviewer and planning; Report and scoring = the report and live scoring;"
        " Voice = speech and transcription."
    )
    with st.expander("Spend over time as a table", icon=":material/table:"):
        st.dataframe(
            [{period: b.start, "Purpose": b.purpose, "Cost": b.cost_usd} for b in cost.over_time],
            column_config={
                period: st.column_config.DateColumn(f"{period} (UTC)", format="YYYY-MM-DD"),
                "Cost": st.column_config.NumberColumn("Cost", format="$%.4f"),
            },
            hide_index=True,
            width="stretch",
        )


def purpose_chart() -> None:
    cost = board.cost
    rows = [{"Purpose": p.purpose, "Cost": p.cost_usd} for p in cost.by_purpose]
    order = [p.purpose for p in cost.by_purpose]  # most expensive on top
    y = {"field": "Purpose", "type": "nominal", "sort": order, "title": None}
    x = {"field": "Cost", "type": "quantitative", "title": "USD", "axis": {"format": "$.2~f", "tickCount": 4}}
    st.vega_lite_chart(
        rows,
        {
            "height": {"step": 28},
            "encoding": {"y": y, "x": x},
            "layer": [
                {
                    # One series: one colour; the bar's length carries the value.
                    "mark": {"type": "bar", "cornerRadiusEnd": 4, "color": group_colors()[0]},
                    "encoding": {
                        "tooltip": [{"field": "Purpose"}, {"field": "Cost", "format": "$.4f"}],
                    },
                },
                {
                    "mark": {"type": "text", "align": "left", "dx": 4, "color": theme_color("textColor")},
                    "encoding": {"text": {"field": "Cost", "format": "$.4f"}},
                },
            ],
        },
        width="stretch",
    )
    with st.expander("Spend by purpose as a table", icon=":material/table:"):
        total = cost.total_usd or 1.0
        st.dataframe(
            [
                {
                    "Purpose": p.purpose,
                    "Calls": p.calls,
                    "Cost": p.cost_usd,
                    "Share": 100 * p.cost_usd / total,
                }
                for p in cost.by_purpose
            ],
            column_config={
                "Cost": st.column_config.NumberColumn("Cost", format="$%.4f"),
                "Share": st.column_config.NumberColumn("Share", format="%.0f%%"),
            },
            hide_index=True,
            width="stretch",
        )


def cost_section() -> None:
    cost = board.cost
    st.subheader("Cost")
    if not cost.total_usd:
        st.caption(
            "No model spend yet: the cost of each interview appears here once a model has been called."
        )
        return
    cards = card_row(3, key="cost", per_row=3)
    cards[0].metric("Total spend", money(cost.total_usd), help="The same total as Settings → Usage and cost.")
    average = cost.average_per_interview_usd
    cards[1].metric(
        "Per interview",
        money(average) if average is not None else "—",
        help=f"Average over the {cost.interviews} interview(s) that made a model call.",
    )
    cards[2].metric(
        "Not tied to an interview",
        money(cost.unassigned_usd),
        help="Document checks when you upload a CV or job description, and lab runs.",
    )
    with panel(key="spend-over-time"):
        st.markdown("**Spend over time**")
        spend_chart()
    with panel(key="spend-by-purpose"):
        st.markdown("**Spend by purpose**")
        purpose_chart()


kpi_row()

with panel(key="trend"):
    st.subheader("Overall score over time")
    series = chart_series(board.rows, board.trend)
    if board.trend:
        score_chart(series)
        if len({p.application_id for p in board.trend}) > len(series):
            st.caption(
                f"The {MAX_LINES} most recently practised applications are drawn; the table lists all."
            )
        st.caption(f"One line per application. {COUNTED_ONLY}")
        with st.expander("The scores as a table", icon=":material/table:"):
            st.dataframe(
                [{"Date": p.started_at, "Application": p.label, "Score": p.score} for p in board.trend],
                column_config={
                    "Date": st.column_config.DatetimeColumn("Date (UTC)", format="YYYY-MM-DD HH:mm"),
                    "Score": st.column_config.NumberColumn("Score", format="%.0f"),
                },
                hide_index=True,
                width="stretch",
            )
    else:
        st.caption("No scored interviews yet: get a feedback report after a Standard or Full interview.")

st.subheader("Applications")
applications_table()
opened = st.session_state.pop("dashboard_open", None)
if opened is not None:
    # History's application filter is a selectbox with this key, so History opens on that application.
    st.session_state.history_app = opened
    # A page run on its own (tests) has no navigation to switch with.
    with suppress(StreamlitAPIException):
        st.switch_page("views/history.py")


def attempt_title(a: Attempt) -> str:
    """'2026-10-06 03:37 · Technical deep-dive · Full · Text · Tough · Realistic — 72/100 · Hire signal'."""
    s = a.session
    kind = TYPE_LABELS[InterviewType(s.interview_type)]
    session = length_channel_label(SessionConfig(length=s.length, channel=s.channel))
    if s.overall is not None:
        band = BAND_LABELS.get(s.band or "", ("",))[0]
        result = f"{s.overall:.0f}/100" + (f" · {band}" if band else "")
    elif s.status == "active":
        result = "in progress"
    else:
        result = "no report yet" if not s.has_report else "no score"
    practice = " · practice" if not a.counted else ""
    return (
        f"{s.started_at:%Y-%m-%d %H:%M} · {kind} · {session} · {s.difficulty.capitalize()} · "
        f"{s.mode.capitalize()} — {result}{practice}"
    )


def attempt_detail(a: Attempt) -> None:
    """The highlights of one interview's report; the full report (quotes, requirements, the stronger
    answer) is one click away on History. Report text is model output, so it goes through safe_md."""
    sid = a.session.session_id
    if a.summary is None:
        if a.session.status == "active":
            st.caption("This interview is still running.")
            go_button("views/interview.py", "Resume it", icon=":material/forum:", key=f"attempt-resume-{sid}")
        else:
            st.caption("No feedback report yet.")
            # Handed over like Home's "Get feedback": the Interview page opens this session (ticket 01).
            go_button(
                "views/interview.py",
                "Get feedback",
                icon=":material/assessment:",
                key=f"attempt-feedback-{sid}",
                state={"open_session": sid},
            )
        return
    if not a.counted:
        st.caption("Practice session: its score is shown here but not counted in the progress numbers.")
    st.markdown(safe_md(a.summary))
    well, improve = form_row(2, key=f"attempt-feedback-{sid}", align="top")
    with well:
        st.markdown("**What went well**")
        st.markdown("\n".join(f"- {safe_md(x, inline=True)}" for x in a.strengths) or "—")
    with improve:
        st.markdown("**What to improve**")
        lines = [
            f"- **{safe_md(i.area, inline=True)}**: {safe_md(i.advice, inline=True)}" for i in a.improvements
        ]
        st.markdown("\n".join(lines) or "—")
    if a.questions:
        st.dataframe(
            [{"Question": q.question, "Score": q.score} for q in a.questions],
            column_config={
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
            },
            hide_index=True,
            width="stretch",
        )
    go_button(
        "views/history.py",
        "Open the full report",
        icon=":material/description:",
        key=f"attempt-open-{sid}",
        primary=False,
        state={"history_open": sid},
    )


def attempts_section() -> None:
    attempts = interview_attempts(engine, user_id)
    st.subheader("Interviews by company")
    st.caption("Every interview per application, newest first. Open one for its score and feedback.")
    rows = [r for r in board.rows if r.interviews]
    if not rows:
        return
    for tab, row in zip(st.tabs([f"{r.label} ({r.interviews})" for r in rows]), rows, strict=True):
        with tab:
            for a in attempts.get(row.application_id, []):
                with st.expander(attempt_title(a)):
                    attempt_detail(a)


attempts_section()

st.subheader("Skills across all applications")
if board.item_means:
    st.caption("Average answer score per skill (1 = weak, 5 = excellent) over every report, weakest first.")
    st.dataframe(
        [{"Skill": m.name, "Average": m.mean, "Answers scored": m.count} for m in board.item_means],
        column_config={
            "Average": st.column_config.ProgressColumn(
                "Average (1–5)", min_value=1, max_value=5, format="%.1f"
            )
        },
        hide_index=True,
        width="stretch",
    )
else:
    st.caption("No scored answers yet: the skills appear after the first feedback report.")

cost_section()

with button_row(key="next"):
    go_button("views/interview.py", "Start an interview", icon=":material/play_arrow:")
    go_button("views/history.py", "Open History", icon=":material/history:", primary=False)
