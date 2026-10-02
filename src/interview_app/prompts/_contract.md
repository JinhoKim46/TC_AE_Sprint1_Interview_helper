## Output format

Reply with one JSON object and nothing else. Fields:
{% for name, text in fields %}
- `{{ name }}`: {{ text }}
{% endfor %}

`stage` is one of: opening, motivation, experience, technical, behavioral, gap, logistics, candidate_questions, close.
`question_id` is a question-bank id when you use one (e.g. OPEN-01, EXP-DEEP-01, EXP-EVID-01, BEH-01, CQ-01, CLOSE-01), CUSTOM for your own question, or NONE when you ask nothing.
Set `is_final` to true only on your closing turn, after the candidate has had the chance to ask questions.
