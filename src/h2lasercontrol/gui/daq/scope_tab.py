"""PicoScope tab: Start / Pause / Stop + the ported plot view (F8a).

Nothing starts by itself. Once started, the acquisition keeps running in its own threads while
other tabs are shown, until Stop is pressed (or the program is closed). Pause: no triggers are
taken and nothing is written; the display freezes; Resume continues in the same files.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...config import DeviceConfig
from ...daq.picoscope.session import PAUSED, RUNNING, STARTING, STOPPED, STOPPING, PicoSession
from ...oplog import OpLog
from ..style import BLUE, GREEN, GREY, ORANGE, set_role
from .scope_views import ContinuousView, SnapshotView

POLL_MS = 100  # 10 Hz, as the old monitor windows

STATE_TEXT = {
    STOPPED: ("Stopped", GREY),
    STARTING: ("Starting … (opening the scopes takes a few seconds)", BLUE),
    RUNNING: ("Running", GREEN),
    PAUSED: ("Paused: no data is taken or saved", ORANGE),
    STOPPING: ("Stopping … (closing files)", BLUE),
}


class ScopeTab(QWidget):
    tab_state_changed = Signal(str)  # "ok" | "busy" | "off" | "error" (same as device tabs)

    def __init__(self, cfg: DeviceConfig, oplog: OpLog, *, sim: bool = False,
                 base_dir: str | os.PathLike[str] = ".", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.oplog = oplog
        self.session = PicoSession(cfg.key, cfg.settings, oplog, sim=sim, base_dir=base_dir)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.state_label = QLabel()
        self.start_btn = QPushButton("▶  Start")
        self.pause_btn = QPushButton("⏸  Pause")
        self.stop_btn = QPushButton("■  Stop")
        set_role(self.start_btn, "primary")
        set_role(self.pause_btn, "primary")
        set_role(self.stop_btn, "stop")
        self.start_btn.setToolTip("Open the scope(s) and start taking and saving data")
        self.pause_btn.setToolTip("Pause: stop taking data (files stay open); press again to resume")
        self.stop_btn.setToolTip("Stop taking data, close the files and release the scope(s)")
        self.start_btn.clicked.connect(self.start)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.stop_btn.clicked.connect(self.stop)
        header.addWidget(self.state_label)
        header.addStretch(1)
        for b in (self.start_btn, self.pause_btn, self.stop_btn):
            header.addWidget(b)
        root.addLayout(header)

        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        set_role(self.detail_label, "muted")
        root.addWidget(self.detail_label)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #dddddd;")
        root.addWidget(line)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        set_role(self.error_label, "error")
        self.error_label.hide()
        root.addWidget(self.error_label)

        s = self.session
        if s.mode == "snapshot":
            name, dcfg = next(iter(s.configs.items()))
            self.view: Any = SnapshotView(
                dcfg["channels"], dcfg["channel_name"], device=name,
                signal_channel=dcfg.get("snapshot_channel", dcfg["channels"][0]),
                snapshot_dir=os.path.join(s.data_path(dcfg), "snapshots"))
            self.view.saved.connect(self._on_snapshot_saved)
        else:
            self.view = ContinuousView(s.channel_names(), s.channel_groups())
        root.addWidget(self.view, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_MS)
        self._last_tab_state = ""
        self._refresh()

    # --- actions ------------------------------------------------------------------------------
    def start(self) -> None:
        self.error_label.hide()
        self.session.start()
        self._refresh()

    def toggle_pause(self) -> None:
        if self.session.state == PAUSED:
            self.session.resume()
        else:
            self.session.pause()
        self._refresh()

    def stop(self) -> None:
        self.session.stop()
        self._refresh()

    @property
    def running(self) -> bool:
        return self.session.state != STOPPED

    def shutdown(self) -> None:
        self.timer.stop()
        self.session.shutdown()

    def _on_snapshot_saved(self, path: str) -> None:
        self.oplog.write(device=self.cfg.key, action="save_snapshot", result={"file": path})

    # --- polling ------------------------------------------------------------------------------
    def poll(self) -> None:
        items = self.session.poll()
        if items:
            self.view.show_items(items)
        self._refresh()

    def _refresh(self) -> None:
        s = self.session
        text, color = STATE_TEXT[s.state]
        self.state_label.setText(f"<b style='color:{color}; font-size:13pt'>●</b> "
                                 f"<b style='font-size:13pt'>{text}</b>")
        self.start_btn.setEnabled(s.state == STOPPED)
        self.pause_btn.setEnabled(s.state in (RUNNING, PAUSED, STARTING))
        self.pause_btn.setText("▶  Resume" if s.state == PAUSED else "⏸  Pause")
        self.stop_btn.setEnabled(s.state in (RUNNING, PAUSED, STARTING))

        lines = []
        for name, dcfg in s.configs.items():
            st = s.states.get(name, STOPPED) if s.digitizers else STOPPED
            part = (f"<b>{name}</b> ({dcfg.get('model')} {dcfg.get('serial')}, "
                    f"{', '.join(dcfg['channel_name'])}): {st}")
            if name in s.rates and st == RUNNING:
                part += f", {s.rates[name]:.1f} triggers/s"
            if name in s.warnings:
                part += f" <span style='color:{ORANGE}'><b>⚠ {s.warnings[name]}</b></span>"
            lines.append(part)
        paths = sorted({s.data_path(c) for c in s.configs.values()})
        lines.append("Data: " + ", ".join(paths))
        self.detail_label.setText("<br>".join(lines))

        if s.errors:
            self.error_label.setText("<br>".join(
                f"{name} stopped with an error: {msg}" for name, msg in s.errors.items()))
            self.error_label.show()

        if s.errors:
            tab = "error"
        elif s.state in (RUNNING,):
            tab = "ok"
        elif s.state in (STARTING, STOPPING, PAUSED):
            tab = "busy"
        else:
            tab = "off"
        if tab != self._last_tab_state:
            self._last_tab_state = tab
            self.tab_state_changed.emit(tab)
