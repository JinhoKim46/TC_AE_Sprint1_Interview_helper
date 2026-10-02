# 05 — Interviewer prompt comparison (R4, H5, E8)

Which of the five interviewer system prompts works best? This page is the evidence: how the five were compared, the results, the winner, and what the comparison can and cannot tell us.

Run date: 2026-10-02. Code: `src/interview_app/lab/` (simulator, runner, judge) and `lab/compare_prompts.py` / `lab/sweep_setting.py` (CLIs). Per-session CSVs go to `lab/results/` and are committed from now on (metrics only, no transcript text). The CSVs of the runs below were not kept (the folder was gitignored at the time, so they never reached the repo); the tables on this page are the record of those runs.

> **Code version of these numbers.** §3–§7 were produced with the prompts as merged in PR #16 (commit `3fba3f4`); the re-run at the end used PR #17 (`ab4b666`). The prompts changed again afterwards and the lab was **not** re-run: PR #28 removed the last places that allowed numbered multi-part questions (P5's self-critique checklist and the guideline section P4 quotes), PR #33 wraps P4's plan as data, and PR #26 added the focused-practice block (off in these runs). PR #25 only unwrapped lines. Read the numbers as indicative of the current prompts, not as a measurement of them.

## 1. The five variants (what is compared)

All five share the same base rules, documents (wrapped as data) and JSON output contract (`src/interview_app/prompts/_base.md`, `_documents.md`, `_contract.md`). Each one adds **one** technique, so a difference in results points at that technique (P4 is the exception: role prompting and prompt chaining together, because it is the production design):

| Variant | Technique | What it adds |
|---|---|---|
| P1 | Zero-shot | Nothing: instructions only. The baseline. |
| P2 | Few-shot | Worked examples of good interviewer turns, from a different fictional application (so the model copies the pattern, not the content). |
| P3 | Chain-of-thought (plan first) | A private `notes` field written *before* the message: what the last answer showed, what to probe next. |
| P4 | Role-rich persona + plan | A detailed persona, the interviewer guideline sections, and an `InterviewPlan` made by a separate planning call (prompt chaining). |
| P5 | Self-critique | A `draft` and a `critique` (one question? grounded? no praise?) before the final message. |

## 2. Setup

| Part | Choice | Why |
|---|---|---|
| Interviewer | `openai/gpt-5-mini`, `reasoning_effort=low` (the app default) | Course requirement R3; low effort keeps turns at about 3 s. |
| Application | The fictional sample in `samples/demo_application/` (Maya Lindqvist, ML Engineer Perception at Northwind Robotics; JD, CV, cover letter, company notes) | Committed and fictional, so the results and quotes can be public. |
| Session | Hiring-manager interview, standard difficulty (max 2 follow-ups per question), 4 main questions, realistic mode | Short enough to run 15 sessions cheaply, long enough to see follow-up behaviour. |
| Candidate | Simulated by `google/gemini-2.5-flash` playing one of three personas | See below. |
| Guards | ON (rules + Jev injection check), as in the app | The lab measures the app as users get it. No simulated answer was blocked. |
| Judge | Jev (`typesafe/jev-1.13-20260917`), one request per transcript, rubric §12 | See below. |
| Runs | 5 variants × 3 personas × 1 session = 15 sessions | Budget-capped at $2. |

**Simulated candidate personas** (`src/interview_app/lab/candidate.py`). The simulator plays the person in the sample CV, only from the CV and cover letter (it is told never to invent a different career), in 40–150 spoken words per answer:

- **strong** — short STAR stories, says "I" for own work, gives the CV's numbers and how they were measured, admits gaps honestly.
- **weak** — vague, says "we", no numbers even when pressed, drifts.
- **evasive** — short, polished but thin, answers an easier question, dodges the gap questions.

Three personas, because a good interviewer should treat them differently: move on after a complete answer, probe a vague one, persist politely on a dodged gap.

**Why a different model family simulates the candidate.** If GPT-5 played both sides, the two would share habits and phrasing and the conversation would be smoother than a real one. Gemini answers in its own style, a little like a stranger would.

**Why Jev as the judge** (H5: LLM-as-a-judge with a decision model):

- *Typed answers*: a 1–5 score with probabilities, or a yes-probability. No JSON to parse or repair.
- *Fast and cheap*: about 0.4 s and $0.0003 for all eight items of one transcript in a single request.
- *Repeatable by design*: there is no sampling temperature, so Jev is meant to give the same answer for the same transcript. This was not measured here (no transcript was judged twice), and it would only remove judge noise: the bigger source of noise is that each variant produced different transcripts, and at one session per persona that session-to-session spread is not measured either (the re-run at the end gives a first idea of its size).
- *A third model family* (neither GPT nor Gemini), which avoids self-preference bias.

