"""PicoScope plot views, ported from H2LaserDAQ `src/H2LaserMonitorApp.py`.

`ContinuousView` = the old continuous monitor window (signal trends + live averaged waveforms);
`SnapshotView` = the old snapshot window (averaged waveforms + area statistics, Freeze / Save).
They are plain widgets now: the tab feeds them the data items (`show_items`) instead of each
window polling its own queue. Layout and mouse controls are unchanged (left drag = zoom box,
right drag = pan, wheel = zoom; +/- step the Y range). Colours: light theme matching the rest
of the program (user 2026-11-18; the old windows were dark).
Changes (user 2026-11-18): trigger channels are not shown (the tab passes only the others; the
files still contain them); the status row shows each scope's trigger rate instead; the monitor
trend has a selectable time window (10 min ... 14 days) filled from the daily CSV files.
The snapshot view averages like an oscilloscope: every waveform arrives, the last N (1 … 1024,
∞) are averaged and redrawn at up to the trigger rate; statistics box with offset, area
(offset subtracted), std, N, stderr; Clear restarts the average.
Removed: the snapshot window's own Pause button (the tab's Pause stops the acquisition and the
display freezes with it, user 2026-11-18) and the Ctrl+C handler (no terminal).
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ...daq.picoscope.averaging import N_CHOICES, WaveAverager, n_label
from ...daq.picoscope.history import DEFAULT_WINDOW, WINDOWS, TrendSource, load_history

_BG = "#ffffff"  # plot background
_FG = "#212121"  # text, axes
_SURF = "#e6e6e6"  # panel titles / statistics labels
_GRID = "#c8c8c8"  # separators
_MATH = "#8d6e00"  # Freeze "Math" value (dark amber, readable on light grey)
# channel colours readable on white (same family as the program's status colours)
_CH_COLOURS = ["#1565c0", "#2e7d32", "#e65100", "#c62828", "#6a1b9a", "#00838f", "#6d4c41",
               "#ad1457"]

VIEW_STYLE = f"""
    QLabel#panelTitle     {{ font-weight: bold; padding: 4px 8px;
                            background: {_SURF}; border-radius: 4px; }}
    QLabel#statsLabel     {{ padding: 2px 10px; background: {_SURF}; border-radius: 4px; }}
    QWidget#statusRow     {{ background: {_SURF}; border-top: 1px solid {_GRID}; }}
    QSplitter::handle     {{ background: {_GRID}; width: 3px; }}
    QFrame#statsSep       {{ color: {_GRID}; }}
    QWidget#scopeView QPushButton {{ font-weight: bold; padding: 0px; }}
"""


def _style_plot(p: pg.PlotItem) -> None:
    """Dark axes and tick labels on the white plot (pyqtgraph defaults are for black)."""
    for name in ("left", "bottom"):
        ax = p.getAxis(name)
        ax.setPen(pg.mkPen(_FG))
        ax.setTextPen(pg.mkPen(_FG))


def _colour(i: int) -> str:
    return _CH_COLOURS[i % len(_CH_COLOURS)]


def _rate_text(rates: dict[str, float | None]) -> str:
    """Status-row text: trigger rate per scope (posted every 5 s by the digitizers)."""
    parts = [f"{name} {'—' if hz is None else f'{hz:.1f} Hz'}" for name, hz in rates.items()]
    return "  Trigger rate: " + ("  ·  ".join(parts) if parts else "—") + "  "


# Signed range list. Positive value -> signal points up; negative -> down.
_SIGNED_RANGES = [
    -5.0, -2.0, -1.0, -0.5, -0.2, -0.1, -0.05, -0.02, -0.01,
    0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0,
]
_V_RANGES = [0.010, 0.020, 0.050, 0.100, 0.200, 0.500, 1.0, 2.0, 5.0]


def _yrange_from_signed(rv: float) -> tuple[float, float]:
    """(ymin, ymax) in volts, with a 10 % margin on the opposite-polarity side."""
    margin = abs(rv) * 0.10
    return (-margin, rv) if rv > 0 else (rv, margin)


def _pick_range_idx(wfm_v: np.ndarray) -> int:
    """Index into _SIGNED_RANGES that best fits the waveform."""
    peak = float(np.max(np.abs(wfm_v)))
    if peak == 0.0:
        return _SIGNED_RANGES.index(0.01)
    r = _V_RANGES[-1]
    for candidate in _V_RANGES:
        if candidate >= peak:
            r = candidate
            break
    signed_r = r if abs(float(np.max(wfm_v))) >= abs(float(np.min(wfm_v))) else -r
    return _SIGNED_RANGES.index(signed_r)


def _fmt_range(rv: float) -> str:
    sign = "−" if rv < 0 else ""
    r = abs(rv)
    if r < 1.0:
        return f"{sign}{round(r * 1000)} mV"
    return f"{sign}{int(r)} V"


class _ZoomPanViewBox(pg.ViewBox):
    """Left drag = rect zoom, right drag = pan, wheel = zoom on the axis under the cursor."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setMouseMode(pg.ViewBox.RectMode)

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == QtCore.Qt.MouseButton.RightButton:
            ev.accept()
            dif = pg.Point(ev.screenPos() - ev.lastScreenPos())
            mask = np.array(self.state["mouseEnabled"], dtype=float)
            tr = pg.functions.invertQTransform(self.childGroup.transform())
            tr = tr.map(dif * mask) - tr.map(pg.Point(0, 0))
            x = -tr.x() if mask[0] else None
            y = -tr.y() if mask[1] else None
            self._resetTarget()
            if x is not None or y is not None:
                self.translateBy(x=x, y=y)
            self.sigRangeChangedManually.emit(self.state["mouseEnabled"])
        else:
            super().mouseDragEvent(ev, axis)


