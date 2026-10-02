"""The code-map generator (reports/tools/build_code_map.py) on the real repo: a few known facts.

If one of these fails after a refactor, either the extractor lost track of something (fix it) or the
fact changed on purpose (update the test and regenerate the report).
"""

import sys

import pytest

from interview_app.config import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "reports" / "tools"))
import build_code_map  # noqa: E402  (a script folder, not a package)

E = "interview_app.interview.engine"


@pytest.fixture(scope="module")
def code_map() -> dict:
    return build_code_map.build()


def _edges(m: dict, src: str) -> set[str]:
    return {e["to"] for e in m["edges"] if e["from"] == src}


def test_lists_every_module_under_src(code_map):
    src = PROJECT_ROOT / "src"
    expected = set()
    for path in src.rglob("*.py"):
        parts = list(path.relative_to(src).with_suffix("").parts)
        expected.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    assert expected <= set(code_map["modules"])


def test_answer_runs_the_guards_and_the_interviewer(code_map):
    assert f"{E}:_check_answer" in _edges(code_map, f"{E}:answer")
    assert "interview_app.security.limits:check_answer_length" in _edges(code_map, f"{E}:_check_answer")
    # Through the `guard: InjectionGuard` field of EngineDeps.
    assert "interview_app.security.injection:InjectionGuard.check_answer" in _edges(
        code_map, f"{E}:_check_answer"
    )


def test_injected_factory_is_bound_to_its_implementations(code_map):
    assert f"{E}:EngineDeps.make_llm" in _edges(code_map, f"{E}:_interviewer_turn")
    assert "app.ui_common:engine_deps.make_llm" in _edges(code_map, f"{E}:EngineDeps.make_llm")


def test_template_includes(code_map):
    templates = code_map["templates"]
    assert "_base.md" in templates["interviewer_p4_role_rich.md"]["includes"]
    renderers = {r["symbol"] for r in templates["interviewer_p4_role_rich.md"]["rendered_by"]}
    assert renderers == {"interview_app.interview.prompting:interviewer_system_prompt"}


def test_agents(code_map):
    agents = {a["role"]: a for a in code_map["agents"]}
    assert {"interviewer", "planner", "judge", "guard", "live_score", "lab_judge", "candidate_sim"} <= set(
        agents
    )
    assert agents["judge"]["models_field"] == "judge"
    assert [s["class"] for s in agents["judge"]["schemas"]] == ["interview_app.evaluation.schemas:Judgement"]
    assert agents["guard"]["models_field"] == "jev"  # the default inside DecisionClient.decide
    assert {"system", "user", "assistant"} <= set(agents["interviewer"]["message_roles"])


def test_database_access(code_map):
    tables = code_map["tables"]
    assert f"{E}:_add_turn" in tables["Turn"]["writers"]
    assert "interview_app.llm.calllog:make_db_recorder.record" in tables["LLMCall"]["writers"]
    assert "interview_app.history:delete_session" in tables["InterviewSession"]["deleters"]
