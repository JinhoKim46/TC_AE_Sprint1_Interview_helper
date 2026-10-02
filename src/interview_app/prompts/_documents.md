## The application

{% for block in documents %}
{{ block }}

{% endfor %}
{% if missing %}
Not provided by the candidate: {{ missing }}. Do not ask about these documents.
{% endif %}
