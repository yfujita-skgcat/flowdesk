#!/usr/bin/env python3
"""Run the lightweight vector scatter baseline benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flowdesk_core.vector_scatter_benchmark import (
  BENCHMARK_COUNTS,
  run_scatter_benchmark,
)


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--counts", nargs="+", type=int, default=list(BENCHMARK_COUNTS),
    help="point counts (default: 1k, 5k, 20k, 100k, 1M)",
  )
  parser.add_argument("--profile", choices=("sparse", "dense", "overlap", "mixed"), default="mixed")
  parser.add_argument("--hybrid-dpi", type=int, default=96)
  parser.add_argument("--output", type=Path, default=Path("artifacts/vector-scatter-benchmark.json"))
  args = parser.parse_args()
  result = run_scatter_benchmark(
    args.counts, profile=args.profile, hybrid_scatter_dpi=args.hybrid_dpi
  )
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
  print(json.dumps(result, indent=2, ensure_ascii=False))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
