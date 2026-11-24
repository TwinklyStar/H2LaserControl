"""Shifter tab (design-document F9): monitor of the operating state + the NO cell, three
one-click measurements, Stop, Return to operating state, and a preview.

The logic (steps, runner, operating-state check) is in `h2lasercontrol.shifter`; this file only
shows it. The tab uses the program's own device services and DAQ tabs (nothing is opened
twice). While a measurement runs, the device tabs it uses are locked (their STOP still works).
"""

from __future__ import annotations

import html
import os
import time
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..daq.picoscope.averaging import default_n
from ..daq.picoscope.history import TrendSource
from ..shifter import (
    DONE,
    FAILED,
    MEASUREMENTS,
    STOPPED,
    Sequence,
    SequenceRunner,
    ShifterContext,
    blocking,
    duration_text,
    operating_state,
    return_to_operating,
)
from .daq.scope_tab import shown_channel_names, shown_channels
from .daq.scope_views import ContinuousView, SnapshotView
from .style import C, set_role, theme

REFRESH_MS = 500
# which drop-down each measurement box has: (choice key, label)
BOX_CHOICE = {"vuv_energy": ("vuv", "VUV PD config:"), "profile_122": ("122", "Camera config:"),
              "profile_355": ("355", "Camera config:")}
BOX_TEXT = {
    "vuv_energy": "Pulse energy of the VUV light with the VUV photodiode",
    "profile_122": "Beam profile of the 122 nm light on the profiler camera",
    "profile_355": "Beam profile of the 355 nm light (at reduced energy) on the profiler camera",
}


def _mark(state: str) -> tuple[str, str]:
    """Symbol and colour of a step state."""
    return {"waiting": ("○", C.GREY), "running": ("▶", C.BLUE), "done": ("✓", C.GREEN),
            "failed": ("✖", C.RED), "skipped": ("–", C.GREY)}[state]


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


class FunctionBox(QGroupBox):
    """One measurement: description, drop-down, Start, readiness, steps, result."""

    def __init__(self, key: str, sequence: Sequence, parent: QWidget | None = None) -> None:
        super().__init__(sequence.title, parent)
        self.key = key
        self.sequence = sequence
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        self.text_label = QLabel(BOX_TEXT.get(key, ""))
        self.text_label.setWordWrap(True)
        self.estimate_label = QLabel()
        set_role(self.estimate_label, "muted")
        row = QHBoxLayout()
        self.combo_label = QLabel(BOX_CHOICE[key][1])
        self.combo = QComboBox()
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(14)
        row.addWidget(self.combo_label)
        row.addWidget(self.combo, 1)
        self.start_btn = QPushButton("▶  Start")
        set_role(self.start_btn, "primary")
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        set_role(self.problem_label, "warning")
        self.steps_label = QLabel()
        self.steps_label.setTextFormat(Qt.TextFormat.RichText)
        self.steps_label.setWordWrap(True)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setTextFormat(Qt.TextFormat.RichText)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        for w in (self.text_label, self.estimate_label):
            lay.addWidget(w)
        lay.addLayout(row)
        for w in (self.start_btn, self.problem_label, self.steps_label, self.result_label):
            lay.addWidget(w)
        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)


def steps_html(sequence: Sequence, records: list[Any] | None) -> str:
    lines = []
    now = time.monotonic()
    for i, step in enumerate(sequence.steps):
        rec = records[i] if records else None
        state = rec.state if rec else "waiting"
        sym, color = _mark(state)
        text = html.escape(step.label)
        extra = ""
        if state == "running":
            text = f"<b>{text}</b>"
            extra = f" … {_clock(now - rec.started)}"
            if step.detail:
                extra += f" — {html.escape(step.detail)}"
        elif state == "failed" and rec.message:
            extra = f"<br>&nbsp;&nbsp;&nbsp;<span style='color:{C.RED}'>{html.escape(rec.message)}</span>"
        lines.append(f"<span style='color:{color}'>{sym}</span> {text}"
                     f"<span style='color:{C.GREY}'>{extra}</span>" if state != "failed" else
                     f"<span style='color:{color}'>{sym}</span> {text}{extra}")
    return "<br>".join(lines)


