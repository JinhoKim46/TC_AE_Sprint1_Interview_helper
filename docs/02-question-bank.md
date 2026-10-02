# Question Bank

These are templates, not scripts. The interviewer **must** fill every `{placeholder}` with concrete content from the JD, CV, cover letter or company notes. Each entry lists:

- **Probes**: the signal the question is designed to surface (this links to rubric items in `03-evaluation-rubric.md`)
- **Strong**: what a strong answer contains
- **Weak**: typical failure patterns

IDs are stable. The interviewer logs them as `meta.question_id`.

---

## OPEN — Opening / warm-up

### OPEN-01 "Tell me about yourself." / "Walk me through your background."
- **Probes:** communication, self-positioning, relevance to the role
- **Strong:** 60–90 s; leads with current focus and domain rather than a chronological CV recap; 2–3 concrete results; explains any change of direction in one calm sentence; ends by connecting to *this* role
- **Weak:** >3 min chronological walk-through; no numbers; nothing linking to the role; reads out the CV

### OPEN-02 "What are you looking for in your next role?"
- **Probes:** motivation fit with the JD's actual day-to-day
- **Strong:** specific about the work content (problem type, domain, IC vs. lead) in a way that matches the JD
- **Weak:** generic ("growth, a good team, interesting challenges"); describes a different role than the one advertised

---

## MOT — Motivation & company

### MOT-01 "Why {company}?"
- **Probes:** company research, genuine interest
- **Strong:** names something specific (a product, research line, publication, technology, market position, team) and links it to their own experience
- **Weak:** could be said about any company; flatters without content; factual errors about the company

### MOT-02 "Why this role, and why now?"
- **Strong:** links the timing to their career situation (finishing a degree, a change of direction) with no defensiveness
- **Weak:** sounds like "any job will do"; badmouths a previous employer

### MOT-03 "In your cover letter you wrote '{cover_letter_quote}'. What did you mean by that?"
- **Probes:** consistency between the cover letter and the spoken answer; ownership of the written claims
- **Strong:** expands with a concrete example consistent with the letter
- **Weak:** can't elaborate; contradicts the letter

### MOT-04 "Where do you see yourself in {3–5} years?"
- **Strong:** a plausible trajectory consistent with the role (depth in the domain, scope growth)
- **Weak:** a trajectory the role clearly can't offer; "your job"; no answer

---

## EXP — Experience deep-dive (CV projects)

### EXP-DEEP-01 "Walk me through {cv_project}, from the problem to the result."
- **Probes:** structure, depth, ownership, results
- **Strong:** clear problem → constraints → approach → own contribution → result with metric → limitations
- **Weak:** only describes the method; no problem framing; no result

### EXP-OWN-01 (follow-up) "What was *your* part specifically?"
- **Probes:** individual ownership
- **Strong:** distinguishes "I" from "we" precisely; names their own decisions and artifacts
- **Weak:** stays at "we"; takes credit for the whole team's work with no specifics

### EXP-EVID-01 (follow-up) "Your CV says {cv_metric}. How was that measured, and against what baseline?"
- **Probes:** evidence quality, scientific rigor, honesty
- **Strong:** names the metric, baseline, dataset/test set, and caveats (e.g. reader-study design, statistical significance)
- **Weak:** can't explain the number; inflates it; the explanation contradicts the CV

### EXP-DEC-01 (follow-up) "Why {chosen_method} rather than {alternative}?"
- **Probes:** decision-making, breadth
- **Strong:** compares alternatives on concrete criteria (data availability, compute, latency, robustness); mentions what was tried and rejected
- **Weak:** "it's state of the art"; can't name an alternative

### EXP-FAIL-01 (follow-up) "What didn't work in that project?"
- **Probes:** reflection, honesty
- **Strong:** a specific failure, its diagnosis, and what changed as a result
- **Weak:** "nothing really"; a humblebrag

### EXP-TRANS-01 "How did this work get from a research result to something people actually used?"
- **Probes:** research-to-product translation, stakeholder work
- **Strong:** names users (clinicians, engineers, other teams), the validation step, and the hand-off/tooling
- **Weak:** stops at "we published it"

### EXP-TIME-01 "I see {timeline_item, e.g. a short tenure / a gap / a change of direction}. Can you tell me about that?"
- **Probes:** handling a sensitive question, honesty, framing
- **Strong:** short, true, non-defensive, forward-looking; no blame on others; takes responsibility for their own decision
- **Weak:** long justification; blames the employer or colleagues; evasive; inconsistent with the CV dates

---

## TECH — Technical / domain (sized to the JD)

Generate these from the JD's technical requirements. Patterns:

### TECH-FUND-01 "Explain {core_concept_from_JD} as you would to a new team member."
- **Strong:** correct, layered (intuition → mechanism → limits), adapted to the audience
- **Weak:** wrong or buzzword-only; can't simplify

### TECH-APPLY-01 "How would you approach {JD_problem} given {constraint, e.g. little labeled data / limited compute / domain shift}?"
- **Strong:** clarifies assumptions, proposes a baseline first, then improvements; names an evaluation plan and risks
- **Weak:** jumps straight to the fanciest model; no evaluation; ignores the constraint

### TECH-EVAL-01 "How would you know your model is good enough to ship / to use clinically?"
- **Strong:** distinguishes offline metrics from task-relevant evaluation (reader studies, downstream tasks); mentions failure-case analysis, robustness across sites/scanners/data shifts, and regulatory awareness where relevant
- **Weak:** "high accuracy / PSNR"

### TECH-DEBUG-01 "Your training loss is fine but validation performance degrades on data from {new_site/device}. What do you do?"
- **Strong:** systematic: check the data pipeline, distribution shift, preprocessing mismatch; ablations; domain-adaptation options
- **Weak:** "train longer / bigger model"

