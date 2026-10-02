"""Build `reports/code-flow-report.html` from `reports/code_map.json`.

    uv run python reports/tools/build_code_flow_html.py     # (build_code_map.py runs this for you)

The page is one self-contained file: the code map is embedded as JSON and drawn by the page's own
script (code_flow_template.html). Two kinds of content go in:

- **Generated facts** (modules, functions, call edges, model roles, templates, tables) come from the code
  map, so they are as current as the last run of `build_code_map.py`.
- **Narrative** (what each agent is for, the steps of one interviewer turn, the sequence diagrams, the
  findings) lives in `code_flow_narrative.toml`. Every function it names is checked against the code map
  on each build: a name that no longer exists is printed as a warning and flagged on the page, so the
  story can't silently drift from the code. Each finding has a check below and is dropped once fixed.

The example prompt in the "prompt journey" is rendered with the app's real template functions and the
committed fictional sample application (samples/), never with real documents.
"""

from __future__ import annotations

import html
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
MAP_JSON = ROOT / "reports" / "code_map.json"
NARRATIVE = TOOLS / "code_flow_narrative.toml"
TEMPLATE = TOOLS / "code_flow_template.html"
OUT_HTML = ROOT / "reports" / "code-flow-report.html"
SAMPLE_DIR = ROOT / "samples" / "demo_application"
REPO_URL = "https://github.com/JinhoKim46/TC_AE_Sprint1_Interview_helper/blob/main"


def _src(rel: str) -> str:
    path = ROOT / rel
    return path.read_text() if path.exists() else ""


def _ref(rel: str, needle: str) -> dict:
    """A file:line reference to the first line containing `needle`."""
    for i, line in enumerate(_src(rel).split("\n"), start=1):
        if needle in line:
            return {"path": rel, "line": i}
    return {"path": rel, "line": 1}


# --------------------------------------------------------------------------- curated findings


