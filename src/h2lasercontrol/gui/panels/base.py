"""Base class for one device tab: header (status, Stop, Connect) + error line + device body."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import DeviceConfig
from ...services import DeviceService
from ..style import GREEN, GREY, set_role

ACTION_TEXT = {"connect": "Connecting", "disconnect": "Disconnecting"}


class DevicePanel(QWidget):
    tab_state_changed = Signal(str)  # "ok" | "busy" | "off" | "error"

    def __init__(self, service: DeviceService, cfg: DeviceConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.cfg = cfg
        self.connected = False
        self.busy = False
        self.state: dict[str, Any] = {}
        self.has_error = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # header
        header = QHBoxLayout()
        self.status_label = QLabel()
        self.busy_label = QLabel()
        set_role(self.busy_label, "muted")
        self.stop_btn = QPushButton("STOP")
        set_role(self.stop_btn, "stop")
        self.stop_btn.setToolTip("Stop the running operation")
        # NOT connected to service.request_stop directly: the service lives in the device thread,
        # so Qt would queue the call behind the running action (= stop arrives after the move).
        self.stop_btn.clicked.connect(self._stop)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._toggle_connection)
        header.addWidget(self.status_label)
        header.addStretch(1)
        header.addWidget(self.busy_label)
        header.addWidget(self.stop_btn)
        header.addWidget(self.connect_btn)
        root.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #dddddd;")
        root.addWidget(line)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        set_role(self.error_label, "error")
        self.error_label.hide()
        root.addWidget(self.error_label)

        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        root.addLayout(self.body)
        root.addStretch(1)
        self.build_body()

        service.connection_changed.connect(self._on_connection)
        service.busy_changed.connect(self._on_busy)
        service.state_changed.connect(self._on_state)
        service.action_failed.connect(self._on_failed)
        service.action_done.connect(self._on_done)
        service.progress.connect(self.on_progress)
        self._on_connection(False, "not connected")

    # --- for subclasses -----------------------------------------------------------------------
    def build_body(self) -> None:
        """Create the device-specific widgets inside self.body."""

    def run(self, action: str, **kwargs: Any) -> None:
        """Start an action on the device (ignored while another one runs)."""
        if self.busy or not self.connected:
            return
        self.show_error("")
        self.service.submit(action, **kwargs)

    def confirm(self, title: str, text: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Yes

    def update_view(self) -> None:
        """Refresh the body from self.state / self.connected / self.busy."""

    def on_progress(self, info: dict) -> None:
        """Live progress during a long action."""

    def on_action_done(self, action: str, result: Any) -> None:
        """Called after an action finished successfully."""

    def busy_text(self, action: str) -> str:
        return ACTION_TEXT.get(action, action.replace("_", " ").capitalize()) + " …"

    @property
    def can_act(self) -> bool:
        return self.connected and not self.busy

    # --- internals ----------------------------------------------------------------------------
    def show_error(self, message: str) -> None:
        self.has_error = bool(message)
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        self._emit_tab_state()

    def _stop(self) -> None:
        self.service.request_stop()  # runs here in the GUI thread; sets a thread-safe flag
        self.busy_label.setText("Stopping …")

    def _toggle_connection(self) -> None:
        self.show_error("")
        self.service.submit("disconnect" if self.connected else "connect")

    def _on_connection(self, connected: bool, message: str) -> None:
        self.connected = connected
        if connected:
            self.status_label.setText(f"<b style='color:{GREEN}'>●</b> Connected "
                                      f"<span style='color:{GREY}'>({message})</span>")
            self.connect_btn.setText("Disconnect")
        else:
            self.status_label.setText(f"<b style='color:{GREY}'>●</b> Not connected")
            self.connect_btn.setText("Connect")
            self.state = {}
            if message not in ("disconnected", "not connected"):
                self.show_error(f"Not connected: {message}")
        self._refresh()

    def _on_busy(self, busy: bool, action: str) -> None:
        self.busy = busy
        self.busy_label.setText(self.busy_text(action) if busy else "")
        self._refresh()

    def _on_state(self, state: dict) -> None:
        self.state = state
        self._refresh()

    def _on_failed(self, action: str, message: str) -> None:
        what = self.busy_text(action).split(" (")[0].rstrip(" …")
        if "stopped on request" in message:
            self.show_error(f"{what} stopped (STOP pressed).")
        else:
            self.show_error(f"{what} failed: {message}")

    def _on_done(self, action: str, result: Any) -> None:
        self.on_action_done(action, result)

    def _refresh(self) -> None:
        self.stop_btn.setEnabled(self.busy and self.connected)
        self.connect_btn.setEnabled(not self.busy)
        self.update_view()
        self._emit_tab_state()

    def _emit_tab_state(self) -> None:
        if self.has_error:
            s = "error"
        elif not self.connected:
            s = "off"
        elif self.busy:
            s = "busy"
        else:
            s = "ok"
        self.tab_state_changed.emit(s)


def colored(text: str, color: str) -> str:
    return f"<span style='color:{color}'>{text}</span>"
