"""PicoScope plot views, ported from H2LaserDAQ `src/H2LaserMonitorApp.py`.

`ContinuousView` = the old continuous monitor window (signal trends + live averaged waveforms);
`SnapshotView` = the old snapshot window (averaged waveforms + area statistics, Freeze / Save).
They are plain widgets now: the tab feeds them the data items (`show_items`) instead of each
window polling its own queue. Look and mouse controls are unchanged (dark Catppuccin palette,
left drag = zoom box, right drag = pan, wheel = zoom; +/- step the Y range).
Removed: the snapshot window's own Pause button (the tab's Pause stops the acquisition and the
display freezes with it, user 2026-11-18) and the Ctrl+C handler (no terminal).
"""

from __future__ import annotations

import math
import os
from collections import deque
from datetime import datetime
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

_BG = "#1e1e2e"  # window / plot background
_FG = "#cdd6f4"  # default text
_SURF = "#313244"  # panel header background
_GRID = "#45475a"  # grid line colour
_CH_COLOURS = ["#a6e3a1", "#89b4fa", "#fab387", "#f38ba8", "#cba6f7", "#89dceb", "#f9e2af",
               "#94e2d5"]

DARK_STYLE = f"""
    QWidget#scopeView, QWidget#scopeView QWidget {{ background: {_BG}; color: {_FG};
                            font-family: Menlo, Consolas, monospace; font-size: 12px; }}
    QLabel#panelTitle     {{ font-size: 13px; font-weight: bold; padding: 4px 8px;
                            background: {_SURF}; border-radius: 4px; }}
    QLabel#statsLabel     {{ font-size: 12px; padding: 2px 10px; background: {_SURF};
                            border-radius: 4px; }}
    QWidget#statusRow     {{ background: {_SURF}; border-top: 1px solid {_GRID}; }}
    QSplitter::handle     {{ background: {_GRID}; width: 3px; }}
    QFrame#statsSep       {{ color: {_GRID}; }}
    QWidget#scopeView QPushButton {{ background: {_SURF}; color: {_FG};
                            border: 1px solid {_GRID}; border-radius: 4px;
                            font-size: 15px; font-weight: bold; padding: 0px; }}
    QWidget#scopeView QPushButton:hover   {{ background: {_GRID}; }}
    QWidget#scopeView QPushButton:pressed {{ background: #585b70; }}
"""