def curated_findings(texts: dict) -> list[dict]:
    """Findings from reading the code. Each check returns refs (still true) or None (fixed, so dropped)."""
    ui = _src("app/ui_common.py")
    apps = _src("app/pages/applications.py")
    judge_py = _src("src/interview_app/evaluation/judge.py")
    view = _src("app/report_view.py")
    base = _src("src/interview_app/prompts/_base.md")
    p5 = _src("src/interview_app/prompts/interviewer_p5_self_critique.md")
    config_py = _src("src/interview_app/config.py")
    engine = _src("src/interview_app/interview/engine.py")
    db = _src("src/interview_app/db.py")
    rubric = json.loads(_src("docs/rubric.json") or "{}").get("judge_settings", {})
    eng_path, cfg_path = "src/interview_app/interview/engine.py", "src/interview_app/config.py"
    code = {p: p.read_text() for d in ("src", "app", "lab") for p in sorted((ROOT / d).rglob("*.py"))}
    metric_uses = sum(t.count("candidate_question_count") for t in code.values())
    focus_reads = sum(len(re.findall(r"focus\w*\.(?:advice|source_session_id)\b", t)) for t in code.values())
    prompting = _src("src/interview_app/interview/prompting.py")

    checks: list[tuple[str, bool, list[dict], dict]] = [
        (
            "jev_not_billed",
            bool(re.search(r"DecisionClient\(cfg, recorder=make_db_recorder\(engine, user_id\)\)", ui)),
            [_ref("app/ui_common.py", "decider = DecisionClient("), _ref(eng_path, "def session_cost")],
            {},
        ),
        (
            "edit_skips_guard",
            "update_document(" in apps and apps.count("check_document") == 1,
            [
                _ref("app/pages/applications.py", "update_document("),
                _ref("app/pages/applications.py", "def _flag_"),
            ],
            {},
        ),
        (
            "mode_not_saved",
            '"mode"' not in _src("app/pages/settings.py")
            and "mode: Mode" in _src("src/interview_app/preferences.py"),
            [
                _ref("src/interview_app/preferences.py", "mode: Mode"),
                _ref("app/pages/settings.py", "save_preferences("),
            ],
            {},
        ),
        (
            "judge_settings_copied",
            "temperature=0" in judge_py and "UNSTABLE_SPREAD = " in view and "unstable_spread" in rubric,
            [
                _ref("src/interview_app/evaluation/judge.py", "temperature=0"),
                _ref("src/interview_app/evaluation/aggregate.py", "NEEDS_EVIDENCE ="),
                _ref("app/report_view.py", "UNSTABLE_SPREAD ="),
            ],
            {"unstable_spread": rubric.get("unstable_spread")},
        ),
        (
            "p5_contradiction",
            "no lists of sub-topics" in base and "numbered multi-part question" in p5,
            [
                _ref("src/interview_app/prompts/_base.md", "no lists of sub-topics"),
                _ref("src/interview_app/prompts/interviewer_p5_self_critique.md", "numbered multi-part"),
            ],
            {},
        ),
        (
            "base_hard_wrap",
            bool(re.search(r"one thing to answer:\n\s+no lists", base)),
            [_ref("src/interview_app/prompts/_base.md", "one thing to answer:")],
            {},
        ),
        (
            "stale_report_view",
            "later, History)" in view and "render_report" in _src("app/pages/history.py"),
            [_ref("app/report_view.py", "later, History")],
            {},
        ),
        (
            "stale_ingest",
            "lives in `security/` (later PR)" in _src("src/interview_app/ingest.py"),
            [_ref("src/interview_app/ingest.py", "(later PR)")],
            {},
        ),
        (
            "status_failed",
            '_set_status(deps.engine, session_id, "failed")' in engine
            and "preparing -> active -> finished / ended_early" in db,
            [_ref("src/interview_app/db.py", "preparing -> active"), _ref(eng_path, '"failed")')],
            {},
        ),
        (
            "counting_duplicated",
            "_NOT_MAIN =" in _src("src/interview_app/lab/judge.py") and "_NOT_MAIN =" in engine,
            [_ref("src/interview_app/lab/judge.py", "_NOT_MAIN ="), _ref(eng_path, "_NOT_MAIN =")],
            {},
        ),
        (
            "unused_metric",
            metric_uses == 2,  # the field and the one assignment in metrics.py, nothing else
            [_ref("src/interview_app/evaluation/metrics.py", "candidate_question_count")],
            {},
        ),
        (
            "drill_unwrapped",
            "focus=ctx.config.focus" in prompting and "{{ r }}" in base and "wrap_untrusted(" not in base,
            [
                _ref("src/interview_app/interview/prompting.py", "focus=ctx.config.focus"),
                _ref("src/interview_app/prompts/_base.md", "{% if focus %}"),
                _ref("src/interview_app/prompts/plan.md", "{% if focus %}"),
            ],
            {},
        ),
        (
            "focus_unread",
            "advice=advice" in _src("src/interview_app/interview/drill.py") and focus_reads == 0,
            [
                _ref("src/interview_app/interview/persona.py", "advice: list[str]"),
                _ref("app/drill_ui.py", "focus.skills"),
            ],
            {},
        ),
        (
            "engine_deps_uncached",
            "def engine_deps" in ui and "@st.cache_resource\ndef engine_deps" not in ui,
            [_ref("app/ui_common.py", "def engine_deps")],
            {},
        ),
    ]
    for needle, target in (
        ("lab/tune_guard.py", "lab/tune_guard.py"),
        ("see auth.py", "src/interview_app/auth.py"),
    ):
        checks.append(
            (
                "missing_file",
                needle in config_py and not (ROOT / target).exists(),
                [_ref(cfg_path, needle)],
                {"name": Path(target).name, "needle": needle, "path": target},
            )
        )

    out = []
    for key, holds, refs, values in checks:
        if holds:
            t = texts[key]
            out.append(
                {
                    "id": key,
                    "severity": t["severity"],
                    "title": t["title"].format(**values),
                    "detail": t["detail"].format(**values),
                    "refs": refs,
                }
            )
    return out


