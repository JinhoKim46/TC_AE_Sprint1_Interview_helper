"""Final evaluation of a finished interview: the candidate's feedback report.

exchanges.py  group the transcript into exchanges (code)
metrics.py    deterministic numbers: answer length, talk ratio... (code)
judge.py      LLM-as-a-judge: rationale + evidence + score per rubric item (model)
aggregate.py  weights, normalisation, penalties, band — all from docs/rubric.json (code)
service.py    runs the pipeline and stores the report
"""
