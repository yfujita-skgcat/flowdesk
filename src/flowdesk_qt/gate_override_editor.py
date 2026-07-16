"""Qt dialog for intentionally creating an auditable sample gate override."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from PySide6.QtWidgets import (
  QComboBox,
  QDialog,
  QDialogButtonBox,
  QFormLayout,
  QLabel,
  QLineEdit,
  QMessageBox,
  QPlainTextEdit,
  QVBoxLayout,
)

from flowdesk_core.models import GateSpec


class GateOverrideDialog(QDialog):
  """Collect geometry and audit metadata for one explicit sample override."""

  def __init__(
    self,
    gate: GateSpec,
    sample_id: str,
    affected_sample_ids: Sequence[str],
    *,
    author: str = "analyst",
    parent=None,
  ) -> None:
    super().__init__(parent)
    self.setWindowTitle("Create Sample Gate Override")
    self.setObjectName("gateOverrideDialog")
    self._gate = gate
    self._sample_id = sample_id
    self._affected_sample_ids = tuple(affected_sample_ids)
    self._build_ui(author)

  def _build_ui(self, author: str) -> None:
    layout = QVBoxLayout(self)
    impact = QLabel(
      "This explicit override applies only to the selected sample and does not "
      "clone the group strategy. Affected samples: "
      f"{', '.join(self._affected_sample_ids) or self._sample_id}"
    )
    impact.setObjectName("gateOverrideImpactLabel")
    impact.setWordWrap(True)
    layout.addWidget(impact)

    form = QFormLayout()
    self._mode = QComboBox()
    self._mode.addItem("Full geometry", "full")
    self._mode.addItem("Typed delta", "delta")
    self._coordinates = QPlainTextEdit(json.dumps(self._gate.coordinates, default=list))
    self._coordinates.setObjectName("gateOverrideCoordinatesEdit")
    self._coordinates.setPlaceholderText("[[x1, y1], [x2, y2]]")
    self._thresholds = QPlainTextEdit(json.dumps(self._gate.thresholds, indent=2))
    self._thresholds.setObjectName("gateOverrideThresholdsEdit")
    self._reason = QLineEdit()
    self._reason.setObjectName("gateOverrideReasonEdit")
    self._author = QLineEdit(author)
    self._author.setObjectName("gateOverrideAuthorEdit")
    self._purpose = QComboBox()
    self._purpose.addItem("Technical cleanup", "technical_cleanup")
    self._purpose.addItem("Comparison-critical", "comparison_critical")
    form.addRow("Geometry mode:", self._mode)
    form.addRow("Coordinates JSON:", self._coordinates)
    form.addRow("Thresholds JSON:", self._thresholds)
    form.addRow("Author:", self._author)
    form.addRow("Reason (required):", self._reason)
    form.addRow("Gate purpose:", self._purpose)
    layout.addLayout(form)

    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(self._validate_and_accept)
    buttons.rejected.connect(self.reject)
    layout.addWidget(buttons)

  def specification(self) -> dict[str, Any]:
    """Return validated dialog values excluding IDs and timestamps."""
    coordinates = json.loads(self._coordinates.toPlainText() or "[]")
    thresholds = json.loads(self._thresholds.toPlainText() or "{}")
    return {
      "sample_id": self._sample_id,
      "base_gate_id": self._gate.id,
      "geometry_mode": self._mode.currentData(),
      "coordinates": coordinates,
      "thresholds": thresholds,
      "author": self._author.text().strip(),
      "reason": self._reason.text().strip(),
      "gate_purpose": self._purpose.currentData(),
    }

  def _validate_and_accept(self) -> None:
    try:
      values = self.specification()
      if not values["author"] or not values["reason"]:
        raise ValueError("Author and reason are required.")
      if not isinstance(values["coordinates"], list) or not isinstance(
        values["thresholds"], dict
      ):
        raise ValueError("Geometry JSON must contain an array and thresholds must be an object.")
      if (
        values["geometry_mode"] == "delta"
        and not values["coordinates"]
        and not values["thresholds"]
      ):
        raise ValueError("A typed delta must contain at least one geometry change.")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
      QMessageBox.warning(self, "Invalid Override", str(exc))
      return
    self.accept()