class ShifterTab(QWidget):
    tab_state_changed = Signal(str)  # "ok" | "busy" | "off" | "error"

    def __init__(self, ctx: ShifterContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.runner = SequenceRunner(ctx, self)
        self.runner.changed.connect(self._on_runner_changed)
        self.runner.finished.connect(self._on_finished)
        self.items = []  # last operating-state check
        self.preview_mode = ""  # "" | "vuv" | "camera"
        self.snapshot_view: SnapshotView | None = None
        self.monitor_view: ContinuousView | None = None
        self.live_view: Any = None
        self.last_sequence: Sequence | None = None
        self._last_tab_state = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        root.addWidget(self._build_monitor())
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(self._build_functions(), 3)
        bottom.addWidget(self._build_preview(), 2)
        root.addLayout(bottom, 1)

        # data from the DAQ tabs
        if ctx.monitor is not None:
            ctx.monitor.items_received.connect(self._on_monitor_items)
        if ctx.vuv is not None:
            ctx.vuv.items_received.connect(self._on_vuv_items)
        if ctx.camera is not None:
            ctx.camera.frame_ready.connect(self._on_frame)
            ctx.camera.open_changed.connect(lambda _open: self._fill_combos())

        self._fill_combos()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(REFRESH_MS)
        theme.changed.connect(self._refresh)
        self._refresh()

    # --- building -----------------------------------------------------------------------------
    def _build_monitor(self) -> QWidget:
        box = QGroupBox("Monitor")
        lay = QVBoxLayout(box)
        self.overall_label = QLabel()
        self.overall_label.setTextFormat(Qt.TextFormat.RichText)
        self.overall_label.setWordWrap(True)
        lay.addWidget(self.overall_label)
        row = QHBoxLayout()
        status = QWidget()
        self.status_grid = QGridLayout(status)
        self.status_grid.setContentsMargins(0, 0, 0, 0)
        self.status_grid.setHorizontalSpacing(8)
        self.status_grid.setVerticalSpacing(3)
        self.status_rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        status.setMinimumWidth(360)
        col = QVBoxLayout()
        col.addWidget(status)
        col.addStretch(1)
        row.addLayout(col)

        self.monitor_stack = QStackedWidget()
        idle = QWidget()
        ilay = QVBoxLayout(idle)
        self.monitor_idle_label = QLabel()
        self.monitor_idle_label.setWordWrap(True)
        self.monitor_start_btn = QPushButton("▶  Start the NO cell monitor")
        self.monitor_start_btn.setToolTip("Starts the Scope monitor (DAQ tab) with its selected "
                                          "config: data is taken and saved as usual")
        self.monitor_start_btn.clicked.connect(self._start_monitor)
        ilay.addStretch(1)
        ilay.addWidget(self.monitor_idle_label, 0, Qt.AlignmentFlag.AlignCenter)
        ilay.addWidget(self.monitor_start_btn, 0, Qt.AlignmentFlag.AlignCenter)
        ilay.addStretch(1)
        self.monitor_stack.addWidget(idle)
        self.monitor_page = QWidget()
        self.monitor_holder = QVBoxLayout(self.monitor_page)
        self.monitor_holder.setContentsMargins(0, 0, 0, 0)
        self.monitor_stack.addWidget(self.monitor_page)
        # compact: the measurement boxes below must stay visible (one channel: trend + waveform)
        self.monitor_stack.setFixedHeight(250)
        row.addWidget(self.monitor_stack, 1)
        lay.addLayout(row)
        return box

    def _build_functions(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._build_control())  # on top: Stop must be visible while it runs
        row = QHBoxLayout()
        self.boxes: dict[str, FunctionBox] = {}
        for key, make in MEASUREMENTS.items():
            box = FunctionBox(key, make(self.ctx))
            box.start_btn.clicked.connect(lambda _=False, k=key: self.start(k))
            box.combo.currentIndexChanged.connect(lambda _=0, b=box: self._on_choice(b))
            self.boxes[key] = box
            row.addWidget(box, 1)
        lay.addLayout(row, 1)
        return w

    def _build_control(self) -> QWidget:
        ctrl = QGroupBox("Measurement")
        clay = QVBoxLayout(ctrl)
        buttons = QHBoxLayout()
        self.stop_btn = QPushButton("■  Stop")
        set_role(self.stop_btn, "stop")
        self.stop_btn.setToolTip("Stop the measurement now (the running step is stopped; nothing "
                                 "is moved back)")
        self.stop_btn.clicked.connect(self.stop)
        self.return_btn = QPushButton("↺  Return to operating state")
        self.return_btn.setToolTip(
            "Stop the VUV PD snapshot, retract both feedthroughs and both blockers, rotation "
            "mount to max energy, camera back to its previous config (one after the other)")
        self.return_btn.clicked.connect(self.return_to_operating)
        self.run_label = QLabel()
        self.run_label.setWordWrap(True)
        self.run_label.setTextFormat(Qt.TextFormat.RichText)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.return_btn)
        buttons.addSpacing(12)
        buttons.addWidget(self.run_label, 1)
        clay.addLayout(buttons)
        self.return_steps_label = QLabel()
        self.return_steps_label.setTextFormat(Qt.TextFormat.RichText)
        self.return_steps_label.setWordWrap(True)
        self.return_steps_label.hide()
        clay.addWidget(self.return_steps_label)
        return ctrl

    def _build_preview(self) -> QWidget:
        box = QGroupBox("Preview")
        lay = QVBoxLayout(box)
        self.preview_stack = QStackedWidget()
        idle = QLabel("The preview appears here during a measurement: the VUV PD waveform "
                      "and statistics, or the camera image.")
        idle.setWordWrap(True)
        idle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_role(idle, "muted")
        self.preview_stack.addWidget(idle)
        self.snapshot_page = QWidget()
        self.snapshot_holder = QVBoxLayout(self.snapshot_page)
        self.snapshot_holder.setContentsMargins(0, 0, 0, 0)
        self.preview_stack.addWidget(self.snapshot_page)
        self.camera_page = QWidget()
        self.camera_holder = QVBoxLayout(self.camera_page)
        self.camera_holder.setContentsMargins(0, 0, 0, 0)
        self.preview_stack.addWidget(self.camera_page)
        self.preview_stack.setMinimumHeight(360)
        lay.addWidget(self.preview_stack)
        return box

    def _fill_combos(self) -> None:
        """Drop-down lists: VUV PD configs (snapshot mode) and camera configs."""
        vuv, cam = self.ctx.vuv, self.ctx.camera
        for key, box in self.boxes.items():
            choice = BOX_CHOICE[key][0]
            if choice == "vuv":
                names = [c.name for c in vuv.configs] if vuv is not None else []
            else:
                names = cam.config_names() if cam is not None else []
            want = self.ctx.choice.get(choice, "")
            box.combo.blockSignals(True)
            box.combo.clear()
            box.combo.addItems(names)
            idx = box.combo.findText(want)
            box.combo.setCurrentIndex(idx if idx >= 0 else (0 if names else -1))
            box.combo.blockSignals(False)
            self._on_choice(box)

    def _on_choice(self, box: FunctionBox) -> None:
        text = box.combo.currentText()
        if text:
            self.ctx.choice[BOX_CHOICE[box.key][0]] = text

    # --- actions ------------------------------------------------------------------------------
    def start(self, key: str) -> None:
        if self.runner.running:
            return
        problems = blocking(operating_state(self.ctx), key)
        if problems:
            return
        sequence = MEASUREMENTS[key](self.ctx)
        when = duration_text(sequence.estimate_s(self.ctx))
        box = QMessageBox(
            QMessageBox.Icon.Question, sequence.title,
            f"Perform the {sequence.title}.\n\nThis will take {when} and block the laser beam. "
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.boxes[key].sequence = sequence
        self.boxes[key].result_label.setText("")
        self._run(sequence)

    def return_to_operating(self) -> None:
        if self.runner.running:
            return
        self._run(return_to_operating(self.ctx))

    def stop(self) -> None:
        self.runner.stop()

    def _run(self, sequence: Sequence) -> None:
        self.last_sequence = sequence
        if sequence.key == "vuv_energy":
            self._set_preview("vuv")
        elif sequence.key.startswith("profile"):
            self._set_preview("camera")
        self.return_steps_label.setVisible(sequence.key == "return")
        self._lock(f"In use by the Shifter tab: {sequence.title}.")
        self.runner.run(sequence)
        self._refresh()

    def _lock(self, reason: str) -> None:
        s = self.ctx.settings
        for key in (s.hitmv, s.flipmounts, s.ell14):
            panel = self.ctx.panels.get(key)
            if panel is not None:
                panel.set_locked(reason)
        for tab in (self.ctx.vuv, self.ctx.camera):
            if tab is not None:
                tab.set_locked(reason)

    def _start_monitor(self) -> None:
        mon = self.ctx.monitor
        if mon is not None and not mon.running:
            mon.start()
        self._refresh()

    # --- runner -------------------------------------------------------------------------------
    def _on_runner_changed(self) -> None:
        seq = self.runner.sequence
        if seq is None:
            return
        text = steps_html(seq, self.runner.records)
        if seq.key == "return":
            self.return_steps_label.setText(text)
        elif seq.key in self.boxes:
            self.boxes[seq.key].steps_label.setText(text)
        self._render_run_label()

    def _on_finished(self, outcome: str, message: str) -> None:
        self._lock("")
        self._close_preview()  # user 2026-11-24: the result stays in the box
        seq = self.runner.sequence
        if seq is not None and seq.key in self.boxes:
            self.boxes[seq.key].result_label.setText(self._result_html(outcome, message))
        self._refresh()

    def _result_html(self, outcome: str, message: str) -> str:
        r = self.runner.summary()
        parts = []
        if outcome == DONE:
            parts.append(f"<b style='color:{C.GREEN}'>Finished.</b>")
        elif outcome == STOPPED:
            parts.append(f"<b style='color:{C.ORANGE}'>Stopped.</b> Use “Return to operating "
                         "state”.")
        else:
            parts.append(f"<b style='color:{C.RED}'>Failed:</b> {html.escape(message)}<br>"
                         "Use “Return to operating state”.")
        if "area_nVs" in r:
            parts.append(f"<b>Area {r['area_nVs']:.4g} ± {r['stderr_nVs']:.2g} nV·s</b> "
                         f"(N = {r['n']}, std {r['std_nVs']:.3g})")
            parts.append("CSV: " + html.escape(os.path.basename(r["csv"])))
            for f in r.get("root", []):
                parts.append("ROOT: " + html.escape(os.path.basename(f)))
        if "photos" in r:
            p = r["photos"]
            parts.append(f"{p['photos']} photos → {html.escape(str(p['folder']))}")
        return "<br>".join(parts)

    def _render_run_label(self) -> None:
        run = self.runner
        seq = run.sequence
        if run.running and seq is not None:
            elapsed = _clock(time.monotonic() - run.started_at)
            what = "Stopping …" if run.stopping else "Running:"
            self.run_label.setText(f"<b style='color:{C.BLUE}'>{what}</b> {seq.title} "
                                   f"(step {run.index + 1} of {len(seq.steps)}, {elapsed})")
        elif seq is not None and run.outcome:
            color = {DONE: C.GREEN, STOPPED: C.ORANGE, FAILED: C.RED}[run.outcome]
            word = {DONE: "Finished", STOPPED: "Stopped", FAILED: "Failed"}[run.outcome]
            msg = f": {html.escape(run.message)}" if run.message else "."
            self.run_label.setText(f"<b style='color:{color}'>{word}</b> {seq.title}{msg}")
        else:
            self.run_label.setText("Nothing running.")

    # --- preview ------------------------------------------------------------------------------
    def _set_preview(self, mode: str) -> None:
        self.preview_mode = mode
        if mode == "vuv":
            if self.snapshot_view is not None:  # a new measurement: a new plot
                self.snapshot_holder.removeWidget(self.snapshot_view)
                self.snapshot_view.deleteLater()
                self.snapshot_view = None
            self.preview_stack.setCurrentWidget(self.snapshot_page)
        elif mode == "camera":
            if self.live_view is None:
                from ..laserdaq.config import AppConfig
                from ..laserdaq.gui.live_view import LiveView
                self.live_view = LiveView(AppConfig())
                self.camera_holder.addWidget(self.live_view)
            self.preview_stack.setCurrentWidget(self.camera_page)

    def _close_preview(self) -> None:
        self.preview_mode = ""
        if self.snapshot_view is not None:
            self.snapshot_holder.removeWidget(self.snapshot_view)
            self.snapshot_view.deleteLater()
            self.snapshot_view = None
        self.preview_stack.setCurrentIndex(0)

    def _on_vuv_items(self, items: list[dict[str, Any]]) -> None:
        if self.preview_mode != "vuv":
            return
        if self.snapshot_view is None:
            session = self.ctx.vuv.session
            name, dcfg = next(iter(session.configs.items()))
            shown = shown_channels(dcfg)
            labels = dict(zip(dcfg["channels"], dcfg["channel_name"], strict=True))
            self.snapshot_view = SnapshotView(
                shown, [labels[c] for c in shown], device=name,
                signal_channel=dcfg.get("snapshot_channel", dcfg["channels"][0]),
                snapshot_dir=os.path.join(session.data_path(dcfg), "snapshots"),
                n_avg=default_n(dcfg.get("refresh_trigger_cnt")))
            # a shifter only looks: no Average / Clear / Freeze / Save row (user 2026-11-24)
            self.snapshot_view.controls_bar.hide()
            self.snapshot_holder.addWidget(self.snapshot_view)
        self.snapshot_view.show_items(items)

    def _on_frame(self, frame: Any) -> None:
        if self.preview_mode == "camera" and self.live_view is not None and self.isVisible():
            self.live_view.update_frame(frame)

    # --- NO cell monitor ----------------------------------------------------------------------
    def _monitor_channels(self) -> tuple[list[str], list[TrendSource], list[str]]:
        """(channels shown, their CSV history, digitizers that have them)."""
        session = self.ctx.monitor.session
        want = self.ctx.settings.monitor_channels
        channels, sources, scopes = [], [], []
        for name, dcfg in session.configs.items():
            mine = [c for c in shown_channel_names(dcfg) if c in want]
            if mine:
                channels += mine
                scopes.append(name)
                sources.append(TrendSource(os.path.join(session.data_path(dcfg), "csv"),
                                           dcfg["output_name"], tuple(mine)))
        return channels, sources, scopes

    def _refresh_monitor(self) -> None:
        mon = self.ctx.monitor
        running = mon is not None and mon.session is not None and mon.running
        if running and self.monitor_view is None:
            channels, sources, _ = self._monitor_channels()
            if channels:
                self.monitor_view = ContinuousView(channels, [channels], history_sources=sources,
                                                   window=mon.trend_window)
                self.monitor_holder.addWidget(self.monitor_view)
                self.monitor_stack.setCurrentWidget(self.monitor_page)
            else:
                self.monitor_idle_label.setText(
                    "The scope monitor runs, but its config has no channel "
                    + ", ".join(self.ctx.settings.monitor_channels) + ".")
        elif not running and self.monitor_view is not None:
            self.monitor_holder.removeWidget(self.monitor_view)
            self.monitor_view.deleteLater()
            self.monitor_view = None
            self.monitor_stack.setCurrentIndex(0)
        if self.monitor_view is not None:
            _, _, scopes = self._monitor_channels()
            s = mon.session
            self.monitor_view.set_rates({n: s.rates.get(n) if s.states.get(n) == "running"
                                         else None for n in scopes})
        elif not running:
            self.monitor_idle_label.setText(
                "The NO cell monitor is <b>not running</b> (DAQ › Scope monitor)."
                if mon is not None else "No scope monitor is configured.")
            self.monitor_start_btn.setVisible(mon is not None)
            self.monitor_start_btn.setEnabled(mon is not None and mon.session is not None
                                              and not mon.locked)

    def _on_monitor_items(self, items: list[dict[str, Any]]) -> None:
        if self.monitor_view is not None:
            self.monitor_view.show_items(items)

    # --- status -------------------------------------------------------------------------------
    def _refresh(self) -> None:
        self.items = items = operating_state(self.ctx)
        self._render_status(items)
        self._refresh_monitor()
        running = self.runner.running
        for key, box in self.boxes.items():
            problems = blocking(items, key)
            box.start_btn.setEnabled(not running and not problems and box.combo.count() > 0)
            box.combo.setEnabled(not running)
            if running:
                box.problem_label.setText("")
            elif problems:
                box.problem_label.setText("Not ready: " + "; ".join(
                    f"{p.name} {p.text}" for p in problems))
            elif box.combo.count() == 0:
                box.problem_label.setText("No config file found.")
            else:
                box.problem_label.setText("")
            box.problem_label.setVisible(bool(box.problem_label.text()))
            if not (running and self.runner.sequence is box.sequence):
                box.estimate_label.setText(
                    f"Takes {duration_text(box.sequence.estimate_s(self.ctx))}; blocks the laser "
                    "beam.")
                if self.runner.sequence is not box.sequence or not self.runner.records:
                    box.steps_label.setText(steps_html(box.sequence, None))
        self.stop_btn.setEnabled(running and not self.runner.stopping)
        self.return_btn.setEnabled(not running)
        self._render_run_label()
        self._emit_tab_state()

    def _render_status(self, items: list[Any]) -> None:
        bad = [i for i in items if not i.ok]
        if self.runner.running:
            self.overall_label.setText(f"<b style='font-size:14pt; color:{C.BLUE}'>●</b> "
                                       f"<b style='font-size:14pt'>Measurement running</b>")
        elif not bad:
            self.overall_label.setText(f"<b style='font-size:14pt; color:{C.GREEN}'>●</b> "
                                       f"<b style='font-size:14pt'>Operating state: OK</b>")
        else:
            names = ", ".join(i.name for i in bad)
            self.overall_label.setText(
                f"<b style='font-size:14pt; color:{C.ORANGE}'>●</b> "
                f"<b style='font-size:14pt'>Operating state: not OK</b>"
                f"<span style='color:{C.ORANGE}'> — ⚠ {html.escape(names)}</span>")
        for row, item in enumerate(items):
            labels = self.status_rows.get(item.name)
            if labels is None:
                labels = (QLabel(), QLabel(item.name), QLabel())
                labels[2].setWordWrap(True)
                for col, lbl in enumerate(labels):
                    self.status_grid.addWidget(lbl, row, col)
                self.status_grid.setColumnStretch(2, 1)
                self.status_rows[item.name] = labels
            color = C.GREEN if item.ok else C.ORANGE
            labels[0].setText(f"<b style='color:{color}'>●</b>")
            labels[2].setText(item.text)

    def _emit_tab_state(self) -> None:
        if self.runner.running:
            state = "busy"
        elif self.runner.outcome == FAILED:
            state = "error"
        elif all(i.ok for i in self.items):
            state = "ok"
        else:
            state = "off"
        if state != self._last_tab_state:
            self._last_tab_state = state
            self.tab_state_changed.emit(state)

    @property
    def running(self) -> bool:
        return self.runner.running

    def shutdown(self) -> None:
        self.timer.stop()
        if self.runner.running:
            self.runner.stop()
