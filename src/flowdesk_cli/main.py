"""Flowdesk CLI entry point."""

from __future__ import annotations

import argparse

from flowdesk_cli.run_project import run_project_command


def main() -> int:
  """Run the Flowdesk CLI."""

  parser = argparse.ArgumentParser(prog="flowdesk")
  subparsers = parser.add_subparsers(dest="command")
  run_parser = subparsers.add_parser("run")
  run_parser.add_argument("project")
  run_parser.add_argument("--output")
  run_parser.add_argument("--execution-profile", default="default")

  args = parser.parse_args()
  if args.command == "run":
    return run_project_command(args.project, args.output, args.execution_profile)
  parser.print_help()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
