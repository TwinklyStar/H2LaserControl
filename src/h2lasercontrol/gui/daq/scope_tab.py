"""PicoScope tab: start page (config drop-down + Start), then Pause / Stop + plots (F8a).

Nothing starts by itself. Until Start, and again after Stop, the tab shows only a start page:
a drop-down of the config files (config/picoscope/*.toml of this tab's mode, user 2026-11-18),
what the selected config does, and one Start button. Once started, the acquisition keeps running
in its own threads while other tabs are shown, until Stop is pressed (or the program is closed).
Pause: no triggers are taken and nothing is written; the display freezes; Resume continues in
the same files. Each Start gets a fresh plot view.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import PROGRAM_DIR, DeviceConfig
from ...daq.picoscope.averaging import default_n
from ...daq.picoscope.configs import ScopeConfig, list_scope_configs
from ...daq.picoscope.history import DEFAULT_WINDOW, TrendSource
from ...daq.picoscope.session import PAUSED, RUNNING, STARTING, STOPPED, STOPPING, PicoSession
from ...oplog import OpLog
from ..style import C, set_role, theme
from .scope_views import ContinuousView, SnapshotView

# The snapshot plot is redrawn per poll that brought new waveforms (user: 10-25 fps). Polling at
# the trigger period (40 ms) gave 20.9 fps at 25 Hz on hardware (timer jitter merges waveforms);
# 20 ms lets nearly every waveform get its own frame.
POLL_MS = 20


def shown_channels(dcfg: dict[str, Any]) -> list[str]:
    """Channels plotted for one digitizer: all except its trigger channel (user 2026-11-18:
    the trigger waveform is not shown; its rate is in the status row). Files keep all channels."""
    trig = dcfg.get("trigger_channel")
    shown = [c for c in dcfg["channels"] if c != trig]
    return shown or list(dcfg["channels"])


def shown_channel_names(dcfg: dict[str, Any]) -> list[str]:
    names = dict(zip(dcfg["channels"], dcfg["channel_name"], strict=True))
    return [names[c] for c in shown_channels(dcfg)]

STATE_TEXT = {  # colour = name of a theme colour (style.C)
    STOPPED: ("Stopped", "GREY"),
    STARTING: ("Starting … (opening a scope takes up to about 10 s)", "BLUE"),
    RUNNING: ("Running", "GREEN"),
    PAUSED: ("Paused: no data is taken or saved", "ORANGE"),
    STOPPING: ("Stopping … (closing files)", "BLUE"),
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
        self.base_dir = base_dir
        s = cfg.settings
        self.mode = s.get("mode", "continuous")
        # config files: always the real config folder (also in simulation)
        self.config_dir = PROGRAM_DIR / s.get("config_dir", "config/picoscope")
        self.configs: list[ScopeConfig] = []
        self.scope_config: ScopeConfig | None = None
        self.session: PicoSession | None = None
        self.view: Any = None  # plot view while started
        self.trend_window = DEFAULT_WINDOW  # monitor trend span, kept between runs
        self.snapshot_n: int | None | str = "config"  # averaged waveforms, kept between runs

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # --- page 0: start page ---------------------------------------------------------------
        start = ScopeStartPage()
        lay = QVBoxLayout(start)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(14)
        self._title = title = QLabel()
        self._render_title()
        row = QHBoxLayout()
        row.addWidget(QLabel("Config:"))
        self.config_combo = QComboBox()
        self.config_combo.setMinimumWidth(460)
        self.config_combo.setToolTip(f"Config files ({self.mode} mode) in {self.config_dir}")
        self.config_combo.currentIndexChanged.connect(self._on_config_selected)
        self.reload_btn = QPushButton("↺")
        self.reload_btn.setToolTip("Read the config folder again (after adding or editing a file)")
        self.reload_btn.clicked.connect(self.reload_configs)
        row.addWidget(self.config_combo)
        row.addWidget(self.reload_btn)
        row.addStretch(1)
        self.config_info = QLabel()
        self.config_info.setWordWrap(True)
        self.config_info.setTextFormat(Qt.TextFormat.RichText)
        self.config_errors = QLabel()
        self.config_errors.setWordWrap(True)
        set_role(self.config_errors, "muted")
        self.config_errors.hide()
        note = QLabel("The scopes are <b>not open</b>. Press <b>Start</b> to open them and start "
                      "taking and saving data. It keeps running while you use other tabs, until "
                      "you press Stop. Close PicoScope 7 and the old H2LaserDAQ program first.")
        note.setWordWrap(True)
        self.start_btn = QPushButton("▶  Start")
        set_role(self.start_btn, "primary")
        self.start_btn.setFixedWidth(260)
        self.start_btn.setToolTip("Open the scope(s) with the selected config and start taking "
                                  "and saving data")
        self.start_btn.clicked.connect(self.start)
        self.start_error = QLabel()
        self.start_error.setWordWrap(True)
        set_role(self.start_error, "error")
        self.start_error.hide()
        lay.addWidget(title)
        lay.addLayout(row)
        for w in (self.config_info, self.config_errors, note, self.start_btn, self.start_error):
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
        set_role(line, "sep")
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

        self._last_tab_state = ""
        self.reload_configs(select=s.get("default_config"))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_MS)
        theme.changed.connect(self._retheme)

    # --- light / dark theme -------------------------------------------------------------------
    def _render_title(self) -> None:
        self._title.setText(
            f"<b style='font-size:15pt'>{self.cfg.settings.get('label', self.cfg.key)}</b>"
            + (f"  <span style='color:{C.SIM_FG}'>(simulated scopes)</span>" if self.sim else ""))

    def _render_no_config(self) -> None:
        self.config_info.setText(f"<span style='color:{C.RED}'>No {self.mode} config file in "
                                 f"{self.config_dir}.</span>")

    def _retheme(self) -> None:
        self._render_title()
        if self.scope_config is None:
            self._render_no_config()
        self._refresh()  # state line (the plot view recolours itself)

    # --- config selection ---------------------------------------------------------------------
    def reload_configs(self, *, select: str | None = None) -> None:
        """Re-read the config folder; keep the current choice (or `select`) if still there."""
        if self.session is not None and self.session.state != STOPPED:
            return
        keep = select or (self.scope_config.name if self.scope_config else None)
        self.configs, errors = list_scope_configs(self.config_dir, self.mode)
        self.config_combo.blockSignals(True)
        self.config_combo.clear()
        for c in self.configs:
            self.config_combo.addItem(f"{c.title}   ({c.name})", c.name)
        idx = self.config_combo.findData(keep) if keep else -1
        self.config_combo.setCurrentIndex(max(idx, 0) if self.configs else -1)
        self.config_combo.blockSignals(False)
        if errors:
            self.config_errors.setText("Not usable (fix the file, then ↺):<br>"
                                       + "<br>".join(errors))
        self.config_errors.setVisible(bool(errors))
        self._on_config_selected()

    def _on_config_selected(self, *_: Any) -> None:
        name = self.config_combo.currentData()
        self.scope_config = next((c for c in self.configs if c.name == name), None)
        sc = self.scope_config
        if sc is None:
            self.session = None
            self._render_no_config()
        else:
            self.session = PicoSession(self.cfg.key, sc.settings(), self.oplog, sim=self.sim,
                                       base_dir=self.base_dir)
            self.config_info.setText(self._describe(sc, self.session))
        self.start_error.hide()
        self._refresh()

    @staticmethod
    def _describe(sc: ScopeConfig, s: PicoSession) -> str:
        scopes = "<br>".join(
            f"• <b>{name}</b>: PicoScope {d.get('model')} {d.get('serial')}, channels "
            + ", ".join(f"{c} = {n}" for c, n in zip(d["channels"], d["channel_name"], strict=True))
            + f", trigger {d.get('trigger_channel')}"
            + f"  →  files <b>{d.get('output_name')}_…</b>"
            for name, d in sc.digitizers.items())
        if sc.mode == "continuous":
            mode = ("continuous monitor: trend of the pulse area of each channel (last 10 min … "
                    "14 days, older points from the CSV files) + waveforms averaged over 100 "
                    "triggers. The trigger channel is saved but not plotted.")
        else:
            d = next(iter(sc.digitizers.values()))
            sig = dict(zip(d["channels"], d["channel_name"], strict=True)).get(
                d.get("snapshot_channel"), d.get("snapshot_channel"))
            mode = ("snapshot, like an oscilloscope: average of the last N waveforms "
                    f"(starts at N = {default_n(d.get('refresh_trigger_cnt'))}; ▲ / ▼ for 1 … "
                    "1024 or ∞), redrawn with every trigger; offset, area, std, N and stderr "
                    f"of channel {d.get('snapshot_channel')} ({sig}); Clear / Freeze / Save. "
                    "The trigger channel is saved but not plotted.")
        paths = ", ".join(sorted({s.data_path(c) for c in s.configs.values()}))
        return f"{scopes}<br>Mode: {mode}<br>Data is saved to <b>{paths}</b>."

    # --- actions ------------------------------------------------------------------------------
    def start(self) -> None:
        s = self.session
        if s is None or s.state != STOPPED:
            return
        self.start_error.hide()
        self.error_label.hide()
        self._make_view()
        s.start()
        self.stack.setCurrentWidget(self.run_page)
        self._refresh()

    def toggle_pause(self) -> None:
        if self.session is None:
            return
        if self.session.state == PAUSED:
            self.session.resume()
        else:
            self.session.pause()
        self._refresh()

    def stop(self) -> None:
        if self.session is not None:
            self.session.stop()
        self._refresh()

    @property
    def running(self) -> bool:
        return self.session is not None and self.session.state != STOPPED

    def shutdown(self) -> None:
        self.timer.stop()
        if self.session is not None:
            self.session.shutdown()

    def _make_view(self) -> None:
        s = self.session
        assert s is not None
        if s.mode == "snapshot":
            name, dcfg = next(iter(s.configs.items()))
            shown = shown_channels(dcfg)
            n_avg = (default_n(dcfg.get("refresh_trigger_cnt")) if self.snapshot_n == "config"
                     else self.snapshot_n)
            view: Any = SnapshotView(
                shown, [dict(zip(dcfg["channels"], dcfg["channel_name"], strict=True))[c]
                        for c in shown], device=name,
                signal_channel=dcfg.get("snapshot_channel", dcfg["channels"][0]),
                snapshot_dir=os.path.join(s.data_path(dcfg), "snapshots"), n_avg=n_avg)
            view.saved.connect(self._on_snapshot_saved)
            for b in (view._n_up, view._n_down):
                b.clicked.connect(lambda _=False, v=view: setattr(self, "snapshot_n", v.n_avg))
        else:
            groups = [shown_channel_names(c) for c in s.configs.values()]
            sources = [TrendSource(os.path.join(s.data_path(c), "csv"), c["output_name"],
                                   tuple(shown_channel_names(c))) for c in s.configs.values()]
            view = ContinuousView([n for g in groups for n in g], groups,
                                  history_sources=sources, window=self.trend_window)
            view.window_combo.currentTextChanged.connect(self._remember_window)
        self.view = view
        self.view_holder.addWidget(view, 1)

    def _remember_window(self, label: str) -> None:
        self.trend_window = label

    def _drop_view(self) -> None:
        if self.view is not None:
            self.view_holder.removeWidget(self.view)
            self.view.deleteLater()
            self.view = None

    def _on_snapshot_saved(self, path: str) -> None:
        self.oplog.write(device=self.cfg.key, action="save_snapshot", result={"file": path})

    # --- polling ------------------------------------------------------------------------------
    def poll(self) -> None:
        if self.session is None:
            return
        items = self.session.poll()
        if items and self.view is not None:
            self.view.show_items(items)
        self._refresh()

    def _errors_html(self) -> str:
        assert self.session is not None
        return "<br>".join(f"{name} stopped with an error: {msg}"
                           for name, msg in self.session.errors.items())

    def _refresh(self) -> None:
        s = self.session
        state = s.state if s is not None else STOPPED
        if state == STOPPED and self.stack.currentWidget() is self.run_page:
            # stopped (by Stop, or every scope failed): back to the start page
            self._drop_view()
            self.stack.setCurrentIndex(0)
            if s is not None and s.errors:
                self.start_error.setText(self._errors_html())
                self.start_error.show()

        text, color = STATE_TEXT[state]
        color = getattr(C, color)
        self.state_label.setText(f"<b style='color:{color}; font-size:13pt'>●</b> "
                                 f"<b style='font-size:13pt'>{text}</b>"
                                 + (f"  <span style='color:{C.GREY}'>— {self.scope_config.title} "
                                    f"({self.scope_config.name})</span>"
                                    if self.scope_config else ""))
        self.start_btn.setEnabled(s is not None and state == STOPPED)
        self.config_combo.setEnabled(state == STOPPED)
        self.reload_btn.setEnabled(state == STOPPED)
        self.pause_btn.setEnabled(state in (RUNNING, PAUSED, STARTING))
        self.pause_btn.setText("▶  Resume" if state == PAUSED else "⏸  Pause")
        self.stop_btn.setEnabled(state in (RUNNING, PAUSED, STARTING))

        if s is not None:
            lines = []
            for name, dcfg in s.configs.items():
                st = s.states.get(name, STOPPED) if s.digitizers else STOPPED
                part = (f"<b>{name}</b> ({dcfg.get('model')} {dcfg.get('serial')}, "
                        f"{', '.join(dcfg['channel_name'])}): {st}")
                if name in s.warnings:
                    part += f" <span style='color:{C.ORANGE}'><b>⚠ {s.warnings[name]}</b></span>"
                lines.append(part)
            paths = sorted({s.data_path(c) for c in s.configs.values()})
            lines.append("Data: " + ", ".join(paths))
            self.detail_label.setText("<br>".join(lines))
            if self.view is not None:  # trigger rate in the plot's status row (user 2026-11-18)
                self.view.set_rates({
                    name: s.rates.get(name) if s.states.get(name) == RUNNING else None
                    for name in s.configs})
            if s.errors and state != STOPPED:
                self.error_label.setText(self._errors_html())
                self.error_label.show()

        if s is not None and s.errors:
            tab = "error"
        elif state == RUNNING:
            tab = "ok"
        elif state in (STARTING, STOPPING, PAUSED):
            tab = "busy"
        else:
            tab = "off"
        if tab != self._last_tab_state:
            self._last_tab_state = tab
            self.tab_state_changed.emit(tab)
