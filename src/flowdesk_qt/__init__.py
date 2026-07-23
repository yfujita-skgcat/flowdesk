"""Qt front-end package.

Qt modules must call core APIs instead of implementing scientific execution.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

from flowdesk_qt.app_info import APP_NAME, ORGANIZATION_NAME, application_version
from flowdesk_qt.app_paths import debug_artifacts_directory
from flowdesk_qt.diagnostics import configure_gui_logging, default_run_id, install_exception_hook
from flowdesk_qt.main_window import MainWindow


def _install_terminal_interrupt_handler(
    app: QCoreApplication,
    window: MainWindow,
) -> Any:
    """Make Ctrl-C close the GUI through the normal Qt cleanup path."""
    previous_handler = signal.getsignal(signal.SIGINT)
    shutting_down = False

    def handle_interrupt(_signum: int, _frame: object) -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        window.close()
        app.quit()

    signal.signal(signal.SIGINT, handle_interrupt)
    return previous_handler


def run_app(
    data_dir: str | Path | None = None,
    debug_artifacts_dir: str | Path | None = None,
    log_level: str = "INFO",
    test_mode: bool = False,
) -> int:
    """Launch the Flowdesk Qt application.

    Args:
      data_dir: Optional directory to pre-load FCS samples from.
      test_mode: Start and close after the event loop becomes active. This is
        intended for packaged-build smoke tests.

    Returns:
      Application exit code.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setApplicationVersion(application_version())

    artifacts_dir = Path(
        debug_artifacts_dir or debug_artifacts_directory() / default_run_id()
    )
    configure_gui_logging(artifacts_dir, log_level)
    install_exception_hook()

    window = MainWindow()
    window.show()
    previous_sigint_handler = _install_terminal_interrupt_handler(app, window)

    if test_mode:
        QTimer.singleShot(0, app.quit)

    try:
        if data_dir is not None:
            count = window.load_samples_from_directory(data_dir)
            if count > 0:
                window.statusBar().showMessage(
                    f"Loaded {count} samples from {data_dir}"
                )
        return app.exec()
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)


def main() -> None:
    """CLI entry point for the GUI."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="flowdesk-gui",
        description="Flowdesk - Flow cytometry analysis GUI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=application_version(),
    )
    parser.add_argument(
        "-d",
        "--data-dir",
        type=str,
        default=None,
        help="Directory containing FCS files to load on startup",
    )
    parser.add_argument("--debug-artifacts-dir", default=None)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--test-mode", action="store_true")

    args = parser.parse_args()
    exit_code = run_app(
        data_dir=args.data_dir,
        debug_artifacts_dir=args.debug_artifacts_dir,
        log_level=args.log_level,
        test_mode=args.test_mode,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
