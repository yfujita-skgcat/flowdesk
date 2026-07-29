#!/usr/bin/env python3
"""Run the opt-in deterministic canonical pipeline baseline benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flowdesk_core.execution_control import ExecutionOptions
from flowdesk_core.pipeline_benchmark import (
  PIPELINE_BENCHMARK_PROFILES,
  run_pipeline_benchmark,
)


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--profile", choices=sorted(PIPELINE_BENCHMARK_PROFILES), default="small")
  parser.add_argument("--repeats", type=int, default=1)
  parser.add_argument("--seed", type=int, default=1729)
  parser.add_argument(
    "--output", type=Path, default=Path("artifacts/pipeline-benchmark.json"),
  )
  args = parser.parse_args()
  result = run_pipeline_benchmark(
    PIPELINE_BENCHMARK_PROFILES[args.profile],
    repeats=args.repeats,
    seed=args.seed,
    options=ExecutionOptions(),
  )
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
  print(json.dumps(result, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
