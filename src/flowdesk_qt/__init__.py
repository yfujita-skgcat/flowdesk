"""Qt front-end package.

Qt modules must call core APIs instead of implementing scientific execution.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from flowdesk_qt.main_window import MainWindow


def run_app(data_dir: str | Path | None = None) -> int:
    """Launch the Flowdesk Qt application.

    Args:
      data_dir: Optional directory to pre-load FCS samples from.

    Returns:
      Application exit code.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("Flowdesk")
    app.setOrganizationName("Flowdesk")

    window = MainWindow()
    window.show()

    if data_dir is not None:
        count = window.load_samples_from_directory(data_dir)
        if count > 0:
            window.statusBar().showMessage(f"Loaded {count} samples from {data_dir}")

    return app.exec()


def main() -> None:
    """CLI entry point for the GUI."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="flowdesk-gui",
        description="Flowdesk - Flow cytometry analysis GUI",
    )
    parser.add_argument(
        "-d",
        "--data-dir",
        type=str,
        default=None,
        help="Directory containing FCS files to load on startup",
    )

    args = parser.parse_args()
    exit_code = run_app(data_dir=args.data_dir)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
