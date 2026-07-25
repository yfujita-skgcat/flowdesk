# Third-party notices

Flowdesk's own source code is distributed under the BSD 3-Clause License in
[`LICENSE`](LICENSE). This file does not change that license and does not
relicense any dependency.

## Qt and PySide6

The optional GUI uses PySide6, Shiboken6, and Qt 6. The community editions are
available under the GNU LGPL version 3 and GNU GPL version 3, and commercial
Qt licenses are also available. The applicable license depends on the exact
Qt modules and distribution used to build the application.

- [Qt licensing](https://doc.qt.io/qt-6/licensing.html)
- [Qt for Python licensing](https://doc.qt.io/qtforpython-6/)
- [Qt for Python third-party licenses](https://doc.qt.io/qtforpython-6.10/licenses.html)
- [GNU LGPL version 3](https://www.gnu.org/licenses/lgpl-3.0.html)
- [GNU GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html)

Flowdesk does not change Qt or PySide6. A native package that bundles Qt must
be distributed with the applicable Qt/PySide6 license texts, attribution
notices, and any corresponding-source or relinking information required by
the selected Qt license. The exact package manifest and Qt modules must be
checked for every release build.

## Other runtime dependencies

The source distribution declares these dependencies in `pyproject.toml`.
Their own licenses remain applicable when they are installed or bundled:

- NumPy: BSD-style license and notices for bundled components
- FlowIO: BSD 3-Clause License
- Pillow: HPND license
- pyqtgraph: MIT License and notices for included data
- PyInstaller: GPL with its bootloader exception when used for native builds

The dependency versions and their license files should be recorded in the
release build manifest. This summary is not a substitute for the license
files shipped by each dependency.
