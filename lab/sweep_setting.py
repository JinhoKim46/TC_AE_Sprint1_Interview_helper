"""Tune one model setting and compare the output (course task E8).

The interviewer is a gpt-5 reasoning model, which ignores `temperature`; the setting that changes
its behaviour is `reasoning_effort` (how much it thinks before answering). This runs one prompt
variant with each effort value on the STRONG and WEAK personas and prints the same quality, latency
and cost table as compare_prompts.py.

    uv run python lab/sweep_setting.py --variant p4 --efforts low,medium
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from interview_app.config import get_settings
from interview_app.interview.persona import LLMSettings, SessionConfig
from interview_app.lab.candidate import CandidatePersona
from interview_app.lab.compare import Arm, Lab, make_lab, markdown_table, run_arms, summarize, write_csv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_prompts import RESULTS_DIR, parse_variants  # noqa: E402  (sibling script, not a package)


def main(argv: list[str] | None = None, lab: Lab | None = None, results_dir: Path = RESULTS_DIR) -> int:
    settings = get_settings()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--variant", default="p4")
    p.add_argument("--efforts", default="low,medium")
    p.add_argument("--personas", default="strong,weak")
    p.add_argument("--sessions-per-persona", type=int, default=1)
    p.add_argument("--main-questions", type=int, default=4)
    p.add_argument("--budget-usd", type=float, default=0.5)
    p.add_argument("--max-candidate-turns", type=int, default=16)
    p.add_argument("--db", type=Path, default=settings.data_dir / "lab.db")
    args = p.parse_args(argv)

    (variant,) = parse_variants(args.variant)
    arms = [
        Arm(
            f"{variant.value} effort={effort}",
            SessionConfig(
                prompt_variant=variant,
                main_questions=args.main_questions,
                llm=LLMSettings(reasoning_effort=effort),
            ),
        )
        for effort in args.efforts.split(",")
    ]
    personas = [CandidatePersona(x.strip()) for x in args.personas.split(",")]
    lab = lab or make_lab(settings, args.db)

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
    out = results_dir / f"sweep-{datetime.now():%Y%m%d-%H%M%S}.csv"
    write_csv(results, out)
    print(f"\nWrote {len(results)} sessions to {out}\n")
    print(markdown_table(summarize(results)))
    print("\nBy persona:\n")
    print(markdown_table(summarize(results, key=lambda r: f"{r.arm} / {r.persona}")))
    return 2 if aborted else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
