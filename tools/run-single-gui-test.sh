#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <pytest-node-id> [pytest-args...]" >&2
  exit 2
fi
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FLOWDESK_GUI_RUN_ID=${FLOWDESK_GUI_RUN_ID:-single-$(date -u +%Y%m%dT%H%M%SZ)-$$} \
  "$ROOT/tools/run-gui-tests.sh" "$@"