def generated_findings(m: dict, texts: dict) -> list[dict]:
    """Findings computed from the code map itself (always current)."""
    sym = m["symbols"]
    out = []

    def ref(sid: str) -> dict:
        s = sym[sid]
        return {"path": m["modules"][s["module"]]["path"], "line": s["line"], "symbol": sid}

    def add(key: str, refs: list[dict], **values) -> None:
        t = texts[key]
        out.append(
            {
                "id": key,
                "severity": t["severity"],
                "title": t["title"].format(**values),
                "detail": t["detail"].format(**values),
                "refs": refs,
                "generated": True,
            }
        )

    if fields := m["unread_config_fields"]:
        add(
            "unread_config",
            [{"path": "src/interview_app/config.py", "line": f["line"]} for f in fields],
            names=", ".join(f"{f['class']}.{f['field']}" for f in fields),
        )
    if unused := [t for t, info in m["tables"].items() if not info["readers"] and not info["writers"]]:
        add(
            "unused_tables",
            [{"path": m["tables"][t]["path"], "line": m["tables"][t]["line"]} for t in unused],
            names=", ".join(unused),
        )
    for key in ("test_only", "unreferenced"):
        if m[key]:
            add(key, [ref(s) for s in m[key]], names=", ".join(sym[s]["qualname"] for s in m[key]))
    unused_kw = [
        (name, r)
        for name, t in m["templates"].items()
        for r in t["rendered_by"]
        if r["unused_kwargs"] and name.startswith("interviewer_")
    ]
    if unused_kw:
        add(
            "unused_kwargs",
            [ref(unused_kw[0][1]["symbol"])],
            names=", ".join(sorted({k for _, r in unused_kw for k in r["unused_kwargs"]})),
            templates=", ".join(sorted({n for n, _ in unused_kw})),
        )
    for name, t in m["templates"].items():
        for r in t["rendered_by"]:
            if r["missing_vars"]:
                add("missing_vars", [ref(r["symbol"])], template=name, names=", ".join(r["missing_vars"]))
    return out


# --------------------------------------------------------------------------- example prompt

FICTIONAL_PLAN = {
    "role_summary": "Mid-level ML engineer for on-robot perception at a warehouse-robotics company.",
    "requirements": [
        {
            "id": "R1",
            "text": "Ship real-time detection models to edge hardware",
            "priority": "must",
            "category": "technical",
            "coverage": "strong",
            "evidence": "Quantised a detector for phones",
        },
        {
            "id": "R2",
            "text": "Safety-critical evaluation of perception models",
            "priority": "must",
            "category": "domain",
            "coverage": "gap",
            "evidence": "none",
        },
    ],
    "probes": [
        {
            "focus": "How the phone latency number was measured",
            "requirement_ids": ["R1"],
            "stage": "experience",
            "why": "Strong number to verify",
        },
        {
            "focus": "How they would evaluate a model that works next to people",
            "requirement_ids": ["R2"],
            "stage": "gap",
            "why": "No safety evidence in the CV",
        },
    ],
    "cv_numbers_to_verify": ["latency 140 ms to 45 ms"],
    "timeline_flags": [],
    "motivation_claims": ["wants to work on robots that share space with people"],
}
FICTIONAL_ANSWER = (
    "I've spent four years on detection models. At Fieldsight I moved our weed detector onto the phone: "
    "I quantised it to int8 and cut latency from 140 ms to 45 ms. Robots that share space with people are "
    "the next step I want."
)
FICTIONAL_REPLY = {
    "stage": "experience",
    "question_id": "EXP-EVID-01",
    "is_followup": True,
    "message": "You mentioned cutting latency from 140 to 45 milliseconds. "
    "How did you measure that, and on which device?",
    "is_final": False,
}