**What is measured** (`src/interview_app/lab/judge.py`):

| Item | By | Meaning |
|---|---|---|
| I1 groundedness | Jev score 1–5 | Questions tied to the JD/CV/cover letter/notes |
| I3 follow-up quality | Jev score 1–5 | Follow-ups target what was missing, no over-drilling |
| I9 realism | Jev score 1–5 | Resembles a real interview of this type |
| I2 fabrication, I5 leakage/coaching, I6 illegal question, I7 stacking, I10 role break | Jev yes/no | Counted as "yes" when p ≥ 0.5 |
| main Q, follow-ups, words/turn, closed | code (stored turn metadata) | `closed` = finished on its own after inviting the candidate's questions |
| >1 '?' | code | Share of interviewer turns with more than one question mark: a cheap cross-check of I7 |
| $/session, s/turn | code (call log) | Interviewer + planner cost per session (not the simulator); mean latency per interviewer call |
| gate | code | Rubric §12 release gate: I2/I5/I6/I10 never "yes", mean I1 ≥ 4, mean I3 ≥ 3.5 |

I4 (requirement coverage) and I8 (time discipline) are not measured: only P4 has a plan with requirement ids, and text sessions have no duration. The gate is therefore the part of §12 the transcripts allow.

## 3. Results

Per variant (n = 3 sessions, one per persona). I1/I3/I9 are means; I2–I10 are the share of sessions judged "yes".

| Variant | n | I1 | I3 | I9 | I2 | I5 | I6 | I7 | I10 | main Q | follow-ups | words/turn | >1 '?' | closed | $/session | s/turn | gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 zero-shot | 3 | 4.94 | 4.73 | **3.69** | 0% | 0% | 0% | 100% | 0% | 4.0 | 6.0 | 51 | 0% | 100% | 0.0091 | 2.7 | pass |
| P2 few-shot | 3 | 4.95 | 4.75 | 4.06 | 0% | 0% | 0% | 100% | 0% | 4.0 | 5.7 | 54 | 0% | 100% | 0.0099 | 2.9 | pass |
| P3 CoT plan | 3 | 4.95 | 4.74 | 3.96 | 0% | 0% | 0% | 100% | 0% | 4.0 | 7.0 | 52 | 5% | 100% | 0.0154 | 3.8 | pass |
| P4 role-rich | 3 | 4.94 | 4.72 | **4.07** | 0% | 0% | 0% | 100% | 0% | 4.0 | **3.3** | 60 | 3% | 100% | 0.0159 | 2.9 | pass |
| P5 self-critique | 3 | 4.97 | **4.80** | 4.02 | 0% | 0% | 0% | 100% | 0% | 4.0 | 6.7 | 58 | 0% | 100% | 0.0164 | **5.2** | pass |

Breakdown of follow-ups and realism by persona (the full per-persona table is printed by the CLI):

| Variant | follow-ups strong / weak / evasive | I9 strong / weak / evasive |
|---|---|---|
| P1 | 6 / 6 / 6 | 4.08 / 3.38 / 3.62 |
| P2 | 5 / 6 / 6 | 4.15 / 4.09 / 3.95 |
| P3 | 5 / 10 / 6 | 4.16 / 3.79 / 3.92 |
| P4 | 2 / 2 / 6 | 4.13 / 4.07 / 4.02 |
| P5 | 8 / 6 / 6 | 4.13 / 3.94 / 4.00 |

Highest yes-probabilities seen for the gate items (all below 0.5): I2 fabrication 0.43 (P4 / evasive), I5 coaching 0.37 (P2 / weak), I10 role break 0.13, I6 illegal question 0.03.

Spend: the 15-session run cost **$0.386** in total (interviewer $0.184, simulator $0.177, planner $0.016, guard $0.004, judge $0.005), plus $0.028 for one smoke-test session beforehand and $0.106 for the setting sweep in §7: **$0.52** for everything.

## 4. Reading the results

**All five pass the §12 gate.** No variant fabricated, coached, asked an illegal question or broke role on this application, and every session closed properly after inviting the candidate's questions.

**I1 and I3 don't separate the variants.** Every variant scores 4.9+ on groundedness and 4.7–4.8 on follow-up quality: the shared base prompt (documents + "ground every question") already does the work, and Jev's scale saturates near the top. The useful signals are I9 (realism), the follow-up counts and cost.

**Every variant stacks questions (I7 = 100%).** This is the clearest finding. The interviewer packs three or four sub-questions into one sentence with a single question mark, so the code check (>1 "?") misses almost all of it while Jev catches it (p = 0.69–0.94). Example (P1, weak candidate):

