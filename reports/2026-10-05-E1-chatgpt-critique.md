# E1 — ChatGPT critique of Interview Helper

Date: 2026-10-05. Reviewer: ChatGPT (Codex). Reviewed revision: `b305821f814377f3945d26225f27e66358f5dc56`, after [PR #51: E2 — ChatGPT improvements to interview prompts](https://github.com/JinhoKim46/TC_AE_Sprint1_Interview_helper/pull/51).

## Review request and scope

The user asked ChatGPT to critique the solution from the **usability, security and prompt-engineering** sides, save a report in `./reports`, and create an E1 pull request. This report addresses [Easy optional criterion 1](../docs/00-project-objective.md), including the critique, changes already made in response to the earlier prompt review, and outstanding recommendations.

Method: read the UI flows, interview engine, input guards, storage, evaluation code, templates, existing tests and recorded prompt-comparison results. A synthetic local check reproduced the quote-validation issue below. No real CVs, credentials or private transcripts were used. This was a source-based usability and implementation review: no new browser screenshots, keyboard/screen-reader audit, penetration test, provider-policy review or live model comparison was performed. Findings about UI behavior follow the code; visual quality and accessibility remain unverified in this review.

## Overall assessment

The application has a coherent practice journey and useful defensive foundations for its intended single-user, local deployment. The strongest design choice is keeping counting, scoring arithmetic, ownership checks and limits in code while models supply interview questions and assessments. The main weaknesses are user visibility into external data processing and degraded safeguards, incomplete enforcement of spending boundaries, and overconfidence that can arise from model-generated evidence and scores.

The recent prompt changes resolve clear instruction conflicts, but passing rendering tests does not establish better interview quality. Keep the app positioned as a practice aid; the current evidence does not validate its scores as hiring predictions.

## 1. Usability

### What works

The [Home flow](../app/views/home.py) presents three understandable steps and a context-sensitive next action. The [application editor](../app/views/applications.py) lets users inspect and correct extracted PDF text, and offers fictional sample data. The [interview UI](../app/views/interview.py) explains preparation/report waits, preserves submitted answers when interviewer generation fails, provides retry controls, and falls back to text when voice generation fails. Developer controls are separated from the candidate's setup flow. These are practical choices that reduce lost work and setup complexity.

### U1 — Explain external processing before the first document check — high priority

**Evidence:** [`_flag_documents`](../app/views/applications.py) sends document text to the model-backed guard during save. The visible document-entry copy explains uploading and editing, but does not explain this transmission at the decision point. [`InjectionGuard.check_document`](../src/interview_app/security/injection.py) sends chunks to Jev through the configured decision client; subsequent interview/evaluation calls also use application text.

**Impact:** a user may interpret a locally hosted application as local-only processing, even though saving a CV can already trigger an external model request. Deleting local records cannot by itself establish deletion at an external provider.

**Recommendation:** add concise copy before Save/Start identifying the configured external processing route, what text is sent, and what is stored locally. Encourage removing unnecessary identifying details. Explain that local deletion and provider retention are separate; do not make unverified promises about provider policy.

**Acceptance check:** a first-time user can see this information before any document-check request and can edit or cancel without transmitting text.

### U2 — Make estimated cost and score uncertainty visible at the decision point — medium priority

**Evidence:** [`feedback`](../app/views/interview.py) explains report generation but shows combined interview/report spend after generation. [`render_report`](../app/report_view.py) leads with a score and hiring-signal band, shows run spread when large, and places a general practice disclaimer later. Live score chips show decimal scores without an adjacent calibration explanation.

**Impact:** users can incur additional report costs without a nearby estimate, and may give precise-looking scores more authority than the evaluation supports. Several runs of the same judge reduce some variation; they do not establish correctness or remove shared bias.

**Recommendation:** show an estimated report cost/range and run count before the button. Put a short practice-only interpretation beside the headline score and live chips. Keep the existing variance disclosure; label estimates as estimates.

**Acceptance check:** report generation requires an informed click, and score meaning is understandable without reading the bottom of the report.

## 2. Security and reliability

### What works

The [guard](../src/interview_app/security/injection.py) combines deterministic rules with a model classifier. [Spotlighting](../src/interview_app/security/spotlight.py) canonicalizes text, neutralizes wrapper escapes and labels documents as data. [UI escaping](../app/ui_common.py) prevents untrusted content from being rendered as active Markdown/HTML. [PDF ingestion](../src/interview_app/ingest.py) applies upload, page, decompression and text limits. [Database handling](../src/interview_app/db.py) restricts file permissions and enables secure deletion; [voice storage](../src/interview_app/voice.py) uses private file/directory permissions and integer-derived paths.

The deployment boundary is explicit: [Streamlit](../.streamlit/config.toml) and [Compose](../compose.yaml) bind the host service to loopback. [`ensure_local_user`](../src/interview_app/users.py) is not authentication. These defaults support personal local use, not a public or shared service; preserve them unless real access controls are added.

### S1 — Model-guard outages silently reduce protection — high priority

**Evidence:** `InjectionGuard.check_answer` and `check_document` catch `LLMError` and return an allowed result with `METHOD_MODEL_UNAVAILABLE`. [`_check_answer`](../src/interview_app/interview/engine.py) returns only blocking verdicts, while `_flag_documents` retains only flagged reasons. The degraded result therefore does not reach these candidate-facing warnings. [`test_model_failure_fails_open_with_method_noted`](../tests/test_guards.py) documents the intended fallback.

**Impact:** the user can continue with rules-only checking without being told that the semantic check is unavailable. Wrapper text remains useful defense in depth, but is not an enforceable isolation boundary.

**Recommendation:** preserve availability for this local practice tool if desired, but propagate a persistent degraded-guard notice and let users retry or stop. If the deployment scope changes, make the fail-open versus fail-closed policy an explicit decision.

**Acceptance check:** simulate a guard API failure for both document save and answer submission; verify a visible warning and the recorded guard method.

### S2 — The session budget is a stopping threshold, not a strict spending ceiling — high priority

**Evidence:** [`answer` and `retry`](../src/interview_app/interview/engine.py) can run the paid guard and coaching scorer before `respond` checks `must_close`. `respond` still generates a closing model turn when the threshold is reached. [`evaluate_session`](../src/interview_app/evaluation/service.py) deliberately permits one judge run after budget exhaustion and may launch several runs when just below the limit. Document checks are user-level calls outside a session budget.

**Impact:** spend can exceed the configured threshold. This is a bounded workflow with explicit exceptions, not proof of unlimited spending, but describing every call as protected by a hard budget would be misleading.

**Recommendation:** clarify the threshold semantics now. For a true ceiling, centralize pre-call checks/reservations, account for concurrent judge runs and retries, give evaluation an explicit allowance, and retain a free deterministic way to end the interview.

**Acceptance check:** exercise an already-exhausted budget in realistic mode, coaching retries, voice and evaluation; assert which paid calls are allowed and the maximum reserved spend.

### S3 — PDF timeout does not terminate extraction — medium priority

**Evidence:** [`extract_pdf_text`](../src/interview_app/ingest.py) runs parsing in a daemon thread, calls `join(timeout_s)`, then raises an error if the thread remains alive. The source explicitly notes that the thread continues in the background.

**Impact:** timeout limits waiting in the UI, not the worker's lifetime. Existing parser limits reduce exposure, but repeated slow inputs can leave overlapping work. No denial-of-service exploit was executed in this review.

**Recommendation:** if stronger resource isolation is needed, use a terminable subprocess with bounded concurrency and memory/time limits. Keep current size and decompression checks.

**Acceptance check:** a synthetic stuck parser leaves no running worker after timeout; repeated uploads cannot accumulate workers.

## 3. Prompt engineering and evaluation

### What works

The [prompt renderer](../src/interview_app/interview/prompting.py) uses strict template variables and schema-derived output descriptions. The five variants retain different techniques, with shared grounding rules. The trailing app control message carries deterministic progress. Structured schemas, repair attempts and [evidence-aware aggregation](../src/interview_app/evaluation/aggregate.py) provide checks beyond asking the model to behave.

### P1 — Quote matching can accept a reversal of meaning — high priority, reproduced

**Evidence:** `quote_found` permits ordered fuzzy matching and does not check entailment or negation. This synthetic call returned `True` at the reviewed revision:

```python
from interview_app.evaluation.aggregate import quote_found

quote_found(
    "I have deployed models in production",
    ["T02"],
    {"T02": "I have not deployed models in production"},
)
# True
```

**Impact:** a judge-generated quote can omit “not” and still pass the validator. A positive requirement rating or strength could therefore survive validation even though its cited answer says the opposite. This reproduces a validator weakness, not an observed live judge failure.

**Recommendation:** validate each quoted span as contiguous source text after limited whitespace/punctuation normalization; treat ellipsis-separated spans explicitly and retain surrounding context for interpretation. Add a negation-omission regression case. Exact quotation alone still does not prove the associated assessment, so separately assess semantic consistency for high-impact claims.

**Acceptance check:** reject the example above while preserving legitimate punctuation normalization and genuinely separate quoted spans.

### P2 — P4 still carries conflicting reference instructions — medium priority

**Evidence:** [P4](../src/interview_app/prompts/interviewer_p4_role_rich.md) includes sections of the [interviewer guideline](../docs/01-interviewer-guideline.md) that mention hints, extra metadata and broader coverage. PR #51 now explicitly overrides conflicts using shared rules, the current app directive and the runtime JSON contract.

**Impact:** precedence is clearer, but the model still reads instructions it must subsequently disregard. More prompt text can add cost and ambiguity. P4 also combines persona enrichment and prompt chaining, so its comparison cannot isolate those two effects.

**Recommendation:** maintain an app-compatible guideline excerpt without obsolete metadata or hint instructions. Preserve the five educational variants, but describe P4's combined technique accurately. Evaluate behavior before choosing it solely on historic scores.

**Acceptance check:** rendered prompts contain only supported operational instructions, and examples validate against the actual turn schema.

### P3 — Historical comparisons do not measure the current prompts — medium priority

**Evidence:** [`docs/05-prompt-comparison.md`](../docs/05-prompt-comparison.md) explicitly dates its results to earlier revisions and describes a small experiment using one fictional application and simulated personas. PR #51 changed shared rules, examples, judging instructions and simulator constraints without a live rerun.

**Impact:** current realism, safety, latency and cost gains remain unmeasured. Changing both interviewer and simulator also changes the evaluation conditions, making a simple old-versus-new score comparison harder to interpret.

**Recommendation:** record prompt hashes, model versions and session settings; compare interviewer revisions under a fixed simulator/judge setup, then evaluate simulator/judge changes separately. Add several fictional domains, sparse documents, Quick sessions and human-rated examples. Measure multipart questions semantically, not just by counting question marks.

**Acceptance check:** published results identify the exact configuration, sample size, uncertainty and failures; historical figures remain clearly labeled.

## Changes made because of the ChatGPT review

The earlier review in this conversation led to the following changes, merged in **PR #51** before this E1 report. They are implemented prompt improvements, not claims that all findings above are fixed.

| Review finding | Implemented response |
| --- | --- |
| Few-shot examples contradicted the one-question rule and promised an unsupported hiring timeline. | Rewrote examples around one answerable focus and a neutral practice close. |
| Planning and guideline coverage could compete with short-session budgets. | Made app pacing directives authoritative and prioritized probes within the configured count. |
| Closing and follow-up metadata were ambiguous. | Clarified stage, finality, follow-up flags and question-free closing behavior. |
| Judge instructions blurred absent evidence and weak evidence. | Defined null handling, requirement levels, applicable-item coverage and candidate-turn citation scope. |
| Simulated candidates could invent measurement evidence to satisfy their persona. | Made factual limits override persona demands and exempted brief closing exchanges from word minimums. |

Validation recorded for PR #51: **156 affected offline tests passed**, lint and whitespace checks passed, and GitHub CI's checks and Docker build passed. A new regression test parses the six few-shot examples against the runtime schema. Those checks establish compatibility and selected contracts, not live model quality.

This E1 change adds the critique and its documentation links only. U1–U2, S1–S3 and P1–P3 are follow-up work unless their text explicitly identifies an existing mitigation. In particular, the reproduced quote weakness is not fixed by this report.

## Prioritized follow-up

1. Fix quote-span validation and add the negation regression case; improve trust in evidence before refining score presentation.
2. Add pre-transmission privacy copy and visible degraded-guard status.
3. Define and enforce budget semantics across guard, coaching, closing, voice and evaluation calls.
4. Simplify the P4 reference instructions and rerun a controlled prompt evaluation.
5. Improve cost/uncertainty presentation and isolate PDF parsing if stronger resource boundaries are required.

## Criterion traceability

**E1:** this report contains the requested ChatGPT critique across all three dimensions, evidence, recommendations and a record of changes already made in response to the prompt review.

**E2:** PR #51 carries the user-requested E2 label. The repository's course brief defines E2 more narrowly as domain-specific prompting. Those general interview-prompt improvements support it, but this report does not certify domain-specific coverage or measured gains. Demonstrating that criterion still needs explicit domain examples and evaluation evidence.
