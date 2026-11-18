"""PicoScope tab: start page, then Pause / Stop + the ported plot view (F8a).

Nothing starts by itself. Until Start, and again after Stop, the tab shows only a start page
(which scopes, where the data goes, one Start button; user 2026-11-18). Once started, the
acquisition keeps running in its own threads while other tabs are shown, until Stop is pressed
(or the program is closed). Pause: no triggers are taken and nothing is written; the display
freezes; Resume continues in the same files. Each Start gets a fresh plot view.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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


class ScopeStartPage(QWidget):
    """Start page (named class for the style sheet, see style.OWN)."""


class ScopeTab(QWidget):
    tab_state_changed = Signal(str)  # "ok" | "busy" | "off" | "error" (same as device tabs)

    def __init__(self, cfg: DeviceConfig, oplog: OpLog, *, sim: bool = False,
                 base_dir: str | os.PathLike[str] = ".", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.oplog = oplog
        self.sim = sim
        self.session = PicoSession(cfg.key, cfg.settings, oplog, sim=sim, base_dir=base_dir)
        self.view: Any = None  # plot view while started
        s = self.session

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # --- page 0: start page ---------------------------------------------------------------
        start = ScopeStartPage()
        lay = QVBoxLayout(start)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(14)
        title = QLabel(f"<b style='font-size:15pt'>{cfg.settings.get('label', cfg.key)}</b>")
        scopes = "<br>".join(
            f"• <b>{name}</b>: PicoScope {d.get('model')} {d.get('serial')}, channels "
            + ", ".join(f"{c} = {n}" for c, n in zip(d["channels"], d["channel_name"], strict=True))
            + f"  →  files <b>{d.get('output_name')}_…</b>"
            for name, d in s.configs.items())
        mode = ("continuous monitor: trend of the pulse area + averaged waveforms"
                if s.mode == "continuous" else
                f"snapshot: averaged waveform and pulse area of channel "
                f"{next(iter(s.configs.values())).get('snapshot_channel', 'A')}, Freeze / Save")
        paths = ", ".join(sorted({s.data_path(c) for c in s.configs.values()}))
        info = QLabel(
            f"{scopes}<br><br>Mode: {mode}"
            + ("  —  <b>simulated scopes</b>" if sim else "") + "<br>"
            f"Data is saved to <b>{paths}</b>.<br><br>"
            "The scopes are <b>not open</b>. Press <b>Start</b> to open them and start taking "
            "and saving data. It keeps running while you use other tabs, until you press Stop."
            "<br>Close PicoScope 7 and the old H2LaserDAQ program first.")
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        self.start_btn = QPushButton("▶  Start")
        set_role(self.start_btn, "primary")
        self.start_btn.setFixedWidth(260)
        self.start_btn.setToolTip("Open the scope(s) and start taking and saving data")
        self.start_btn.clicked.connect(self.start)
        self.start_error = QLabel()
        self.start_error.setWordWrap(True)
        set_role(self.start_error, "error")
        self.start_error.hide()
        for w in (title, info, self.start_btn, self.start_error):
            lay.addWidget(w)
        lay.addStretch(1)
        self.stack.addWidget(start)

        # --- page 1: running ------------------------------------------------------------------
        run = QWidget()
        rlay = QVBoxLayout(run)
        rlay.setContentsMargins(16, 12, 16, 12)
        rlay.setSpacing(8)
        header = QHBoxLayout()
        self.state_label = QLabel()
        self.pause_btn = QPushButton("⏸  Pause")
        self.stop_btn = QPushButton("■  Stop")
        set_role(self.pause_btn, "primary")
        set_role(self.stop_btn, "stop")
        self.pause_btn.setToolTip("Pause: stop taking data (files stay open); press again to resume")
        self.stop_btn.setToolTip("Stop taking data, close the files and release the scope(s)")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.stop_btn.clicked.connect(self.stop)
        header.addWidget(self.state_label)
        header.addStretch(1)
        header.addWidget(self.pause_btn)
        header.addWidget(self.stop_btn)
        rlay.addLayout(header)
        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        set_role(self.detail_label, "muted")
        rlay.addWidget(self.detail_label)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #dddddd;")
        rlay.addWidget(line)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        set_role(self.error_label, "error")
        self.error_label.hide()
        rlay.addWidget(self.error_label)
        self.view_holder = QVBoxLayout()
        rlay.addLayout(self.view_holder, 1)
        self.run_page = run
        self.stack.addWidget(run)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_MS)
        self._last_tab_state = ""
        self._refresh()

    # --- actions ------------------------------------------------------------------------------
    def start(self) -> None:
        if self.session.state != STOPPED:
            return
        self.start_error.hide()
        self.error_label.hide()
        self._make_view()
        self.session.start()
        self.stack.setCurrentWidget(self.run_page)
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

    def _make_view(self) -> None:
        s = self.session
        if s.mode == "snapshot":
            name, dcfg = next(iter(s.configs.items()))
            view: Any = SnapshotView(
                dcfg["channels"], dcfg["channel_name"], device=name,
                signal_channel=dcfg.get("snapshot_channel", dcfg["channels"][0]),
                snapshot_dir=os.path.join(s.data_path(dcfg), "snapshots"))
            view.saved.connect(self._on_snapshot_saved)
        else:
            view = ContinuousView(s.channel_names(), s.channel_groups())
        self.view = view
        self.view_holder.addWidget(view, 1)

    def _drop_view(self) -> None:
        if self.view is not None:
            self.view_holder.removeWidget(self.view)
            self.view.deleteLater()
            self.view = None

    def _on_snapshot_saved(self, path: str) -> None:
        self.oplog.write(device=self.cfg.key, action="save_snapshot", result={"file": path})

    # --- polling ------------------------------------------------------------------------------
    def poll(self) -> None:
        items = self.session.poll()
        if items and self.view is not None:
            self.view.show_items(items)
        self._refresh()

    def _errors_html(self) -> str:
        return "<br>".join(f"{name} stopped with an error: {msg}"
                           for name, msg in self.session.errors.items())

    def _refresh(self) -> None:
        s = self.session
        if s.state == STOPPED and self.stack.currentWidget() is self.run_page:
            # stopped (by Stop, or every scope failed): back to the start page
            self._drop_view()
            self.stack.setCurrentIndex(0)
            if s.errors:
                self.start_error.setText(self._errors_html())
                self.start_error.show()

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

        if s.errors and s.state != STOPPED:
            self.error_label.setText(self._errors_html())
            self.error_label.show()

        if s.errors:
            tab = "error"
        elif s.state == RUNNING:
            tab = "ok"
        elif s.state in (STARTING, STOPPING, PAUSED):
            tab = "busy"
        else:
            tab = "off"
        if tab != self._last_tab_state:
            self._last_tab_state = tab
            self.tab_state_changed.emit(tab)