def _vline() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setObjectName("statsSep")
    f.setFrameShape(QtWidgets.QFrame.Shape.VLine)
    f.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return f


class _RangeMixin:
    """+/- buttons stepping the Y range of one channel's waveform plot."""

    def _make_range_buttons(self, key: str, col: str) -> QtWidgets.QWidget:
        btn_panel = QtWidgets.QWidget()
        btn_panel.setFixedWidth(52)
        lay = QtWidgets.QVBoxLayout(btn_panel)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(2)
        plus = QtWidgets.QPushButton("+")
        plus.setFixedSize(44, 26)
        plus.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        label = QtWidgets.QLabel("—")
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {col}; font-size: 10px;")
        minus = QtWidgets.QPushButton("−")
        minus.setFixedSize(44, 26)
        minus.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        plus.clicked.connect(lambda _=False, c=key: self._step_range(c, +1))
        minus.clicked.connect(lambda _=False, c=key: self._step_range(c, -1))
        lay.addStretch()
        lay.addWidget(plus)
        lay.addWidget(label)
        lay.addWidget(minus)
        lay.addStretch()
        self._range_idx[key] = None
        self._range_labels[key] = label
        return btn_panel

    def _auto_range(self, key: str, wfm_v: np.ndarray) -> None:
        if self._range_idx[key] is None:
            idx = _pick_range_idx(wfm_v)
            self._range_idx[key] = idx
            self._wfm_plots[key].setYRange(*_yrange_from_signed(_SIGNED_RANGES[idx]), padding=0)
            self._wfm_plots[key].enableAutoRange(axis="y", enable=False)
            self._range_labels[key].setText(_fmt_range(_SIGNED_RANGES[idx]))

    def _step_range(self, key: str, direction: int) -> None:
        idx = self._range_idx.get(key)
        if idx is None:
            return  # auto-range not yet set
        new_idx = max(0, min(len(_SIGNED_RANGES) - 1, idx + direction))
        if new_idx == idx:
            return
        self._range_idx[key] = new_idx
        rv = _SIGNED_RANGES[new_idx]
        self._wfm_plots[key].setYRange(*_yrange_from_signed(rv), padding=0)
        self._range_labels[key].setText(_fmt_range(rv))


