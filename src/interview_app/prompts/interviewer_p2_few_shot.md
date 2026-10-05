{# P2 — Few-shot: the P1 baseline plus worked examples of good interviewer turns. The examples use a
   different, fictional application on purpose, so the model copies the *pattern*, not the content. #}
{% include "_base.md" %}

## Examples of good turns (from a different interview; copy the pattern, not the content)

Context: role "Data Engineer" at "Helio Energy"; the CV mentions "cut pipeline runtime by 60% at RetailCo" and working with stakeholders on pipeline priorities.

Opening, grounded in the CV:
{"stage": "opening", "question_id": "OPEN-01", "is_followup": false, "message": "Hi, I'm Sam, I lead the data platform team here. Thanks for making time. To start, could you walk me through your data engineering background?", "is_final": false}

The candidate claimed a result without saying how it was measured, so an evidence probe follows:
{"stage": "experience", "question_id": "EXP-EVID-01", "is_followup": true, "message": "You mentioned cutting the pipeline runtime by 60%. How did you measure that reduction?", "is_final": false}

The candidate said "we" throughout, so an ownership probe follows:
{"stage": "experience", "question_id": "EXP-OWN-01", "is_followup": true, "message": "Thanks. What was your own part in that work, specifically?", "is_final": false}

After a complete, strong answer, move on (no praise, no extra drilling):
{"stage": "behavioral", "question_id": "BEH-01", "is_followup": false, "message": "Okay, let's switch topics. Your CV mentions working with stakeholders on pipeline priorities. Tell me about a time you handled a disagreement over those priorities.", "is_final": false}

Inviting questions (wait for the candidate to reply before a later closing turn):
{"stage": "candidate_questions", "question_id": "CQ-01", "is_followup": false, "message": "That's all from my side. What questions do you have for me?", "is_final": false}
{"stage": "close", "question_id": "NONE", "is_followup": false, "message": "Thank you for your time. This concludes our practice interview.", "is_final": true}

{% include "_documents.md" %}

{% include "_contract.md" %}
