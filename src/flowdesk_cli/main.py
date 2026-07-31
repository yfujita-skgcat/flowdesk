"""Flowdesk CLI entry point."""

from __future__ import annotations

import argparse

from flowdesk_cli.batch_gate import batch_gate_command
from flowdesk_cli.batch_plot import batch_plot_command
from flowdesk_cli.inspect_fcs import inspect_fcs_command
from flowdesk_cli.run_project import run_project_command
from flowdesk_core.credits import credits_text
from flowdesk_core.density_colors import DensityColorConfig
from flowdesk_core.execution_control import ExecutionOptions


def _positive_integer(value: str) -> int:
  """Parse a positive integer for an explicit runtime resource limit."""
  try:
    parsed = int(value)
  except ValueError as exc:
    raise argparse.ArgumentTypeError("must be an integer") from exc
  if parsed < 1:
    raise argparse.ArgumentTypeError("must be positive")
  return parsed


def main() -> int:
  """Run the Flowdesk CLI."""

  parser = argparse.ArgumentParser(
    prog="flowdesk",
    epilog=credits_text(),
    formatter_class=argparse.RawDescriptionHelpFormatter,
  )
  parser.add_argument(
    "--credits",
    action="store_true",
    help="Show copyright and license information and exit.",
  )
  subparsers = parser.add_subparsers(dest="command")

  # ------------------------------------------------------------------
  # run sub-command
  # ------------------------------------------------------------------
  run_parser = subparsers.add_parser(
    "run",
    help="Run a saved Flowdesk project headlessly.",
  )
  run_parser.add_argument("project", help="Path to the .flowdesk project bundle.")
  run_parser.add_argument(
    "--output",
    default=None,
    help="Path for the unified Results export file.",
  )
  run_parser.add_argument(
    "--layout",
    choices=("wide", "long"),
    default="wide",
    help="Unified Results layout (default: wide).",
  )
  run_parser.add_argument(
    "--include-internal-ids",
    action="store_true",
    help="Include stable sample/population IDs and hierarchy metadata.",
  )
  run_parser.add_argument(
    "--include-qc",
    action="store_true",
    help="Include status and statistic quality-control metadata.",
  )
  run_parser.add_argument(
    "--statistics-output",
    default=None,
    help=argparse.SUPPRESS,
  )
  run_parser.add_argument(
    "--execution-profile",
    default="default",
    help="Execution profile id to use (default: default).",
  )
  run_parser.add_argument(
    "--execution-backend",
    choices=("sequential", "thread"),
    default="sequential",
    help="Runtime executor backend (default: sequential).",
  )
  run_parser.add_argument(
    "--max-workers",
    type=_positive_integer,
    default=1,
    help="Maximum concurrent samples for --execution-backend thread (default: 1).",
  )
  run_parser.add_argument(
    "--memory-budget-mib",
    type=_positive_integer,
    default=None,
    help="Maximum estimated in-flight sample memory in MiB.",
  )

  # ------------------------------------------------------------------
  # inspect sub-command
  # ------------------------------------------------------------------
  inspect_parser = subparsers.add_parser(
    "inspect",
    help="Inspect FCS file metadata.",
  )
  inspect_parser.add_argument(
    "fcs_file",
    help="Path to the FCS file.",
  )

  # ------------------------------------------------------------------
  # batch-gate sub-command
  # ------------------------------------------------------------------
  batch_parser = subparsers.add_parser(
    "batch-gate",
    help="Apply gates to multiple FCS files and export results.",
  )
  batch_parser.add_argument(
    "project",
    help="Path to the .flowdesk project bundle.",
  )
  batch_parser.add_argument(
    "fcs_files",
    nargs="+",
    help="FCS file paths to process.",
  )
  batch_parser.add_argument(
    "--output",
    default=None,
    help="Path for the TSV export file.",
  )
  batch_parser.add_argument(
    "--execution-profile",
    default="default",
    help="Execution profile id to use (default: default).",
  )

  plot_parser = subparsers.add_parser(
    "batch-plot", help="Export plots for every sample from a saved definition."
  )
  plot_parser.add_argument("project", help="Path to the .flowdesk project bundle.")
  plot_parser.add_argument("--export-id", required=True, help="Batch plot export definition ID.")
  plot_parser.add_argument("--output-dir", required=True, help="Output directory.")
  plot_parser.add_argument(
    "--execution-backend",
    choices=("sequential", "thread"),
    default="sequential",
    help="Runtime renderer backend (default: sequential).",
  )
  plot_parser.add_argument(
    "--max-workers",
    type=_positive_integer,
    default=1,
    help="Maximum concurrent batch items for --execution-backend thread.",
  )
  plot_parser.add_argument(
    "--memory-budget-mib",
    type=_positive_integer,
    default=None,
    help="Maximum estimated in-flight batch render memory in MiB.",
  )
  plot_parser.add_argument(
    "--density-workers",
    type=_positive_integer,
    default=1,
    help="Workers for density histogram chunks (default: 1).",
  )
  plot_parser.add_argument(
    "--density-memory-budget-mib",
    type=_positive_integer,
    default=None,
    help="Memory budget for concurrent density histogram chunks in MiB.",
  )

  args = parser.parse_args()

  if args.credits:
    print(credits_text())
    return 0

  if args.command == "run":
    return run_project_command(
      args.project,
      output=args.output,
      statistics_output=args.statistics_output,
      execution_profile_id=args.execution_profile,
      layout=args.layout,
      include_internal_ids=args.include_internal_ids,
      include_qc=args.include_qc,
      execution_options=ExecutionOptions(
        backend=args.execution_backend,
        max_workers=args.max_workers,
        memory_budget_bytes=(
          None if args.memory_budget_mib is None
          else args.memory_budget_mib * 1024 * 1024
        ),
      ),
    )
  if args.command == "inspect":
    return inspect_fcs_command(args.fcs_file)
  if args.command == "batch-gate":
    return batch_gate_command(
      args.project, args.fcs_files, args.output, args.execution_profile
    )
  if args.command == "batch-plot":
    return batch_plot_command(
      args.project,
      args.export_id,
      args.output_dir,
      execution_options=ExecutionOptions(
        backend=args.execution_backend,
        max_workers=args.max_workers,
        memory_budget_bytes=(
          None if args.memory_budget_mib is None
          else args.memory_budget_mib * 1024 * 1024
        ),
      ),
      density_config=DensityColorConfig(
        histogram_workers=args.density_workers,
        histogram_memory_budget_bytes=(
          None if args.density_memory_budget_mib is None
          else args.density_memory_budget_mib * 1024 * 1024
        ),
      ),
    )

  parser.print_help()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