# ----------------------------------------------------------------------------------------------
# Continuous monitor
# ----------------------------------------------------------------------------------------------
class ContinuousView(QtWidgets.QWidget, _RangeMixin):
    """Trend of the summed area per channel (nV*s vs time) + averaged waveforms (V vs s).

    The trend shows the last `window` (drop-down, 10 min ... 14 days; the old window kept a fixed
    4000 points = ~4.4 h). On a window change the history is read from the daily CSV files
    (`history_sources`), then live points are appended. The x range follows the latest data
    until the user zooms / pans; "Latest" (or picking a window) follows again.
    Trigger channels are not passed in (not shown, user 2026-11-18); the trigger rate of each
    scope is in the status row (`set_rates`)."""

    def __init__(self, channels: list[str], channel_groups: list[list[str]] | None = None,
                 parent: QtWidgets.QWidget | None = None, *,
                 history_sources: list[TrendSource] | None = None,
                 window: str = DEFAULT_WINDOW) -> None:
        super().__init__(parent)
        self.setObjectName("scopeView")
        self.setStyleSheet(VIEW_STYLE)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.channels = channels
        channel_groups = channel_groups or [channels]
        self._group_of = {ch: g for g, grp in enumerate(channel_groups) for ch in grp}
        self._wfm_group_tail = {[c for c in grp if c in channels][-1]
                                for grp in channel_groups if any(c in channels for c in grp)}
        self._history_sources = history_sources or []
        self._windows = dict(WINDOWS)
        self.window = window if window in self._windows else DEFAULT_WINDOW
        self._ts: dict[str, list[float]] = {ch: [] for ch in channels}
        self._val: dict[str, list[float]] = {ch: [] for ch in channels}
        self._follow = True
        self._range_idx: dict[str, int | None] = {}
        self._range_labels: dict[str, QtWidgets.QLabel] = {}

        vlay = QtWidgets.QVBoxLayout(self)
        vlay.setContentsMargins(8, 8, 8, 4)
        vlay.setSpacing(4)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)
        vlay.addWidget(splitter, 1)
        trend_panel, self._trend_curves = self._make_trend_panel()
        wfm_panel, self._wfm_curves, self._wfm_plots = self._make_wfm_panel()
        splitter.addWidget(trend_panel)
        splitter.addWidget(wfm_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([900, 600])
        vlay.addWidget(self._build_status_row())
        self.load_history()

    def _make_trend_panel(self):
        panel = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        title = QtWidgets.QLabel("Signal Trends  (nV·s)")
        title.setObjectName("panelTitle")
        head.addWidget(title, 1)
        head.addWidget(QtWidgets.QLabel("Show last:"))
        self.window_combo = QtWidgets.QComboBox()
        for label, _ in WINDOWS:
            self.window_combo.addItem(label)
        self.window_combo.setCurrentText(self.window)
        self.window_combo.setToolTip("Time span of the trend plots. Older points are read from "
                                     "the daily CSV files in data/picoscope/csv.")
        self.window_combo.currentTextChanged.connect(self.set_window)
        head.addWidget(self.window_combo)
        self.latest_btn = QtWidgets.QPushButton("Latest")
        self.latest_btn.setToolTip("Follow the newest data again (after zooming or panning)")
        self.latest_btn.clicked.connect(self.follow_latest)
        self.latest_btn.setEnabled(False)
        head.addWidget(self.latest_btn)
        lay.addLayout(head)
        gw = pg.GraphicsLayoutWidget()
        gw.setBackground(_BG)
        lay.addWidget(gw)
        curves = {}
        self._trend_plots: list[pg.PlotItem] = []
        prev = None
        n = len(self.channels)
        for i, ch in enumerate(self.channels):
            col = _colour(i)
            p = gw.addPlot(row=i, col=0, axisItems={"bottom": pg.DateAxisItem(orientation="bottom")},
                           viewBox=_ZoomPanViewBox())
            _style_plot(p)
            p.setLabel("left", ch, units="nV·s", color=col, size="10pt")
            p.getAxis("left").enableAutoSIPrefix(False)  # compound unit: no "knV·s"
            p.showGrid(x=True, y=True, alpha=0.20)
            p.getAxis("left").setWidth(90)
            # up to 14 days = ~300k points per channel: draw only what is visible, decimated
            p.setDownsampling(auto=True, mode="peak")
            p.setClipToView(True)
            p.setAutoVisible(y=True)  # y auto-range over the visible time span only
            if i < n - 1:
                p.hideAxis("bottom")
            if prev is not None:
                p.setXLink(prev)
            p.getViewBox().sigRangeChangedManually.connect(self._on_manual_range)
            curves[ch] = p.plot(pen=pg.mkPen(col, width=2))
            gw.ci.layout.setRowStretchFactor(i, 1)
            self._trend_plots.append(p)
            prev = p
        return panel, curves

    # --- trend window / history ---------------------------------------------------------------
    @property
    def window_s(self) -> int:
        return self._windows[self.window]

    def set_window(self, label: str) -> None:
        if label not in self._windows:
            return
        self.window = label
        if self.window_combo.currentText() != label:
            self.window_combo.setCurrentText(label)
        self.load_history()
        self.follow_latest()

    def load_history(self) -> None:
        """Replace the trend data with the CSV history of the current window (the live points
        are in the CSV files too: one row is written and flushed per 100 triggers)."""
        hist = load_history(self._history_sources, self.window_s) if self._history_sources else {}
        for ch in self.channels:
            t, v = hist.get(ch, (np.empty(0), np.empty(0)))
            self._ts[ch] = t.tolist()
            self._val[ch] = v.tolist()
        self._redraw_trends()

    def follow_latest(self) -> None:
        self._follow = True
        self.latest_btn.setEnabled(False)
        self._apply_follow()

    def _on_manual_range(self, *_: Any) -> None:
        self._follow = False
        self.latest_btn.setEnabled(True)

    def _apply_follow(self) -> None:
        if self._follow and self._trend_plots:
            now = time.time()
            self._trend_plots[0].setXRange(now - self.window_s, now, padding=0.01)
            for p in self._trend_plots:
                p.enableAutoRange(axis="y", enable=True)

    def _trim(self) -> None:
        t0 = time.time() - self.window_s
        for ch in self.channels:
            ts = self._ts[ch]
            if ts and ts[0] < t0:
                k = int(np.searchsorted(np.asarray(ts), t0))
                del ts[:k]
                del self._val[ch][:k]

    def _redraw_trends(self, channels: set[str] | None = None) -> None:
        for ch in channels if channels is not None else self.channels:
            self._trend_curves[ch].setData(np.asarray(self._ts[ch]), np.asarray(self._val[ch]))
        self._apply_follow()

    def _make_wfm_panel(self):
        panel = QtWidgets.QWidget()
        vlay = QtWidgets.QVBoxLayout(panel)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(2)
        title = QtWidgets.QLabel("Live Waveforms")
        title.setObjectName("panelTitle")
        vlay.addWidget(title)
        curves, plots = {}, {}
        self._wfm_plots = plots
        prev_per_group: dict[int, Any] = {}
        for i, ch in enumerate(self.channels):
            col = _colour(i)
            g_idx = self._group_of.get(ch, 0)
            prev = prev_per_group.get(g_idx)
            row = QtWidgets.QWidget()
            row_lay = QtWidgets.QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(2)
            gw = pg.GraphicsLayoutWidget()
            gw.setBackground(_BG)
            p = gw.addPlot(row=0, col=0, viewBox=_ZoomPanViewBox())
            _style_plot(p)
            p.setLabel("left", ch, units="V", color=col, size="10pt")
            p.showGrid(x=True, y=True, alpha=0.20)
            p.getAxis("left").setWidth(75)
            if ch in self._wfm_group_tail:
                p.setLabel("bottom", "Time", units="s")
            else:
                p.hideAxis("bottom")
            if prev is not None:
                p.setXLink(prev)  # X linked only within one digitizer
            plots[ch] = p
            row_lay.addWidget(gw, stretch=1)
            row_lay.addWidget(self._make_range_buttons(ch, col))
            vlay.addWidget(row, stretch=1)
            curves[ch] = p.plot(pen=pg.mkPen(col, width=1.5))
            prev_per_group[g_idx] = p
        return panel, curves, plots

    def _build_status_row(self) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        row.setObjectName("statusRow")
        row.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(0)
        self._lbl_time = QtWidgets.QLabel("  Waiting for data…")
        self._lbl_time.setFixedWidth(230)
        lay.addWidget(self._lbl_time)
        self._ch_labels: dict[str, QtWidgets.QLabel] = {}
        for i, ch in enumerate(self.channels):
            lay.addWidget(_vline())
            lbl = QtWidgets.QLabel(f"  {ch}: —  ")
            lbl.setStyleSheet(f"color: {_colour(i)}; font-weight: bold;")
            lay.addWidget(lbl)
            self._ch_labels[ch] = lbl
        lay.addStretch()
        lay.addWidget(_vline())
        self._lbl_rate = QtWidgets.QLabel("  Trigger rate: —  ")
        lay.addWidget(self._lbl_rate)
        return row

    def set_rates(self, rates: dict[str, float | None]) -> None:
        self._lbl_rate.setText(_rate_text(rates))

    def show_items(self, items: list[dict[str, Any]]) -> None:
        changed = set()
        for item in items:
            ch = item.get("channel_name")
            if ch not in self.channels:
                continue  # e.g. the trigger channel: recorded, not shown
            ts = self._ts[ch]
            if ts and item["timestamp"] <= ts[-1]:
                pass  # already read from the CSV file (history loaded after it was written)
            else:
                ts.append(item["timestamp"])
                self._val[ch].append(item["value"])
            wfm_v = np.asarray(item["wfm"]) * 1e-3  # mV -> V
            self._wfm_curves[ch].setData(np.asarray(item["wfm_t"]) * 1e-9, wfm_v)  # ns -> s
            self._auto_range(ch, wfm_v)
            self._ch_labels[ch].setText(f"  {ch}: {item['value']:.4g}  ")
            changed.add(ch)
        if changed:
            self._trim()
            self._redraw_trends(changed)
            self._lbl_time.setText(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")

    @property
    def n_points(self) -> dict[str, int]:
        return {ch: len(v) for ch, v in self._val.items()}


# ----------------------------------------------------------------------------------------------
# Snapshot monitor
# ----------------------------------------------------------------------------------------------
class SnapshotView(QtWidgets.QWidget, _RangeMixin):
    """Averaged waveforms like an oscilloscope (user 2026-11-18).

    The scope sends every waveform; the plot shows the average of the last N (▲ / ▼: 1, 2, 4 …
    1024, ∞ = all since Clear) and is redrawn whenever new waveforms arrived (the tab polls every
    40 ms: up to 25 fps at 25 Hz triggers). A statistics box on the signal plot shows offset
    (first 5 % of the points), area (offset subtracted), std, N and stderr of the waveforms in
    the average. Clear restarts the average. Freeze keeps the current average as a dashed
    reference (Math = area difference); Save writes the old snapshot CSV."""

    saved = QtCore.Signal(str)

    def __init__(self, channels: list[str], channel_labels: list[str], device: str,
                 signal_channel: str, snapshot_dir: str,
                 parent: QtWidgets.QWidget | None = None, *, n_avg: int | None = 128) -> None:
        super().__init__(parent)
        self.setObjectName("scopeView")
        self.setStyleSheet(VIEW_STYLE)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.channels = channels
        self.channel_labels = channel_labels
        self.device = device
        self.snapshot_dir = snapshot_dir
        self._signal_ch = signal_channel if signal_channel in channels else channels[0]
        self.averager = WaveAverager(n_avg if n_avg in N_CHOICES else 128, self._signal_ch)
        self._t: np.ndarray | None = None
        self.frames = 0  # redraws (for tests)
        self._frozen_area: float | None = None
        self._range_idx: dict[str, int | None] = {}
        self._range_labels: dict[str, QtWidgets.QLabel] = {}
        self._frozen_curves: dict[str, Any] = {}

        vlay = QtWidgets.QVBoxLayout(self)
        vlay.setContentsMargins(8, 8, 8, 4)
        vlay.setSpacing(4)
        panel, self._wfm_curves, self._wfm_plots = self._make_wfm_panel()
        vlay.addWidget(panel, stretch=1)
        vlay.addWidget(self._make_stats_bar())
        status = QtWidgets.QWidget()
        status.setObjectName("statusRow")
        status.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        slay = QtWidgets.QHBoxLayout(status)
        slay.setContentsMargins(6, 2, 6, 2)
        self._lbl_time = QtWidgets.QLabel("  Waiting for data…")
        self._lbl_rate = QtWidgets.QLabel("  Trigger rate: —  ")
        slay.addWidget(self._lbl_rate)
        slay.addStretch()
        slay.addWidget(self._lbl_time)
        vlay.addWidget(status)
        self._update_stats_box()

    def set_rates(self, rates: dict[str, float | None]) -> None:
        self._lbl_rate.setText(_rate_text(rates))

    def _make_wfm_panel(self):
        panel = QtWidgets.QWidget()
        vlay = QtWidgets.QVBoxLayout(panel)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(2)
        title = QtWidgets.QLabel("Averaged Waveforms")
        title.setObjectName("panelTitle")
        vlay.addWidget(title)
        curves, plots = {}, {}
        self._wfm_plots = plots
        prev = None
        n = len(self.channels)
        for i, (ch, label) in enumerate(zip(self.channels, self.channel_labels, strict=True)):
            col = _colour(i)
            row = QtWidgets.QWidget()
            row_lay = QtWidgets.QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(2)
            gw = pg.GraphicsLayoutWidget()
            gw.setBackground(_BG)
            p = gw.addPlot(row=0, col=0, viewBox=_ZoomPanViewBox())
            _style_plot(p)
            p.setLabel("left", label, units="V", color=col, size="10pt")
            p.showGrid(x=True, y=True, alpha=0.20)
            p.getAxis("left").setWidth(75)
            if i < n - 1:
                p.hideAxis("bottom")
            else:
                p.setLabel("bottom", "Time", units="s")
            if prev is not None:
                p.setXLink(prev)
            plots[ch] = p
            row_lay.addWidget(gw, stretch=1)
            row_lay.addWidget(self._make_range_buttons(ch, col))
            vlay.addWidget(row, stretch=1)
            curves[ch] = p.plot(pen=pg.mkPen(col, width=2))
            self._frozen_curves[ch] = p.plot(
                pen=pg.mkPen(col, width=1.5, style=QtCore.Qt.PenStyle.DashLine))
            if ch == self._signal_ch:
                self._make_stats_box(p)
            prev = p
        return panel, curves, plots

    def _make_stats_box(self, p: pg.PlotItem) -> None:
        """Statistics 'legend' in the top-right corner of the signal plot (fixed on screen)."""
        vb = p.getViewBox()
        self._stats_box = pg.TextItem(anchor=(1, 0), fill=pg.mkBrush(255, 255, 255, 225),
                                      border=pg.mkPen(_GRID))
        self._stats_box.setParentItem(vb)

        def place() -> None:
            self._stats_box.setPos(vb.width() - 8, 8)

        vb.sigResized.connect(place)
        place()

    def _make_stats_bar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(40)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(4)
        self._lbl_device = QtWidgets.QLabel(f"  Device: {self.device}")
        self._lbl_device.setObjectName("statsLabel")
        avg_lbl = QtWidgets.QLabel("  Average:")
        self._n_down = QtWidgets.QToolButton()
        self._n_down.setArrowType(QtCore.Qt.ArrowType.DownArrow)
        self._n_down.setToolTip("Average fewer waveforms")
        self._n_down.clicked.connect(lambda: self.step_n(-1))
        self._lbl_navg = QtWidgets.QLabel()
        self._lbl_navg.setObjectName("statsLabel")
        self._lbl_navg.setMinimumWidth(56)
        self._lbl_navg.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._n_up = QtWidgets.QToolButton()
        self._n_up.setArrowType(QtCore.Qt.ArrowType.UpArrow)
        self._n_up.setToolTip("Average more waveforms (… 1024, then ∞ = all since Clear)")
        self._n_up.clicked.connect(lambda: self.step_n(+1))
        self._clear_btn = QtWidgets.QPushButton("Clear")
        self._clear_btn.setFixedSize(60, 28)
        self._clear_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._clear_btn.setToolTip("Clear the averaged waveform and the statistics; restart")
        self._clear_btn.clicked.connect(self.clear)
        self._freeze_btn = QtWidgets.QPushButton("Freeze")
        self._freeze_btn.setFixedSize(72, 28)
        self._freeze_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._freeze_btn.setToolTip("Keep the current signal waveform as a dashed reference")
        self._freeze_btn.clicked.connect(self._on_freeze)
        self._lbl_math = QtWidgets.QLabel("")
        self._lbl_math.setObjectName("statsLabel")
        self._lbl_math.setStyleSheet(
            f"color: {_MATH}; font-weight: bold;"
            f"padding: 2px 10px; background: {_SURF}; border-radius: 4px;")
        self._save_btn = QtWidgets.QPushButton("Save")
        self._save_btn.setFixedSize(60, 28)
        self._save_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._save_btn.setToolTip("Save the signal waveform to data/picoscope/snapshots")
        self._save_btn.clicked.connect(self._on_save)
        for w in (self._lbl_device, _vline(), avg_lbl, self._n_down, self._lbl_navg, self._n_up,
                  self._clear_btn, _vline(), self._freeze_btn, self._lbl_math):
            lay.addWidget(w)
        lay.addStretch()
        lay.addWidget(self._save_btn)
        self._update_n_label()
        return bar

    # --- averaging ----------------------------------------------------------------------------
    @property
    def n_avg(self) -> int | None:
        return self.averager.n

    def set_n(self, n: int | None) -> None:
        if n not in N_CHOICES:
            return
        self.averager.set_n(n)  # restarts the average
        self._update_n_label()
        self._redraw()

    def step_n(self, direction: int) -> None:
        i = N_CHOICES.index(self.averager.n) + direction
        if 0 <= i < len(N_CHOICES):
            self.set_n(N_CHOICES[i])

    def clear(self) -> None:
        self.averager.clear()
        self._redraw()

    def _update_n_label(self) -> None:
        n = self.averager.n
        self._lbl_navg.setText(n_label(n))
        self._n_down.setEnabled(N_CHOICES.index(n) > 0)
        self._n_up.setEnabled(N_CHOICES.index(n) < len(N_CHOICES) - 1)

    def _update_stats_box(self) -> None:
        if not hasattr(self, "_stats_box"):
            return
        st = self.averager.stats()
        col = _colour(self.channels.index(self._signal_ch))
        if st is None:
            rows = [("Offset", "—"), ("Area", "—"), ("Std", "—"), ("N", "0"), ("Stderr", "—")]
        else:
            target = "" if self.averager.n is None else f" / {self.averager.n}"
            rows = [("Offset", f"{st.offset_mv:.4g} mV"), ("Area", f"{st.area:.4g} nV·s"),
                    ("Std", f"{st.std:.3g} nV·s"),
                    ("N", f"{st.n}{target}" if self.averager.n is not None else f"{st.n} (∞)"),
                    ("Stderr", f"{st.stderr:.3g} nV·s")]
        # large print: read from a distance while aligning (user 2026-11-18)
        html = "".join(f"<tr><td style='padding:2px 6px'>{k}</td>"
                       f"<td align='right' style='padding:2px 6px'><b>{v}</b></td></tr>"
                       for k, v in rows)
        self._stats_box.setHtml(
            f"<div style='color:{_FG}; font-size:16pt'><b style='color:{col}'>"
            f"&nbsp;{self.channel_labels[self.channels.index(self._signal_ch)]}</b>"
            f"<table cellspacing='0'>{html}</table></div>")

    def _redraw(self) -> None:
        means = self.averager.mean_waves()
        for ch in self.channels:
            if ch in means and self._t is not None:
                wfm_v = means[ch] * 1e-3  # mV -> V
                self._wfm_curves[ch].setData(self._t, wfm_v)
                self._auto_range(ch, wfm_v)
            else:
                self._wfm_curves[ch].setData([], [])
        self._update_stats_box()
        st = self.averager.stats()
        if self._frozen_area is not None and st is not None:
            self._lbl_math.setText(f"  Math: {st.area - self._frozen_area:+.4g}  nV·s")
        self.frames += 1

    # --- freeze / math / save -----------------------------------------------------------------
    def _on_freeze(self) -> None:
        if self._frozen_area is None:
            st = self.averager.stats()
            wfm = self.averager.mean_waves().get(self._signal_ch)
            if st is None or wfm is None or self._t is None:
                return
            self._frozen_curves[self._signal_ch].setData(self._t, wfm * 1e-3)
            self._frozen_area = st.area
            self._freeze_btn.setText("Unfreeze")
            self._lbl_math.setText(f"  Math: {0.0:+.4g}  nV·s")
        else:
            self._frozen_curves[self._signal_ch].setData([], [])
            self._frozen_area = None
            self._freeze_btn.setText("Freeze")
            self._lbl_math.setText("")

    def save_snapshot(self) -> str | None:
        """Write the averaged signal waveform (+ frozen reference) as the old snapshot CSV, with
        one extra comment line for the offset. Returns the path."""
        st = self.averager.stats()
        wfm = self.averager.mean_waves().get(self._signal_ch)
        if st is None or wfm is None or self._t is None:
            return None
        ch = self._signal_ch
        t_s = self._t
        live_v = wfm * 1e-3
        try:
            ch_label = self.channel_labels[self.channels.index(ch)]
        except ValueError:
            ch_label = ch
        frozen_t, frozen_v = self._frozen_curves[ch].getData()
        has_frozen = frozen_t is not None and len(frozen_t) > 0

        os.makedirs(self.snapshot_dir, exist_ok=True)
        dev_tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.device).strip("_")
        dev_tag = dev_tag or "unknown"
        prefix = f"snapshot_{dev_tag}_{datetime.now().strftime('%Y%m%d')}_"
        nums = []
        for f in os.listdir(self.snapshot_dir):
            if f.startswith(prefix) and f.endswith(".csv"):
                try:
                    nums.append(int(f[len(prefix):-4]))
                except ValueError:
                    pass
        seq = (max(nums) + 1) if nums else 1
        fname = os.path.join(self.snapshot_dir, f"{prefix}{seq:03d}.csv")
        with open(fname, "w", encoding="utf-8", newline="") as fp:
            fp.write("# H2LaserDAQ Snapshot\n")
            fp.write(f"# Saved   : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n")
            fp.write(f"# Device  : {self.device}\n")
            fp.write(f"# Channel : {ch} ({ch_label})\n")
            fp.write(f"# Area (live)  : {st.area:.6g} ± {st.stderr:.4g}  nV·s"
                     f"  (N = {st.n} triggers)\n")
            fp.write(f"# Offset       : {st.offset_mv:.6g}  mV  (mean of the first 5 % of the "
                     f"points, subtracted from the area; std {st.std:.4g} nV·s)\n")
            if has_frozen:
                fp.write(f"# Area (frozen): {self._frozen_area:.6g}  nV·s\n")
                fp.write(f"# Area (Math)  : {st.area - self._frozen_area:+.6g}  nV·s\n")
            fp.write("#\n")
            if has_frozen:
                fp.write("time_s,live_V,frozen_V\n")
                frozen_i = np.interp(t_s, frozen_t, frozen_v, left=np.nan, right=np.nan)
                fp.writelines(f"{ts:.6e},{lv:.6e},{fv:.6e}\n"
                              for ts, lv, fv in zip(t_s, live_v, frozen_i, strict=True))
            else:
                fp.write("time_s,live_V\n")
                fp.writelines(f"{ts:.6e},{lv:.6e}\n" for ts, lv in zip(t_s, live_v, strict=True))
        return fname

    def _on_save(self) -> None:
        fname = self.save_snapshot()
        if fname is None:
            return
        orig = self._lbl_time.text()
        self._lbl_time.setText(f"  Saved: {os.path.basename(fname)}")
        # context object: the timer is dropped if the label is deleted first (window closed)
        QtCore.QTimer.singleShot(3000, self._lbl_time, lambda: self._lbl_time.setText(orig))
        self.saved.emit(fname)

    # --- data ---------------------------------------------------------------------------------
    def show_items(self, items: list[dict[str, Any]]) -> None:
        """Every item = one waveform: {'t': ns, 'dt': ns, 'Ch<x>': mV, ...}. All are averaged;
        the plot is redrawn once per call (one call per tab poll)."""
        got = False
        for item in items:
            t = item.get("t")
            waves = {ch: item[f"Ch{ch}"] for ch in self.channels if f"Ch{ch}" in item}
            if t is None or self._signal_ch not in waves:
                continue
            self._t = np.asarray(t) * 1e-9  # ns -> s
            self.averager.add(waves, float(item.get("dt") or (t[1] - t[0])))
            got = True
        if got:
            self._redraw()
            self._lbl_time.setText(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}  ")
