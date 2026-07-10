#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
PYTHON_BIN=${FLOWDESK_PYTHON:-"$ROOT/.direnv/python-3.12.13/bin/python"}
RUN_ID=${FLOWDESK_GUI_RUN_ID:-debug-$(date -u +%Y%m%dT%H%M%SZ)-$$}
ARTIFACT_DIR=${FLOWDESK_GUI_ARTIFACT_DIR:-"$ROOT/artifacts/gui/$RUN_ID"}
mkdir -p "$ARTIFACT_DIR"
export PYTHONFAULTHANDLER=1
exec "$PYTHON_BIN" -X faulthandler -m flowdesk_qt \
  --debug-artifacts-dir "$ARTIFACT_DIR" "$@"
