"""Unified compensation controls, matrix review, and application workspace.

The two editors remain the canonical implementations for their respective
forms.  This dialog composes them into one commit boundary so a user can
calculate a candidate, inspect its visual preview, and save matrices/bindings
atomically without creating a second scientific execution path.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
  QDialog,
  QDialogButtonBox,
  QLabel,
  QTabWidget,
  QVBoxLayout,
  QWidget,
)

from flowdesk_qt.compensation_editor import (
  CompensationCalculationEditorDialog,
  CompensationMatrixEditorDialog,
)


class CompensationWorkspaceDialog(QDialog):
  """Compose calculation and matrix editors under one Save/Cancel boundary."""

  def __init__(
    self,
    matrices: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    calculations: list[dict[str, Any]],
    available_channels: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    population_ids: tuple[str, ...] | list[str],
    sample_ids: tuple[str, ...] | list[str],
    *,
    sample_data: dict[str, dict[str, Any]] | None = None,
    sample_labels: dict[str, str] | None = None,
    population_labels: dict[str, str] | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("compensationWorkspaceDialog")
    self.setWindowTitle("Compensation Workspace")
    self.setMinimumSize(900, 600)
    screen = QGuiApplication.primaryScreen()
    if self.parent() is not None:
      parent_screen = QGuiApplication.screenAt(
        self.parent().mapToGlobal(self.parent().rect().center())
      )
      if parent_screen is not None:
        screen = parent_screen
    available = screen.availableGeometry() if screen is not None else None
    if available is None:
      self.resize(1200, 800)
    else:
      self.resize(
        min(1400, int(available.width() * 0.92)),
        min(900, int(available.height() * 0.88)),
      )

    self._matrix_editor = CompensationMatrixEditorDialog(
      matrices,
      bindings,
      available_channels,
      sample_ids,
      (),
      sample_data=sample_data,
      sample_labels=sample_labels,
      population_ids=population_ids,
      population_labels=population_labels,
      parent=self,
    )
    self._calculation_editor = CompensationCalculationEditorDialog(
      calculations,
      available_channels,
      population_ids,
      sample_ids,
      sample_data=sample_data,
      parent=self,
    )
    self._prepare_embedded_editor(self._matrix_editor)
    self._prepare_embedded_editor(self._calculation_editor)

    outer = QVBoxLayout(self)
    help_label = QLabel(
      "Controls: assign single-stain populations and calculate a matrix. "
      "Matrix Preview: edit matrix metadata and review before/after events. "
      "Application / Bindings: choose where a matrix is applied. "
      "Save and Apply commits matrices and bindings; Cancel discards all edits."
    )
    help_label.setObjectName("compensationWorkspaceHelpLabel")
    help_label.setWordWrap(True)
    outer.addWidget(help_label)

    self._tabs = QTabWidget()
    self._tabs.setObjectName("compensationWorkspaceTabs")
    self._tabs.addTab(self._calculation_editor, "Controls & Calculate")
    self._tabs.addTab(self._matrix_editor, "Matrix Preview")
    self._tabs.addTab(self._matrix_editor.binding_panel(), "Application / Bindings")
    self._tabs.currentChanged.connect(self._sync_control_assignments)
    outer.addWidget(self._tabs, 1)

    buttons = QDialogButtonBox()
    buttons.setObjectName("compensationWorkspaceButtons")
    save_button = buttons.addButton(
      "Save and Apply", QDialogButtonBox.ButtonRole.AcceptRole
    )
    save_button.setObjectName("compensationWorkspaceSaveButton")
    cancel_button = buttons.addButton(
      "Cancel", QDialogButtonBox.ButtonRole.RejectRole
    )
    cancel_button.setObjectName("compensationWorkspaceCancelButton")
    outer.addWidget(buttons)
    buttons.accepted.connect(self._accept_if_valid)
    buttons.rejected.connect(self.reject)
    self._sync_control_assignments()

  def _sync_control_assignments(self) -> None:
    """Propagate explicit control assignments to the preview selector."""
    calculated = self._calculation_editor.calculated_matrix()
    if calculated is not None:
      self._matrix_editor.add_matrix_mapping(calculated)
    self._matrix_editor.set_control_assignments(
      self._calculation_editor.calculations()
    )

  @staticmethod
  def _prepare_embedded_editor(editor: QDialog) -> None:
    """Make an existing editor a child page without a second commit button."""
    editor.setWindowFlags(Qt.WindowType.Widget)
    editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    button_box = editor.findChild(QDialogButtonBox)
    if button_box is not None:
      button_box.hide()

  def matrices(self) -> list[dict[str, Any]]:
    return self._matrix_editor.matrices()

  def bindings(self) -> list[dict[str, Any]]:
    return self._matrix_editor.bindings()

  def calculations(self) -> list[dict[str, Any]]:
    values = self._calculation_editor.calculations()
    return [
      value for value in values
      if str(value.get("id", "")).strip() or value.get("controls")
    ]

  def calculated_matrix(self) -> dict[str, Any] | None:
    value = self._calculation_editor.calculated_matrix()
    return None if value is None else deepcopy(value)

  def _accept_if_valid(self) -> None:
    try:
      self._matrix_editor._commit_current_matrix()
      self._matrix_editor._commit_current_binding()
      self._matrix_editor._validate_all_matrices()
      self._matrix_editor._validate_all_bindings()
      calculation_values = self._calculation_editor.calculations()
      if any(
        str(value.get("id", "")).strip() or value.get("controls")
        for value in calculation_values
      ):
        self._calculation_editor._validate_all()
    except ValueError as exc:
      self._tabs.setCurrentWidget(
        self._calculation_editor if "calculation" in str(exc).lower()
        else self._matrix_editor
      )
      from PySide6.QtWidgets import QMessageBox

      QMessageBox.warning(self, "Invalid compensation", str(exc))
      return
    self.accept()

  def closeEvent(self, event: Any) -> None:
    """Ensure the embedded preview scheduler is stopped before destruction."""
    self._matrix_editor.close()
    super().closeEvent(event)

  def done(self, result: int) -> None:
    """Stop preview work on both Save and Cancel, not only window close."""
    self._matrix_editor.close()
    super().done(result)


__all__ = ["CompensationWorkspaceDialog"]