def _short(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return (
        text[:limit].rsplit(" ", 1)[0]
        + f"\n[… {len(text) - limit:,} more characters, shortened for this report …]"
    )


def example_messages() -> dict:
    """One real interviewer request, rendered by the app's own functions from the fictional sample.

    Imports the project (not Streamlit). Any failure is reported on the page instead of breaking the build,
    so a refactor elsewhere never blocks regenerating the report.
    """
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from interview_app import config as config_mod
        from interview_app.ingest import DocKind
        from interview_app.interview import prompting
        from interview_app.interview.engine import TurnView, compute_progress, next_directive
        from interview_app.interview.persona import SessionConfig, derive_persona
        from interview_app.interview.schemas import InterviewPlan
        from interview_app.security import wrap_answer

        settings = config_mod.Settings(_env_file=None)  # defaults only: never read keys from .env
        files = {
            DocKind.JD: "jd.md",
            DocKind.CV: "cv.md",
            DocKind.COVER_LETTER: "cover_letter.md",
            DocKind.COMPANY_NOTES: "company_notes.md",
        }
        documents = {k: _short((SAMPLE_DIR / f).read_text(), 420) for k, f in files.items()}
        config = SessionConfig()
        persona = derive_persona(config)
        ctx = prompting.PromptContext(
            company="Northwind Robotics",
            role="Machine Learning Engineer, Perception",
            documents=documents,
            config=config,
            persona=persona,
            guideline=_short(prompting.guideline_excerpt(settings.guideline_path), 700),
            plan=InterviewPlan.model_validate(FICTIONAL_PLAN),
        )

        # Capture what the real render() is called with, to show which template produced which part.
        captured: list[tuple[str, dict]] = []
        real_render = prompting.render

        def spy(template: str, **context):
            captured.append((template, context))
            return real_render(template, **context)

        prompting.render = spy
        try:
            system = prompting.interviewer_system_prompt(ctx)
        finally:
            prompting.render = real_render
        variant_template, kwargs = captured[0]
        segments = []
        for part in ("_base.md", "_documents.md", "_contract.md"):
            text = real_render(part, **kwargs)
            start = system.find(text)
            if text and start >= 0:
                segments.append({"template": part, "start": start, "end": start + len(text)})

        opening = {
            "stage": "opening",
            "question_id": "OPEN-01",
            "is_followup": False,
            "message": f"Hi, I'm {persona.name.split()[0]}, {persona.title.lower()} here. "
            "Thanks for making time. Could you walk me through your background "
            "and what draws you to perception at Northwind?",
            "is_final": False,
        }
        turns = [
            TurnView(0, "interviewer", opening["message"], "opening", "OPEN-01", False, False),
            TurnView(1, "candidate", FICTIONAL_ANSWER, None, None, False, False),
        ]
        progress = compute_progress(turns)
        directive = next_directive(progress, config, force_close=False)
        control = prompting.control_message(
            main_asked=progress.main_asked,
            main_target=config.main_questions,
            followups=progress.followups,
            max_followups=config.max_followups,
            candidate_turns=progress.candidate_turns,
            directive=directive,
        )
        schema = prompting.TURN_SCHEMA[config.prompt_variant]
        messages = [
            {"role": "system", "content": system},
            {"role": "assistant", "content": prompting.assistant_turn_content(opening)},
            {"role": "user", "content": wrap_answer(FICTIONAL_ANSWER)},
            control,
        ]
        request = {
            "model": config.llm.model or settings.models.interviewer,
            "messages": f"[the {len(messages)} messages above]",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            },
        }
        if config.llm.reasoning_effort is not None:
            request["extra_body"] = {"reasoning": {"effort": config.llm.reasoning_effort}}
        schema.model_validate(FICTIONAL_REPLY)  # the illustrative reply must match the real schema
        return {
            "variant": config.prompt_variant.value,
            "variant_template": variant_template,
            "persona": persona.model_dump(),
            "messages": messages,
            "segments": segments,
            "request": request,
            "reply": FICTIONAL_REPLY,
            "directive": directive,
        }
    except Exception as e:  # the report must still build if the app's API changed
        return {"error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------- build


def validate(m: dict, narrative: dict) -> list[str]:
    """Every symbol the narrative names must exist in the code map."""
    names = [s["symbol"] for s in narrative["journey"]]
    names += [stage[2] for lane in narrative["lifecycles"] for stage in lane["stages"]]
    names += [sid for seq in narrative["sequences"] for sid in seq["symbols"]]
    return sorted({n for n in names if n not in m["symbols"]})


def build_page(m: dict) -> tuple[str, list[str]]:
    narrative = tomllib.loads(NARRATIVE.read_text())
    missing = validate(m, narrative)
    extra = {
        "repo_url": REPO_URL,
        "agent_notes": narrative["agents"],
        "journey": narrative["journey"],
        "lanes": narrative["lanes"],
        "lifecycles": narrative["lifecycles"],
        # Escaped here because the page puts the source inside <pre class="mermaid">.
        "sequences": [{**s, "mermaid": html.escape(s["mermaid"])} for s in narrative["sequences"]],
        "findings": curated_findings(narrative["findings"])
        + generated_findings(m, narrative["generated_findings"]),
        "example": example_messages(),
        "missing_symbols": missing,
    }
    payload = json.dumps({"map": m, "extra": extra}, ensure_ascii=False, sort_keys=True)
    payload = payload.replace("</", "<\\/")  # never let the data close the <script> tag
    page = TEMPLATE.read_text().replace("/*__DATA__*/{}", payload)
    return page, missing


def main(argv: list[str] | None = None) -> int:
    if not MAP_JSON.exists():
        sys.path.insert(0, str(TOOLS))
        import build_code_map

        build_code_map.write_json(build_code_map.build())
    m = json.loads(MAP_JSON.read_text())
    page, missing = build_page(m)
    OUT_HTML.write_text(page)
    print(f"code-flow-report.html: {len(page) / 1024:.0f} KB")
    for name in missing:
        print(f"  WARNING: the narrative names {name}, which is not in the code map (renamed or removed?)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
