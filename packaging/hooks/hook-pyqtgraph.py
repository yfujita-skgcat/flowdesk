"""Flowdesk's 2-D-only pyqtgraph PyInstaller hook."""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


datas = collect_data_files("pyqtgraph", excludes=["**/examples/*"])


def _is_runtime_module(name: str) -> bool:
  return (
    name != "pyqtgraph.examples"
    and not name.startswith("pyqtgraph.opengl")
    and not name.startswith("pyqtgraph.jupyter")
  )


# pyqtgraph uses Qt-version-specific templates.  Keep those hidden imports,
# but do not import/inspect optional OpenGL or Jupyter packages while
# discovering them.
all_imports = collect_submodules("pyqtgraph", filter=_is_runtime_module)
hiddenimports = [name for name in all_imports if "Template" in name]
hiddenimports.append("pyqtgraph.multiprocess.bootstrap")

try:
  from PyInstaller.utils.hooks.qt import exclude_extraneous_qt_bindings
except ImportError:
  pass
else:
  excludedimports = exclude_extraneous_qt_bindings(
    hook_name="hook-pyqtgraph",
    qt_bindings_order=None,
  )
