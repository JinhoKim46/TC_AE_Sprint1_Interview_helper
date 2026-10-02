"""Compare the five interviewer system prompts (course requirement R4, judged with Jev for H5).

Every prompt variant interviews every simulated candidate persona on the fictional sample
application; each transcript is judged against rubric §12 and measured in code. Writes one CSV row
per session to lab/results/<timestamp>.csv and prints a markdown summary per variant.

    uv run python lab/compare_prompts.py                       # 5 variants x 3 personas x 1
    uv run python lab/compare_prompts.py --variants p1,p4 --personas weak --sessions-per-persona 2

Real API calls: costs money. --budget-usd stops the run cleanly once the logged spend passes it.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from interview_app.config import Settings, get_settings
from interview_app.interview.persona import PromptVariant, SessionConfig
from interview_app.lab.candidate import CandidatePersona
from interview_app.lab.compare import Arm, Lab, make_lab, markdown_table, run_arms, summarize, write_csv

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def parse_variants(text: str) -> list[PromptVariant]:
    if text == "all":
        return list(PromptVariant)
    # Accept the short form "p1" as well as the full value "p1_zero_shot".
    by_prefix = {v.value.split("_")[0]: v for v in PromptVariant}
    return [by_prefix.get(t.strip()) or PromptVariant(t.strip()) for t in text.split(",")]


def build_parser(settings: Settings) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sessions-per-persona", type=int, default=1)
    p.add_argument("--personas", default="strong,weak,evasive")
    p.add_argument("--variants", default="all", help="all, or a list like p1,p4")
    p.add_argument("--main-questions", type=int, default=4)
    p.add_argument("--budget-usd", type=float, default=2.0)
    p.add_argument("--max-candidate-turns", type=int, default=16)
    p.add_argument("--db", type=Path, default=settings.data_dir / "lab.db")
    return p


def main(argv: list[str] | None = None, lab: Lab | None = None, results_dir: Path = RESULTS_DIR) -> int:
    settings = get_settings()
    args = build_parser(settings).parse_args(argv)
    personas = [CandidatePersona(p.strip()) for p in args.personas.split(",")]
    arms = [
        Arm(v.value, SessionConfig(prompt_variant=v, main_questions=args.main_questions))
        for v in parse_variants(args.variants)
    ]
    lab = lab or make_lab(settings, args.db)

    print(f"{len(arms)} variants x {len(personas)} personas x {args.sessions_per_persona} sessions")
    results, aborted = run_arms(
        lab.deps,
        lab.decider,
        lab.user_id,
        lab.app_id,
        arms,
        personas,
        args.sessions_per_persona,
        args.budget_usd,
        args.max_candidate_turns,
    )
    out = results_dir / f"{datetime.now():%Y%m%d-%H%M%S}.csv"
    write_csv(results, out)
    print(f"\nWrote {len(results)} sessions to {out}\n")
    print(markdown_table(summarize(results)))
    print("\nBy persona:\n")
    print(markdown_table(summarize(results, key=lambda r: f"{r.arm} / {r.persona}")))
    return 2 if aborted else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
