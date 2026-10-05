"""Waits that move: the step list for preparing an interview, and the moving bar for the report.

Both draw into an `st.empty()` slot, so every redraw replaces the last one in place. The motion itself is in
the design system's stylesheet (app/styles/app.css, "Waits"): the containers here only get keys with the
fixed prefixes `ih-step-` and `ih-wait-`, which the stylesheet animates and which `prefers-reduced-motion`
turns still. No markup is built here, so nothing from a model or a user can end up in it.
"""

import streamlit as st

from interview_app.interview.engine import PrepStep

# What the candidate reads for each preparation step, as it runs (the label gets "…" while it is the
# current step). In plain words: the candidate needs to know it is working, not how.
STEP_LABELS = {
    PrepStep.DOCUMENTS: "Reading your documents",
    PrepStep.PLAN: "Planning the questions",
    PrepStep.OPENING: "Writing the opening question",
    PrepStep.VOICE: "Recording the voice",
}


class StepProgress:
    """A progress bar plus one line per step: done (a tick), current (animated) or still to come.

    Call `finished(step)` as each step finishes, e.g. as the engine's `on_step` callback. Each step that is
    reported as finished is ticked off, along with any step before it, so a skipped step can't stall the list.
    """

    def __init__(self, steps: list[PrepStep]):
        self.steps = steps
        self.done = 0
        self._draws = 0  # part of each container key: the keys must stay unique within one script run
        self._bar = st.progress(0.0)
        self._list = st.empty()
        self._draw()

    def finished(self, step: PrepStep) -> None:
        if step in self.steps:
            self.done = max(self.done, self.steps.index(step) + 1)
        self._draw()

    def stop(self) -> None:
        """A failed start: freeze the list where it stopped (no motion on a step that won't finish)."""
        self._draw(still=True)

    def _draw(self, still: bool = False) -> None:
        self._draws += 1
        total = len(self.steps)
        current = None if still or self.done >= total else self.steps[self.done]
        text = (
            f"{STEP_LABELS[current]}… (step {self.done + 1} of {total})"
            if current
            else ("Ready" if self.done >= total else "Stopped")
        )
        self._bar.progress(self.done / total, text=text)
        with self._list.container():
            for i, step in enumerate(self.steps):
                if i < self.done:
                    state, line = "done", f":material/check_circle: {STEP_LABELS[step]}"
                elif step == current:
                    # The stylesheet animates this one; the word "now" carries the state without the motion.
                    state, line = "active", f":material/pending: **{STEP_LABELS[step]}…** (now)"
                else:
                    state, line = "todo", f":material/radio_button_unchecked: {STEP_LABELS[step]}"
                with st.container(key=f"ih-step-{state}-{self._draws}-{i}"):
                    st.markdown(line)


def moving_bar(slot, key: str) -> None:
    """An indeterminate bar (motion only, no fake percentage) for a wait with no steps, drawn into `slot`
    (an `st.empty()`); clear it with `slot.empty()` when the wait ends."""
    with slot.container(key=f"ih-wait-{key}"):
        # The bar is the container's ::after (stylesheet); an element is needed for Streamlit to draw it.
        st.caption("Working on it…")
