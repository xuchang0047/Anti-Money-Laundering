#!/usr/bin/env python3
"""Run the complete local v0.3 subgraph and DoWhy workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline import PipelineConfig, run_pipeline


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--candidate", type=Path, required=True)
    command.add_argument("--manifest", type=Path, required=True)
    command.add_argument("--attack-summary", type=Path)
    command.add_argument("--output-dir", type=Path, required=True)
    command.add_argument("--treatment")
    command.add_argument("--lookback-days", type=int, default=7)
    command.add_argument("--rapid-hours", type=float, default=1.0)
    command.add_argument("--motif-hours", type=float, default=1.0)
    command.add_argument("--fan-threshold", type=int, default=3)
    command.add_argument("--refute-simulations", type=int, default=20)
    command.add_argument("--bootstrap-simulations", type=int, default=50)
    command.add_argument("--seed", type=int, default=42)
    command.add_argument("--max-rows", type=int)
    return command


def main() -> None:
    args = parser().parse_args()
    config = PipelineConfig(
        treatment=args.treatment,
        lookback_days=args.lookback_days,
        rapid_hours=args.rapid_hours,
        motif_hours=args.motif_hours,
        fan_threshold=args.fan_threshold,
        refute_simulations=args.refute_simulations,
        bootstrap_simulations=args.bootstrap_simulations,
        seed=args.seed,
        max_rows=args.max_rows,
    )
    result = run_pipeline(
        args.candidate,
        args.manifest,
        args.output_dir,
        config,
        args.attack_summary,
    )
    print(json.dumps(result["report"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
