"""Flowdesk CLI entry point."""

from __future__ import annotations

import argparse

from flowdesk_cli.inspect_fcs import inspect_fcs_command
from flowdesk_cli.run_project import run_project_command


def main() -> int:
  """Run the Flowdesk CLI."""

  parser = argparse.ArgumentParser(prog="flowdesk")
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
    help="Path for the TSV export file.",
  )
  run_parser.add_argument(
    "--execution-profile",
    default="default",
    help="Execution profile id to use (default: default).",
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

  args = parser.parse_args()

  if args.command == "run":
    return run_project_command(
      args.project, args.output, args.execution_profile
    )
  if args.command == "inspect":
    return inspect_fcs_command(args.fcs_file)

  parser.print_help()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