def _colour(i: int) -> str:
    return _CH_COLOURS[i % len(_CH_COLOURS)]


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
    """Trend of the summed area per channel (nV*s vs time) + averaged waveforms (V vs s)."""

    _BUFFER = 4000  # trend points kept per channel

    def __init__(self, channels: list[str], channel_groups: list[list[str]] | None = None,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("scopeView")
        self.setStyleSheet(DARK_STYLE)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.channels = channels
        channel_groups = channel_groups or [channels]
        self._group_of = {ch: g for g, grp in enumerate(channel_groups) for ch in grp}
        self._wfm_group_tail = {[c for c in grp if c in channels][-1]
                                for grp in channel_groups if any(c in channels for c in grp)}
        self._ts = {ch: deque(maxlen=self._BUFFER) for ch in channels}
        self._val = {ch: deque(maxlen=self._BUFFER) for ch in channels}
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

    def _make_trend_panel(self):
        panel = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        title = QtWidgets.QLabel("Signal Trends  (nV·s)")
        title.setObjectName("panelTitle")
        lay.addWidget(title)
        gw = pg.GraphicsLayoutWidget()
        gw.setBackground(_BG)
        lay.addWidget(gw)
        curves = {}
        prev = None
        n = len(self.channels)
        for i, ch in enumerate(self.channels):
            col = _colour(i)
            p = gw.addPlot(row=i, col=0, axisItems={"bottom": pg.DateAxisItem(orientation="bottom")},
                           viewBox=_ZoomPanViewBox())
            p.setLabel("left", ch, units="nV·s", color=col, size="10pt")
            p.getAxis("left").enableAutoSIPrefix(False)  # compound unit: no "knV·s"
            p.showGrid(x=True, y=True, alpha=0.20)
            p.getAxis("left").setWidth(90)
            if i < n - 1:
                p.hideAxis("bottom")
            if prev is not None:
                p.setXLink(prev)
            curves[ch] = p.plot(pen=pg.mkPen(col, width=2))
            gw.ci.layout.setRowStretchFactor(i, 1)
            prev = p
        return panel, curves

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
        return row

    def show_items(self, items: list[dict[str, Any]]) -> None:
        changed = set()
        for item in items:
            ch = item.get("channel_name")
            if ch not in self.channels:
                continue
            self._ts[ch].append(item["timestamp"])
            self._val[ch].append(item["value"])
            wfm_v = np.asarray(item["wfm"]) * 1e-3  # mV -> V
            self._wfm_curves[ch].setData(np.asarray(item["wfm_t"]) * 1e-9, wfm_v)  # ns -> s
            self._auto_range(ch, wfm_v)
            self._ch_labels[ch].setText(f"  {ch}: {item['value']:.4g}  ")
            changed.add(ch)
        for ch in changed:
            self._trend_curves[ch].setData(np.array(self._ts[ch]), np.array(self._val[ch]))
        if changed:
            self._lbl_time.setText(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")

    @property
    def n_points(self) -> dict[str, int]:
        return {ch: len(v) for ch, v in self._val.items()}


# ----------------------------------------------------------------------------------------------
# Snapshot monitor
# ----------------------------------------------------------------------------------------------
class SnapshotView(QtWidgets.QWidget, _RangeMixin):
    """Averaged waveform of each channel + area of the signal channel (mean ± error)."""

    def __init__(self, channels: list[str], channel_labels: list[str], device: str,
                 signal_channel: str, snapshot_dir: str,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("scopeView")
        self.setStyleSheet(DARK_STYLE)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.channels = channels
        self.channel_labels = channel_labels
        self.device = device
        self.snapshot_dir = snapshot_dir
        self._signal_ch = signal_channel or channels[0]
        self._last_item: dict[str, Any] | None = None
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
        slay.addStretch()
        slay.addWidget(self._lbl_time)
        vlay.addWidget(status)

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
            prev = p
        return panel, curves, plots

    def _make_stats_bar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(40)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(0)
        self._lbl_device = QtWidgets.QLabel(f"  Device: {self.device}")
        self._lbl_device.setObjectName("statsLabel")
        self._lbl_area = QtWidgets.QLabel("  Area: —")
        self._lbl_area.setObjectName("statsLabel")
        self._lbl_area.setStyleSheet(
            f"color: {_colour(0)}; font-weight: bold; font-size: 13px;"
            f"padding: 2px 10px; background: {_SURF}; border-radius: 4px;")
        self._lbl_n = QtWidgets.QLabel("  N: —")
        self._lbl_n.setObjectName("statsLabel")
        self._freeze_btn = QtWidgets.QPushButton("Freeze")
        self._freeze_btn.setFixedSize(72, 28)
        self._freeze_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._freeze_btn.setToolTip("Keep the current signal waveform as a dashed reference")
        self._freeze_btn.clicked.connect(self._on_freeze)
        self._lbl_math = QtWidgets.QLabel("")
        self._lbl_math.setObjectName("statsLabel")
        self._lbl_math.setStyleSheet(
            "color: #f9e2af; font-weight: bold; font-size: 13px;"
            f"padding: 2px 10px; background: {_SURF}; border-radius: 4px;")
        self._save_btn = QtWidgets.QPushButton("Save")
        self._save_btn.setFixedSize(60, 28)
        self._save_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._save_btn.setToolTip("Save the signal waveform to data/picoscope/snapshots")
        self._save_btn.clicked.connect(self._on_save)
        for w in (self._lbl_device, _vline(), self._lbl_area, _vline(), self._lbl_n, _vline(),
                  self._freeze_btn, _vline(), self._lbl_math):
            lay.addWidget(w)
        lay.addStretch()
        lay.addWidget(self._save_btn)
        return bar

    # --- freeze / math / save -----------------------------------------------------------------
    def _on_freeze(self) -> None:
        if self._frozen_area is None:
            if self._last_item is None:
                return
            item = self._last_item
            t = item.get("t")
            wfm = item.get(f"Ch{self._signal_ch}")
            if wfm is not None and t is not None:
                self._frozen_curves[self._signal_ch].setData(np.asarray(t) * 1e-9,
                                                             np.asarray(wfm) * 1e-3)
            self._frozen_area = item.get("area_avg", 0.0)
            self._freeze_btn.setText("Clear")
            self._lbl_math.setText("  Math: computing…")
        else:
            self._frozen_curves[self._signal_ch].setData([], [])
            self._frozen_area = None
            self._freeze_btn.setText("Freeze")
            self._lbl_math.setText("")

    def save_snapshot(self) -> str | None:
        """Write the signal waveform (+ frozen reference) as the old snapshot CSV. Returns path."""
        if self._last_item is None:
            return None
        item = self._last_item
        ch = self._signal_ch
        t_raw, wfm = item.get("t"), item.get(f"Ch{ch}")
        if t_raw is None or wfm is None:
            return None
        t_s = np.asarray(t_raw) * 1e-9
        live_v = np.asarray(wfm) * 1e-3
        area_avg = item.get("area_avg", 0.0)
        area_std = item.get("area_std", 0.0)
        n = item.get("trigger_cnt", 1)
        device = item.get("device", "—")
        stderr = area_std / math.sqrt(max(n, 1))
        try:
            ch_label = self.channel_labels[self.channels.index(ch)]
        except ValueError:
            ch_label = ch
        frozen_t, frozen_v = self._frozen_curves[ch].getData()
        has_frozen = frozen_t is not None and len(frozen_t) > 0

        os.makedirs(self.snapshot_dir, exist_ok=True)
        dev_tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in device).strip("_")
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
            fp.write(f"# Device  : {device}\n")
            fp.write(f"# Channel : {ch} ({ch_label})\n")
            fp.write(f"# Area (live)  : {area_avg:.6g} ± {stderr:.4g}  nV·s"
                     f"  (N = {n} triggers)\n")
            if has_frozen:
                fp.write(f"# Area (frozen): {self._frozen_area:.6g}  nV·s\n")
                fp.write(f"# Area (Math)  : {area_avg - self._frozen_area:+.6g}  nV·s\n")
            fp.write("#\n")
            if has_frozen:
                fp.write("time_s,live_V,frozen_V\n")
                frozen_i = np.interp(t_s, frozen_t, frozen_v, left=np.nan, right=np.nan)
                fp.writelines(f"{ts:.6e},{lv:.6e},{fv:.6e}\n" for ts, lv, fv in zip(t_s, live_v, frozen_i, strict=True))
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

    saved = QtCore.Signal(str)

    # --- data ---------------------------------------------------------------------------------
    def show_items(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        item = items[-1]  # keep only the latest packet
        self._last_item = item
        t = item.get("t")
        for ch in self.channels:
            wfm = item.get(f"Ch{ch}")
            if wfm is not None and t is not None:
                wfm_v = np.asarray(wfm) * 1e-3
                self._wfm_curves[ch].setData(np.asarray(t) * 1e-9, wfm_v)
                self._auto_range(ch, wfm_v)
        area_avg = item.get("area_avg", 0.0)
        n = item.get("trigger_cnt", 1)
        stderr = item.get("area_std", 0.0) / math.sqrt(max(n, 1))
        self._lbl_area.setText(f"  Peak area: {area_avg:.4g} ± {stderr:.3g}  nV·s")
        self._lbl_n.setText(f"  N = {n} triggers")
        self._lbl_time.setText(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}  ")
        if self._frozen_area is not None:
            self._lbl_math.setText(f"  Math: {area_avg - self._frozen_area:+.4g}  nV·s")
