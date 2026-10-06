"""Settings page: interview defaults, developer settings, and usage/cost.

Course task M9 asks to keep developer settings (model, system prompt) apart from the candidate's
experience, because a candidate may know nothing about LLMs. So the page has a plain-language part
(interview defaults) and a developer part that stays hidden until a toggle is switched on.
Everything saved here is read by the Interview page when a new interview starts (preferences.py).
"""

import streamlit as st
from ui_common import (
    button_row,
    card_row,
    current_user_id,
    form_row,
    get_engine,
    get_price_catalog,
    kept_widget,
    panel,
    slider_start,
)

from interview_app.config import get_settings
from interview_app.interview.persona import (
    CHANNEL_LABELS,
    DEFAULT_MAIN_QUESTIONS,
    LENGTH_LABELS,
    TYPE_LABELS,
    VARIANT_LABELS,
    Channel,
    Difficulty,
    InterviewType,
    Length,
    LLMSettings,
    Mode,
    PromptVariant,
)
from interview_app.llm.pricing import ModelOption, model_options
from interview_app.preferences import judge_model, load_preferences, preset_main_questions, save_preferences
from interview_app.usage import usage_summary

engine = get_engine()
user_id = current_user_id()
cfg = get_settings()
prefs = load_preferences(engine, user_id)

# One line per prompting technique (course requirement R4), so the choice is understandable here.
VARIANT_HELP: dict[PromptVariant, str] = {
    PromptVariant.P1_ZERO_SHOT: "Instructions only, no examples: the baseline.",
    PromptVariant.P2_FEW_SHOT: "Adds example exchanges showing good questions and follow-ups.",
    PromptVariant.P3_COT_PLAN: "The model writes private notes (plan, reasoning) before each question.",
    PromptVariant.P4_ROLE_RICH: "A detailed persona plus an interview plan made from your documents first "
    "(prompt chaining). The default.",
    PromptVariant.P5_SELF_CRITIQUE: "Drafts a question, critiques it against the rules, then rewrites it.",
}

# "default" = don't send the parameter at all (LLMSettings value None), so the provider decides.
EFFORT_OPTIONS = ["default", "none", "low", "medium", "high"]

st.title("Settings")
st.caption("Defaults for new interviews, optional developer settings, and what the app has spent so far.")

# --- Interview defaults (candidate-facing, plain language) --------------------------------------

st.subheader("Interview defaults")
st.caption("What a new interview starts with. You can still change these on the Interview page.")

# One panel with a grid like the Interview page's start form (the same settings in the same places, so the
# two pages read alike). The rows share their columns, and the controls of a row are level (form_row).
with panel(key="defaults"):
    col1, col2 = form_row(2, key="defaults-kind")
    # Options are plain strings and labels come from a lookup, as on the Interview page: widgets compare
    # options by value across reruns, which is most robust with plain strings.
    interview_type = InterviewType(
        col1.selectbox(
            "Interview type",
            options=[t.value for t in InterviewType],
            format_func=lambda v: TYPE_LABELS[InterviewType(v)],
            index=list(InterviewType).index(prefs.interview_type),
        )
    )
    difficulty = col2.segmented_control(
        "Difficulty",
        options=[d.value for d in Difficulty],
        default=prefs.difficulty.value,
        format_func=str.capitalize,
        help="Friendly: supportive, one follow-up per topic. Tough: probes gaps and assumptions harder.",
    )
    col3, col4 = form_row(2, key="defaults-length")
    length = Length(
        col3.segmented_control(
            "Default length",
            options=[v.value for v in Length],
            default=prefs.length.value,
            format_func=lambda v: LENGTH_LABELS[Length(v)],
            help="Quick: a short practice on the core questions. Full: the real interview. "
            "Custom: pick the number of questions yourself.",
            key="pref_length",
        )
        # Clicking the selected segment again deselects it; keep the saved value then.
        or prefs.length
    )
    channel = Channel(
        col4.segmented_control(
            "Default channel",
            options=[c.value for c in Channel],
            default=prefs.channel.value,
            format_func=lambda v: CHANNEL_LABELS[Channel(v)],
            help="Voice: the interviewer speaks each question and you can answer by speaking (or typing). "
            "Text: you read the questions and type your answers.",
            key="pref_channel",
        )
        or prefs.channel
    )
    # Custom keeps the saved count; a preset length leaves it untouched, so switching back to Custom later
    # brings the old number back. The count sits right under the Length it belongs to.
    main_questions = prefs.main_questions
    if length == Length.CUSTOM:
        main_questions = st.slider(
            "Main questions (follow-ups come on top)",
            cfg.limits.min_main_questions,
            cfg.limits.max_main_questions,
            slider_start(prefs.main_questions or DEFAULT_MAIN_QUESTIONS[interview_type]),
            key="pref_main_questions",
        )
    else:
        count = preset_main_questions(length, cfg.length_presets, interview_type)
        st.caption(f"{LENGTH_LABELS[length]}: {count} main questions, follow-ups come on top.")
    MODE_CHOICES = {
        Mode.REALISTIC.value: "Realistic: feedback at the end",
        Mode.COACHING.value: "Coaching: feedback after every answer, with retries",
    }
    mode = st.radio(
        "Mode",
        options=[m.value for m in Mode],
        format_func=lambda v: MODE_CHOICES[v],
        index=[m.value for m in Mode].index(prefs.mode.value),
        horizontal=True,
        key="pref_mode",
    )
    # Voice channel: one fixed voice for every interviewer, or each persona's own voice (config.py
    # TTSSettings). Half the width, like the other select boxes, so the grid stays one grid.
    PERSONA_VOICE = ""  # the selectbox needs a plain-string option for "no override" (saved as None)
    voice_options = [PERSONA_VOICE, *cfg.tts.available_voices]
    voice_col, voice_model_col = form_row(2, key="defaults-voice")
    voice = voice_col.selectbox(
        "Interviewer voice",
        options=voice_options,
        index=voice_options.index(prefs.voice) if prefs.voice in voice_options else 0,
        format_func=lambda v: v or "Match the interviewer (each persona has its own voice)",
        help="Used in Voice interviews. The voice is fixed when an interview starts.",
        key="pref_voice",
    )
    # The TTS model (config.py TTSSettings.available_models: the ones the guardrail allows). Every voice
    # above works with every model, so changing the model keeps the chosen voice.
    voice_model_ids = cfg.tts.model_ids()
    # None (or a model removed from config since) shows the config default.
    current_voice_model = prefs.voice_model if prefs.voice_model in voice_model_ids else cfg.tts.model
    voice_model = voice_model_col.selectbox(
        "Voice model",
        options=voice_model_ids,
        index=voice_model_ids.index(current_voice_model),
        format_func=cfg.tts.model_label,
        help="Used in Voice interviews. The model is fixed when an interview starts.",
        key="pref_voice_model",
    )