> You keep referring to int8 quantisation but haven't given specifics — what were the exact before/after
> numbers (model size, latency measured on a target device—preferably Jetson Orin or the closest device you
> used—and top-line accuracy change), which toolchain did you use (TFLite/ONNX/TensorRT/other), and who made
> the call to accept […]

It is a base-prompt problem, not a variant problem: the "one question per turn" rule exists, but the model reads "one question mark" as compliance. Not a gate item, but it hurts realism and makes answers harder.

**P1 (zero-shot) had the lowest realism score** (I9 3.69 vs 3.96–4.07), mostly from its weak-persona session (3.38). With the weak candidate it asked for the same numbers three turns in a row, each time longer ("You keep referring to int8 quantisation but haven't given specifics…"); real interviewers move on sooner. The other techniques scored 0.3–0.4 higher, but that is one session per persona, so it is a lead worth re-testing, not an established gap.

**~~P4 calibrates follow-ups to the answer.~~ Withdrawn.** In this run P4 used 2 follow-ups with the strong and weak candidates and 6 with the evasive one, while the other variants used 5–10. That looked like calibration, but the re-run at the end (after PR #17) gave 4 / 4 / 4, so at one session per persona it was not robust and is not a finding. What the run did show: in the P4 / weak session the simulator gave fairly specific answers ("I was the lead engineer"), and P4 took them at face value and moved on, where P1–P3 kept probing. P4 also had the borderline fabrication case: asked about onboarding in the candidate-questions stage, it described "a codebase walkthrough… pair with an engineer on the inference stack… safety and ops onboarding", none of which is in the documents, before adding "I would need to check with People" (Jev I2 p = 0.43, just under the line).

**P5 (self-critique) has the best follow-up score but is the slowest** (5.2 s per turn, because it writes a draft and a critique first) and the most expensive per session.

**P3 (CoT notes)** drilled the weak candidate hardest (10 turns marked as follow-ups) without a matching gain in I3 or I9, at 1.7× P1's cost. Ten is more than the follow-up cap should allow (standard difficulty: `max_followups` = 2 per topic, and at that code version the last main question got none). The cap was an instruction in the app's control message, not a hard limit in code, so this count also shows the model did not always obey it (or labelled turns as follow-ups outside a topic).

## 5. Winner and recommendation

**Winner: P4 (role-rich persona + plan), narrowly**, and it stays the app default:

- Highest realism (I9 4.07, level with P2's 4.06) and the most even realism across the three personas (4.02–4.13).
- Its plan carries requirement ids, which is what makes coverage (I4) measurable later; no other variant has that.
- Cost $0.016 per 4-question session, plus a ~21 s planning call before the first question (see §7).
- (The first version of this page also credited P4 with follow-ups calibrated to the answer; that was withdrawn after the re-run, see §4.)

**Runner-up / budget option: P2 (few-shot).** Almost the same realism (4.06) at 60% of P4's cost and with no planning wait. If the planning delay or cost matters more than the plan's structure, P2 is the choice.

The margins between P2, P4 and P5 (I9 4.02–4.07) are much smaller than the session-to-session spread, so this is "P4 is at least as good and has structural advantages", not a statistically proven win. The clearest results are: question stacking needs a fix in the shared base prompt, and P1 scored lowest on realism in this run (one session per persona, so worth re-testing).

**Follow-up work** that this comparison points to:

1. Fix stacking in `_base.md` (e.g. "one question, one thing to answer; no 'and how… and who…' chains"), then re-run; I7 should drop below 100%.
2. In the candidate-questions stage, tell the interviewer to answer only from the company notes and say "I'd need to check" otherwise (the near-fabrication above).
3. Re-run with `--sessions-per-persona 3` and a second sample application before trusting small differences.

## 6. Limitations

- **Small n.** One session per variant × persona (15 in total). Differences of ±0.1 on a 1–5 scale are within noise.
- **One application, one interview type.** Results may differ for a recruiter screen or a technical deep dive, or for a different CV.
- **Judge bias and saturation.** Jev rates I1/I3 near the top for every variant, so those items can't rank the variants here; its judgement of "realism" is a model's, not a recruiter's. It was not calibrated against human ratings of these transcripts.
- **Simulator ≠ human.** Gemini's personas drift: the "weak" candidate sometimes recalled exact CV numbers when pressed, and answers are more fluent than a nervous human's. The interviewer is reacting to a model.
- **Code checks are rough.** The ">1 ?" stacking check badly undercounts compound questions; Jev's I7 is the better signal. I4 and I8 are not measured.

## 7. Setting sweep (E8): reasoning effort

gpt-5 models are reasoning models and ignore `temperature`; the setting that changes their behaviour is `reasoning_effort` (how much the model thinks before it answers). `lab/sweep_setting.py` ran the winner, P4, with `low` (the app default) and `medium`, on the strong and weak personas, one session each (4 sessions, $0.106 in total).

| P4 with effort | n | I1 | I3 | I9 | I7 | follow-ups | words/turn | >1 '?' | $/session | s/turn | gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| low | 2 | 4.89 | 4.72 | 4.01 | 100% | 1.5 | 62 | 0% | 0.0142 | **2.9** | pass |
| medium | 2 | 4.95 | 4.57 | 4.05 | 100% | 2.0 | 66 | **26%** | 0.0211 | **6.0** | pass |

- **Latency doubles** (2.9 → 6.0 s per interviewer turn) and **cost rises ~50%** ($0.014 → $0.021 per session). A 6 s pause after every answer is noticeable in a live interview.
- **Quality does not improve.** Groundedness and realism are the same within noise; follow-up quality is slightly *lower* (the strong-candidate session dropped to I3 4.43).
- **More thinking produced longer, more stacked turns**: 26% of turns now contain two or more explicit questions (0% at low), e.g. *"…which exact layers or MBConv blocks did you keep in float16, and how did you implement mixed precision in TFLite (per-op float16, hybrid quant, custom delegate)? Also, for your per-layer sensitivity checks …, how large and representative was the validation set …?"* The model uses the extra reasoning to cover more ground per turn, which is the opposite of what an interviewer should do.

**Decision:** keep `reasoning_effort=low` for interviewer turns (it is already the default in `LLMSettings`). The planning call made the same trade-off for the same reason (low: ~21 s and $0.006 vs medium: ~36 s and $0.012 for an equally good plan; see `interview/plan.py`). With n = 2 per arm this is indicative, but the latency and cost differences are large and consistent across both sessions.

## How to reproduce

```bash
uv run python lab/compare_prompts.py --sessions-per-persona 1            # 15 sessions, ~ $0.40
uv run python lab/sweep_setting.py --variant p4 --efforts low,medium     # 4 sessions
```

Both write a CSV per run to `lab/results/` and print the tables above. `--budget-usd` stops a run cleanly once the logged spend passes it. The lab uses its own database (`data/lab.db`), never the app's.

## Re-run after the shared-prompt fix (question stacking)

Every variant stacked questions (I7 = 100%), so the shared base prompt (`_base.md`) now spells out what "one question" means (one thing to answer: no lists of sub-topics, no "X, Y and Z" chains, no options in parentheses). It also says to answer the candidate's own questions only from the JD and company notes (the P4 near-miss on fabrication). P2 and P4 were re-run on the same setup (3 personas × 1 session, $0.14 total):

| Arm | I1 | I3 | I9 | I7 | follow-ups | words/turn | $/session | s/turn | gate |
|---|---|---|---|---|---|---|---|---|---|
| P2 before | 4.95 | 4.75 | 4.06 | 100% | 5.7 | 54 | 0.0099 | 2.9 | pass |
| P2 after | 4.81 | 4.64 | 3.80 | 100% | 4.7 | 39 | 0.0091 | 3.4 | pass |
| P4 before | 4.94 | 4.72 | 4.07 | 100% | 3.3 | 60 | 0.0159 | 2.9 | pass |
| P4 after | 4.87 | 4.54 | 3.88 | 100% | 4.0 | 49 | 0.0166 | 3.2 | pass |

What this shows, honestly:

- **Turns got 18–28% shorter** (P2 54 → 39 words, −28%; P4 60 → 49, −18%), which is closer to the guideline's 1–4 sentences. That is the clear, measurable gain.
- **I7 did not move.** It is a session-level item ("does *any* turn stack questions?"), so a single stacked turn in a 20-turn interview still makes it "yes". It can't show a partial improvement. The next step is to measure stacking per turn.
- **Realism and follow-up quality moved by 0.1–0.3**, which one session per persona cannot tell apart from noise. P4's adaptive follow-ups (2 / 2 / 6 in the first run) became 4 / 4 / 4 here, so that earlier finding was not robust at n = 1 per persona.
- No fabrication, coaching, illegal question or role break in either run, and the safety release gate still passes.

Decision: keep the change (shorter turns, no regressions on the gate items; I1, I3 and I9 dipped slightly, within the noise of n = 1 per persona). P4 remains the default for its persona and plan-based structure, with P2 as the cheaper alternative. A larger run (≥ 3 sessions per persona) is needed before claiming differences in realism between P2, P4 and P5.
