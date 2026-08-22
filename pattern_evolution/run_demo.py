#!/usr/bin/env python3
"""Run one full proxy-based self-evolution round."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pattern_evolution.src.evolution_loop import run_evolution


PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "artifacts")
    parser.add_argument(
        "--api-config",
        type=Path,
        default=Path("/home/bingqinshao/MOOSE-Chem/main.sh"),
        help="MOOSE-Chem shell config containing api_key, base_url and model_name_gene",
    )
    parser.add_argument("--no-api", action="store_true", help="Skip only the non-executable hypothesis view")
    parser.add_argument("--require-api", action="store_true", help="Fail the run if the hypothesis API call fails")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_evolution(
        args.output_dir,
        api_config=None if args.no_api else args.api_config,
        require_api=args.require_api,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