# --- Developer settings (hidden by default, course task M9) -------------------------------------

st.divider()
show_dev = st.toggle(
    "Show developer settings",
    help="Prompt and model settings. You don't need these to practise interviews.",
)

options = model_options(get_price_catalog(), cfg)
# A saved model may have been dropped from the curated list since; keep it selectable, not a crash.
for saved in (prefs.interviewer.model, prefs.judge_model):
    if saved and saved not in {o.id for o in options}:
        options.append(ModelOption(id=saved, label=saved, open_weight=False))
by_id: dict[str, ModelOption] = {o.id: o for o in options}


def _price(o: ModelOption) -> str:
    if o.prompt_price_per_m is None or o.completion_price_per_m is None:
        return "price unknown"
    return f"${o.prompt_price_per_m:.2f} in / ${o.completion_price_per_m:.2f} out per 1M tokens"


def _model_label(model_id: str) -> str:
    o = by_id[model_id]
    # A selectbox can't render badges, so the open-weight marker is plain text in the label.
    tag = " · open-weight" if o.open_weight else ""
    return f"{o.label}{tag} · {_price(o)}"


def _model_picker(label: str, current: str, help_text: str, key: str) -> str:
    ids = [o.id for o in options]
    picked = kept_widget(
        st.selectbox, key, current, label, options=ids, format_func=_model_label, help=help_text
    )
    o = by_id[picked]
    badges = []
    if o.open_weight:
        badges.append(":green-badge[open-weight]")
    if o.supports_structured_outputs is False:
        badges.append(":orange-badge[no JSON schema mode: relies on the repair retry]")
    if o.supports_reasoning:
        badges.append(":blue-badge[reasoning model]")
    if badges:
        st.markdown(" ".join(badges))
    return picked


# Start from what is saved, so saving with the developer section hidden keeps those settings as they are.
variant = prefs.prompt_variant
llm = prefs.interviewer
judge = judge_model(prefs, cfg)

