"""Qt-only runtime controls for authoritative pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
  QComboBox,
  QDialog,
  QDialogButtonBox,
  QFormLayout,
  QLabel,
  QSpinBox,
  QVBoxLayout,
  QWidget,
)


# The headless runner keeps the explicit thread backend for benchmark and CLI
# diagnostics.  GUI/package lifecycle validation is not complete yet, so the
# GUI must remain on the deterministic sequential backend.
PIPELINE_EXPERIMENTAL_WORKERS_GUI_AVAILABLE = False


@dataclass(frozen=True)
class PipelineExecutionRequest:
  """Runtime-only pipeline options; never serialized into a project."""

  execution_backend: str = "sequential"
  max_workers: int = 1
  memory_budget_mib: int | None = None


class PipelineExecutionDialog(QDialog):
  """Choose bounded sample-level execution settings for the next run."""

  def __init__(
    self,
    request: PipelineExecutionRequest | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("pipelineExecutionDialog")
    self.setWindowTitle("Pipeline Execution Settings")
    self.resize(430, 180)
    current = request or PipelineExecutionRequest()

    self._execution_backend = QComboBox()
    self._execution_backend.setObjectName("pipelineExecutionBackendCombo")
    self._execution_backend.addItem("Sequential (recommended)", "sequential")
    self._execution_backend.addItem("Bounded threads (opt-in)", "thread")
    index = self._execution_backend.findData(current.execution_backend)
    self._execution_backend.setCurrentIndex(max(0, index))

    self._max_workers = QSpinBox()
    self._max_workers.setObjectName("pipelineMaxWorkersSpinBox")
    self._max_workers.setRange(1, 64)
    self._max_workers.setValue(current.max_workers)

    self._memory_budget_mib = QSpinBox()
    self._memory_budget_mib.setObjectName("pipelineMemoryBudgetMiBSpinBox")
    self._memory_budget_mib.setRange(0, 1_048_576)
    self._memory_budget_mib.setValue(current.memory_budget_mib or 0)

    self._experimental_workers_status = QLabel(
      "Experimental worker controls are disabled in the GUI until "
      "Windows/PyInstaller lifecycle validation is complete."
    )
    self._experimental_workers_status.setObjectName(
      "pipelineExperimentalWorkersStatusLabel"
    )
    self._experimental_workers_status.setWordWrap(True)
    self._execution_backend.setEnabled(PIPELINE_EXPERIMENTAL_WORKERS_GUI_AVAILABLE)
    self._max_workers.setEnabled(PIPELINE_EXPERIMENTAL_WORKERS_GUI_AVAILABLE)
    self._memory_budget_mib.setEnabled(PIPELINE_EXPERIMENTAL_WORKERS_GUI_AVAILABLE)

    form = QFormLayout()
    form.addRow("Execution backend", self._execution_backend)
    form.addRow("Max workers", self._max_workers)
    form.addRow("Memory budget (MiB, 0 = automatic)", self._memory_budget_mib)
    form.addRow("", self._experimental_workers_status)

    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("pipelineExecutionDialogButtons")
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)
    layout = QVBoxLayout(self)
    layout.addLayout(form)
    layout.addWidget(buttons)

  def request(self) -> PipelineExecutionRequest:
    """Return selected runtime controls without project data."""
    return PipelineExecutionRequest(
      execution_backend=str(self._execution_backend.currentData() or "sequential"),
      max_workers=self._max_workers.value(),
      memory_budget_mib=self._memory_budget_mib.value() or None,
    )
