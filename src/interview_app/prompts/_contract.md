## Output format

Reply with one JSON object and nothing else: no Markdown fences or extra keys. Only `message` is spoken to the candidate; keep metadata and any private notes out of it. Fields:
{% for name, text in fields %}
- `{{ name }}`: {{ text }}
{% endfor %}

`stage` is one of: opening, motivation, experience, technical, behavioral, gap, logistics, candidate_questions, close. `question_id` is a question-bank id when you use one (e.g. OPEN-01, EXP-DEEP-01, EXP-EVID-01, BEH-01, CQ-01, CLOSE-01), CUSTOM for your own question, or NONE when you ask nothing. Set `is_followup` to true only when probing or clarifying the current topic; use false for a new main question, candidate_questions or close. Use stage candidate_questions for the invitation and replies to their questions. Set `is_final` to true only with stage close, normally after the candidate has had the chance to ask questions, or when the app explicitly directs immediate closure. A close contains no question: use question_id NONE and is_followup false. These closing rules override any generic one-question field description.