if show_dev:
    # Its own panel, so the developer part reads as one separate group under the candidate's defaults.
    with panel(key="developer"):
        st.subheader("Developer settings")
        variant = PromptVariant(
            kept_widget(
                st.radio,
                "pref_variant",
                prefs.prompt_variant.value,
                "Interviewer system prompt",
                options=[v.value for v in PromptVariant],
                format_func=lambda v: VARIANT_LABELS[PromptVariant(v)],
                captions=[VARIANT_HELP[v] for v in PromptVariant],
                help="Five prompting techniques for the same interviewer, compared in the lab "
                "(course task R4).",
            )
        )

        interviewer_model = _model_picker(
            "Interviewer model",
            llm.model or cfg.models.interviewer,
            "The model that asks the questions. Prices come from OpenRouter's model list.",
            key="pref_interviewer_model",
        )

        # Top-aligned: each column starts with a checkbox, and the slider or number box below it is optional.
        c1, c2 = form_row(2, key="dev-limits", align="top")
        with c1:
            temp_default = kept_widget(
                st.checkbox, "pref_temp_default", llm.temperature is None, "Provider default temperature"
            )
            temperature = None
            if not temp_default:
                temperature = kept_widget(
                    st.slider,
                    "pref_temperature",
                    llm.temperature if llm.temperature is not None else 0.7,
                    "Temperature",
                    0.0,
                    2.0,
                    step=0.1,
                    help="Randomness of the wording: 0 = almost the same reply every time, higher = more "
                    "varied but less predictable. Reasoning models (e.g. the gpt-5 family) ignore it.",
                )
        with c2:
            tokens_default = kept_widget(
                st.checkbox, "pref_tokens_default", llm.max_tokens is None, "Provider default max tokens"
            )
            max_tokens = None
            if not tokens_default:
                max_tokens = kept_widget(
                    st.number_input,
                    "pref_max_tokens",
                    llm.max_tokens or 2000,
                    "Max tokens",
                    min_value=64,
                    max_value=8000,
                    step=100,
                    help="Upper limit on the length of one reply (output only). Too low and the reply is cut "
                    "off mid-JSON, which fails validation. Reasoning models count their hidden thinking "
                    "against this limit too.",
                )

        effort = kept_widget(
            st.segmented_control,
            "pref_effort",
            llm.reasoning_effort or "default",
            "Reasoning effort",
            options=EFFORT_OPTIONS,
            format_func=str.capitalize,
            help="How much the model 'thinks' before answering, for models that support it. More effort can "
            "mean better questions but slower, more expensive turns. 'Low' keeps turns at a few seconds. "
            "Models without reasoning ignore it.",
        )
        llm = LLMSettings(
            # None = follow the default from config, so a changed .env default applies automatically.
            model=None if interviewer_model == cfg.models.interviewer else interviewer_model,
            temperature=temperature,
            max_tokens=int(max_tokens) if max_tokens is not None else None,
            reasoning_effort=None if effort in (None, "default") else effort,
        )

        judge = _model_picker(
            "Judge model (final report)",
            judge,
            "Writes the final evaluation. A different model family from the interviewer avoids the judge "
            "favouring its own family's style (self-preference bias).",
            key="pref_judge_model",
        )

with button_row(key="save"):
    save_clicked = st.button(
        "Save settings",
        type="primary",
        icon=":material/save:",
        help="Saves the interview defaults (and the developer settings, if you changed them).",
    )
if save_clicked:
    save_preferences(
        engine,
        user_id,
        prefs.model_copy(
            update={
                "interview_type": interview_type,
                "difficulty": Difficulty(difficulty or Difficulty.STANDARD),
                "mode": Mode(mode),
                "length": length,
                "channel": channel,
                "voice": voice or None,
                # The default is saved as None, so a later change of the config default applies to this user.
                "voice_model": None if voice_model == cfg.tts.model else voice_model,
                "main_questions": main_questions,
                "prompt_variant": variant,
                "interviewer": llm,
                "judge_model": None if judge == cfg.models.judge else judge,
            }
        ),
    )
    st.toast("Settings saved", icon=":material/check:")

# --- Usage and cost (course task M3) ------------------------------------------------------------

st.divider()
st.subheader("Usage and cost")
usage = usage_summary(engine, user_id)
m1, m2 = card_row(2, key="usage", per_row=2)
m1.metric("Total spend", f"${usage.total_cost_usd:.4f}")
m2.metric("Model calls", usage.total_calls)


def _rows(rows, name: str) -> list[dict]:
    return [
        {
            name: r.name,
            "Calls": r.calls,
            "Prompt tokens": r.prompt_tokens,
            "Completion tokens": r.completion_tokens,
            "Cost (USD)": round(r.cost_usd, 5),
        }
        for r in rows
    ]


if usage.total_calls:
    t1, t2 = form_row(2, key="usage-tables", align="top")
    t1.caption("By role")
    t1.dataframe(_rows(usage.by_role, "Role"), hide_index=True)
    t2.caption("By model")
    t2.dataframe(_rows(usage.by_model, "Model"), hide_index=True)
else:
    st.caption("No model calls yet.")

st.caption("Current list prices of the selected models (from OpenRouter's model catalog):")
interviewer_id = llm.model or cfg.models.interviewer
st.dataframe(
    [
        {"Role": "Interviewer", "Model": interviewer_id, "Price": _price(by_id[interviewer_id])},
        {"Role": "Judge", "Model": judge, "Price": _price(by_id[judge])},
    ],
    hide_index=True,
)
