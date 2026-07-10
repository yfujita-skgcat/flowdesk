#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
PYTHON_BIN=${FLOWDESK_PYTHON:-"$ROOT/.direnv/python-3.12.13/bin/python"}
RUN_ID=${FLOWDESK_GUI_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}
ARTIFACT_DIR=${FLOWDESK_GUI_ARTIFACT_DIR:-"$ROOT/artifacts/gui/$RUN_ID"}
mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/tests"

export PYTHONFAULTHANDLER=1
export FLOWDESK_GUI_STRICT_CALLBACKS=1
export FLOWDESK_GUI_ARTIFACT_DIR="$ARTIFACT_DIR"

"$PYTHON_BIN" -c 'import json, platform, sys; import PySide6, pyqtgraph, pytest; from PySide6.QtCore import qVersion; print(json.dumps({"executable": sys.executable, "python": platform.python_version(), "PySide6": PySide6.__version__, "Qt": qVersion(), "pyqtgraph": pyqtgraph.__version__, "pytest": pytest.__version__}, indent=2))' > "$ARTIFACT_DIR/environment.json"

COMMAND=("$PYTHON_BIN" -X faulthandler -m pytest -m gui "$@")
if [[ ${FLOWDESK_GUI_BACKEND:-offscreen} == xvfb ]]; then
  export QT_QPA_PLATFORM=xcb
  COMMAND=(xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" "${COMMAND[@]}")
else
  export QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen}
fi

printf 'Command:' | tee "$ARTIFACT_DIR/pytest.log"
printf ' %q' "${COMMAND[@]}" | tee -a "$ARTIFACT_DIR/pytest.log"
printf '\n' | tee -a "$ARTIFACT_DIR/pytest.log"
set +e
"${COMMAND[@]}" 2>&1 | tee -a "$ARTIFACT_DIR/pytest.log"
status=${PIPESTATUS[0]}
set -e
exit "$status"