### TECH-SCALE-01 "How would you scale training of {model} to {data_size} on {infra from JD}?"
- **Strong:** concrete (data loading, distributed strategy, mixed precision, checkpointing, experiment tracking), with trade-offs
- **Weak:** vague "use the cloud"

### TECH-GAP-01 "The role requires {jd_requirement_marked_gap}. How would you get up to speed?"
- **Probes:** honesty about gaps, learning ability, transfer
- **Strong:** acknowledges the gap plainly; maps transferable experience concretely; gives a realistic ramp-up plan
- **Weak:** claims experience they don't have; dismisses the requirement

### TECH-CODE-01 (optional, live) "Write/describe a function that {small task relevant to JD}." (pseudo-code is acceptable in voice mode)
- **Strong:** clarifies inputs, handles edge cases, explains complexity
- **Weak:** silent coding with no reasoning; ignores edge cases

### TECH-LIT-01 (research roles) "What recent work in {field} do you find most important, and why?"
- **Strong:** names specific work, gives a critical view (strength + limitation), relates it to their own work
- **Weak:** can't name anything recent; uncritical

---

## CASE — ML case / system design (for `ml_case`, `system_design`)

### CASE-01 "{company} wants to {product_goal_in_company_domain}. Design the ML system end to end."
Expected arc the interviewer steers through, one step per turn:
1. Clarify goal, users, constraints, success metric
2. Data: sources, labels, quality, privacy (GDPR, medical data)
3. Baseline → model choice with trade-offs
4. Evaluation: offline + task/clinical/user evaluation
5. Deployment: latency, hardware, monitoring, drift, rollback
6. Risks: failure modes, bias, regulatory (e.g. MDR / FDA where relevant)

- **Strong:** drives the structure themselves, asks clarifying questions first, makes explicit trade-offs, stays within constraints
- **Weak:** jumps to the model; never defines success; ignores deployment and risk

---

## RES — Research talk Q&A (for `research_talk`)

After the candidate's presentation:
- RES-01 "What is the key assumption your method relies on, and when does it break?"
- RES-02 "How does this compare to {strong_baseline}? Was the comparison fair?"
- RES-03 "What would it take to get this into routine clinical / product use?"
- RES-04 "If you had six more months, what would you do next?"
- RES-05 "How would this transfer to {company_problem}?"

- **Strong:** precise, admits limitations, separates evidence from speculation
- **Weak:** defensive; overclaims; can't connect the work to the company

---

## BEH — Behavioral (STAR expected)

Pick the competencies the JD names. Each answer should contain Situation, Task, Action, Result (+ Learning).

| ID | Question | Competency |
|---|---|---|
| BEH-OWN-01 | "Tell me about a time you took ownership of something nobody asked you to do." | Initiative / ownership |
| BEH-COLLAB-01 | "Tell me about working with a stakeholder from a different discipline (e.g. clinicians, product, hardware)." | Cross-functional collaboration |
| BEH-CONF-01 | "Tell me about a disagreement with a colleague or supervisor. How was it resolved?" | Conflict handling |
| BEH-AMBIG-01 | "Describe a project where the goal was unclear at the start." | Ambiguity |
| BEH-FAIL-01 | "Tell me about a failure or a mistake and what you learned." | Accountability / learning |
| BEH-PRIO-01 | "Tell me about a time you had more work than time. How did you prioritize?" | Prioritization |
| BEH-COMM-01 | "Explain a complex technical result you had to communicate to a non-expert." | Communication |
| BEH-LEAD-01 | "Tell me about a time you led people without formal authority." | Leadership / influence |
| BEH-PRESS-01 | "Tell me about delivering under a hard deadline." | Execution under pressure |
| BEH-FEED-01 | "Tell me about critical feedback you received and what you did with it." | Coachability |
| BEH-WEAK-01 | "What is your biggest weakness?" | Self-awareness |

- **Strong:** a specific single episode (not "I usually..."), a clear personal action, a measurable or observable result, a genuine learning; 1.5–2.5 min
- **Weak:** hypothetical ("I would..."); generic; no result; the blame sits with others; a fake weakness ("I'm a perfectionist")

---

## LOG — Logistics (recruiter screen / final round)

| ID | Question | Strong answer |
|---|---|---|
| LOG-START-01 | "When could you start?" | A concrete date or notice period, consistent with the application documents |
| LOG-SAL-01 | "What are your salary expectations?" | A researched range (annual gross, in EUR for Germany), with a rationale; flexible but not vague; doesn't undercut themselves out of nervousness |
| LOG-LOC-01 | "Our team works {work_model} from {location}. How does that fit?" | Clear and honest; states any constraint early |
| LOG-AUTH-01 | "Do you need a work permit or sponsorship?" | Factual and brief |
| LOG-LANG-01 | "How is your {language}?" | Honest level (e.g. CEFR) plus a concrete improvement plan if it's below the JD's requirement |
| LOG-PROC-01 | "Are you interviewing elsewhere?" | Honest, discreet, no company names needed |

---

## CQ — Candidate's questions (the evaluator scores these)

The interviewer answers in character. The evaluator checks whether the candidate's questions were:
- specific to the role/team/company (not answerable from the JD in 10 seconds)
- about the work itself (success criteria, team setup, the hardest current problem, the research-to-product path)
- free of premature focus on perks only

Good examples the candidate may use: "What would success look like in the first 6 months?", "What's the biggest technical challenge the team faces right now?", "How does a research result get into the product here?"

---

## CLOSE

### CLOSE-01 "Is there anything else you'd like us to know?"
- **Strong:** a 20–30 s closing summary of fit (2 reasons + enthusiasm) or a clarification of something earlier
- **Weak:** "No." or a new long monologue
