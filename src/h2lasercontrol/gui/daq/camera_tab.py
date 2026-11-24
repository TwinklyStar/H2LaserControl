"""IDS camera tab (F8b): the old camera GUI (laserdaq MainWindow), embedded unchanged.

Before Start (and after "Close camera") the tab shows only a start page: the camera is not
opened, so it can be used by another program. Start opens the camera and shows the old window
(sidebar, live view, histogram, auto gain, Capture, Multi-shot run, config selector).
Op log: camera open / close / failures and every finished recording (folder, frames, dropped).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import PROGRAM_DIR, DeviceConfig
from ...oplog import OpLog
from ..style import C, set_role, theme

_log = logging.getLogger(__name__)


class CameraStartPage(QWidget):
    """Start page (named class: our style sheet applies here, not to the camera window)."""


class CameraHeader(QWidget):
    """'Camera open' + Close button above the embedded camera window (styled like our tabs)."""


class CameraTab(QWidget):
    tab_state_changed = Signal(str)
    # for the Shifter tab (F9): camera opened / closed, every displayed frame, finished recording
    open_changed = Signal(bool)
    frame_ready = Signal(object)
    recording_done = Signal(object)  # RecordStats

    def __init__(self, cfg: DeviceConfig, oplog: OpLog, *, sim: bool = False,
                 base_dir: str | os.PathLike[str] = ".", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.oplog = oplog
        self.sim = sim
        self.base_dir = Path(base_dir)
        s = cfg.settings
        self.serial = str(s.get("usb_serial", "")) or None
        # settings files: always the real config folder (also in simulation)
        self.configs_dir = PROGRAM_DIR / s.get("config_dir", "config/camera")
        self.default_config = s.get("default_config", "default.toml")
        self.window: Any = None  # laserdaq MainWindow while the camera is open
        self.locked = ""  # reason, while the Shifter tab uses the camera (F9)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # page 0: start page
        start = CameraStartPage()
        lay = QVBoxLayout(start)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(14)
        title = QLabel(f"<b style='font-size:15pt'>{s.get('label', 'Camera')}</b>")
        model = s.get("model", "IDS camera")
        info = QLabel(
            f"{model}, serial {self.serial or '(first camera found)'}"
            + ("  —  simulated camera" if sim else "") + "<br><br>"
            "The camera is <b>not open</b>. Press <b>Start</b> to open it and show the live view."
            "<br>Pictures are saved to <b>"
            f"{self.base_dir / s.get('output_dir', 'data/camera')}</b> "
            "(the folder in the camera config).<br>"
            "Close other camera programs (IDS peak Cockpit, the old LaserDAQ) first.")
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        self.start_btn = QPushButton("▶  Start camera")
        set_role(self.start_btn, "primary")
        self.start_btn.setFixedWidth(260)
        self.start_btn.clicked.connect(self.start)
        self.start_status = QLabel()
        set_role(self.start_status, "muted")
        self.start_error = QLabel()
        self.start_error.setWordWrap(True)
        set_role(self.start_error, "error")
        self.start_error.hide()
        for w in (title, info, self.start_btn, self.start_status, self.start_error):
            lay.addWidget(w)
        lay.addStretch(1)
        self.stack.addWidget(start)

        # page 1: camera open (header + old window)
        self.open_page = QWidget()
        olay = QVBoxLayout(self.open_page)
        olay.setContentsMargins(8, 6, 8, 0)
        olay.setSpacing(4)
        header = CameraHeader()
        head = QHBoxLayout(header)
        head.setContentsMargins(0, 0, 0, 0)
        self.open_label = QLabel()
        self._render_open_label()
        theme.changed.connect(self._render_open_label)
        self.close_btn = QPushButton("■  Close camera")
        set_role(self.close_btn, "stop")
        self.close_btn.setToolTip("Stop the live view, close the camera, back to the start page")
        self.close_btn.clicked.connect(self.close_camera)
        head.addWidget(self.open_label)
        self.lock_label = QLabel()
        set_role(self.lock_label, "warning")
        self.lock_label.hide()
        head.addSpacing(16)
        head.addWidget(self.lock_label)
        head.addStretch(1)
        head.addWidget(self.close_btn)
        olay.addWidget(header)
        self.window_holder = QVBoxLayout()
        olay.addLayout(self.window_holder, 1)
        self.stack.addWidget(self.open_page)
        self._emit_state("off")

    def _render_open_label(self) -> None:
        self.open_label.setText(f"<b style='color:{C.GREEN}'>●</b> <b>Camera open</b>")

    # --- state ------------------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self.window is not None

    @property
    def running(self) -> bool:
        """True while a recording (Capture / Multi-shot run) is in progress."""
        w = self.window
        return bool(w is not None and w._controller is not None and w._controller.recording)

    def _emit_state(self, state: str) -> None:
        self.tab_state_changed.emit(state)

    # --- used by the Shifter tab (F9) --------------------------------------------------------
    def config_names(self) -> list[str]:
        """Camera config files (the camera window's drop-down list)."""
        return sorted(p.name for p in self.configs_dir.glob("*.toml"))

    def current_config(self) -> str | None:
        """Name of the config file selected in the camera window (None = camera closed)."""
        if self.window is None:
            return None
        return self.window._config_combo.currentText() or None

    def load_config(self, name: str) -> None:
        """Select and load a config file in the camera window, as if chosen in its drop-down:
        exposure, gain and (if stored) trigger mode / FPS. Raises if it cannot be loaded."""
        win = self.window
        if win is None:
            raise RuntimeError("the camera is not open")
        path = self.configs_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"camera config {name} not found in {self.configs_dir}")
        from ...laserdaq.config import load_config
        load_config(path)  # raises with the reason if the file is broken
        win._refresh_config_list()
        combo = win._config_combo
        combo.blockSignals(True)
        combo.setCurrentIndex(combo.findText(name))
        combo.blockSignals(False)
        win._load_session_config(path)
        self.oplog.write(device=self.cfg.key, action="load_config", args={"config": name},
                         result={"exposure_us": win._exposure_spin.value(),
                                 "trigger": win._config.trigger_mode or "unchanged"})

    def start_burst(self, n: int) -> None:
        """Record the next n frames as a normal Multi-shot run. Raises if it cannot start."""
        win = self.window
        if win is None:
            raise RuntimeError("the camera is not open")
        if not win._start_recording(n):
            raise RuntimeError(win._status_label.text() or "the camera is not ready (live view)")

    def stop_burst(self) -> None:
        if self.window is not None and self.running:
            self.window._stop_run()

    def set_locked(self, reason: str) -> None:
        """Lock the camera window while the Shifter tab uses it ("" = unlock)."""
        self.locked = reason
        self.lock_label.setText(f"🔒 {reason}" if reason else "")
        self.lock_label.setVisible(bool(reason))
        self.close_btn.setEnabled(not reason)
        self.start_btn.setEnabled(not reason)
        if self.window is not None:
            self.window.setEnabled(not reason)

    # --- start / close ----------------------------------------------------------------------
    def start(self) -> None:
        if self.window is not None:
            return
        self.start_btn.setEnabled(False)
        self.start_error.hide()
        self.start_status.setText("Opening the camera … (a few seconds)")
        self._emit_state("busy")
        QTimer.singleShot(30, self._open)  # let the text appear before the blocking open

    def _make_camera(self):
        if self.sim:
            from ...laserdaq.camera.mock import MockCamera
            return MockCamera(simulate_spot=True, fps=5.0)
        from ...laserdaq.camera.ids_camera import IDSCamera
        return IDSCamera(serial=self.serial)

    def _load_config(self):
        from ...laserdaq.config import AppConfig, load_config
        path = self.configs_dir / self.default_config
        return load_config(path) if path.exists() else AppConfig()

    def _open(self) -> None:
        from ...laserdaq.gui.main_window import MainWindow

        try:
            camera = self._make_camera()
            win = MainWindow(self._load_config(), camera=None,
                             camera_label=f"serial {self.serial}" if self.serial else "",
                             configs_dir=self.configs_dir, base_dir=self.base_dir)
            win.setWindowFlags(Qt.WindowType.Widget)
            win.set_camera(camera)  # opens the camera (blocking, as in the old program)
            ok = win._camera_ready
            err = "" if ok else (win._status_label.text() or "Camera could not be opened")
        except Exception as exc:  # noqa: BLE001 - e.g. SDK not installed
            _log.exception("camera open failed")
            win, ok, err = None, False, f"{type(exc).__name__}: {exc}"
        self.start_btn.setEnabled(True)
        self.start_status.setText("")
        if not ok:
            if win is not None:
                win.shutdown()
                win.deleteLater()
            self.start_error.setText(
                f"{err}<br>Check the USB cable and that no other program uses the camera. "
                "If it still fails: unplug and re-plug the camera's USB cable.")
            self.start_error.show()
            self.oplog.write(device=self.cfg.key, action="open", event="failed", error=err,
                             args={"serial": self.serial})
            self._emit_state("error")
            return
        win._load_trigger_from_config()  # trigger mode / FPS stored in the config (F9c)
        self.window = win
        win._controller.recording_finished.connect(self._on_recording_finished)
        win._controller.frame_ready.connect(self.frame_ready)
        self.window_holder.addWidget(win, 1)
        win.show()
        self.stack.setCurrentWidget(self.open_page)
        self.oplog.write(device=self.cfg.key, action="open", args={"serial": self.serial},
                         result={"link": win._camera_label})
        self._emit_state("ok")
        self.open_changed.emit(True)

    def close_camera(self, *, ask: bool = True) -> bool:
        win = self.window
        if win is None:
            return True
        if ask and self.running:
            box = QMessageBox(QMessageBox.Icon.Warning, "Recording in progress",
                              "A recording is running. Stop it, save what was recorded so far, "
                              "and close the camera?",
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                              self)
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return False
        self.window = None
        try:
            win.shutdown()  # stops acquisition, flushes a recording, closes the camera
        finally:
            self.window_holder.removeWidget(win)
            win.hide()
            win.deleteLater()
            self.stack.setCurrentIndex(0)
            self.oplog.write(device=self.cfg.key, action="close")
            self._emit_state("off")
            self.start_status.setText("Camera closed.")  # grey: role "muted"
            self.open_changed.emit(False)
        return True

    def shutdown(self) -> None:
        self.close_camera(ask=False)

    def _on_recording_finished(self, stats: Any) -> None:
        self.oplog.write(
            device=self.cfg.key, action="record",
            event="done" if not stats.dropped else "failed",
            result={"folder": str(stats.run_dir), "written": stats.written,
                    "submitted": stats.submitted, "dropped": stats.dropped},
            error=f"{stats.dropped} frame(s) dropped (disk too slow)" if stats.dropped else None,
            duration_s=stats.elapsed_s)
        self.recording_done.emit(stats)
