"""Multi-shot run configuration dialog."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class RunDialog(QDialog):
    """Modal dialog that collects N (frames to record) for a multi-shot run."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Multi-shot run")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._n_spin = QSpinBox()
        self._n_spin.setRange(1, 99999)
        self._n_spin.setValue(10)
        form.addRow("Frames (N):", self._n_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def n_shots(self) -> int:
        return self._n_spin.value()
