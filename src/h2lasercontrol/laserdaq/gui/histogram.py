"""RGB histogram widget — three overlapping filled curves for R, G, B channels."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

_BIN_X = np.arange(256, dtype=np.float64)
_MAX_DIM = 512  # downsample threshold for fast histogram computation

# (inactive_bg, active_bg, inactive_fg, active_fg) per indicator
_SAT_STYLE: dict[str, tuple[str, str, str, str]] = {
    "R": ("#3a0808", "#ff3030", "white", "white"),
    "G": ("#083a08", "#30dd30", "white", "white"),
    "B": ("#08083a", "#3060ff", "white", "white"),
    "W": ("#1a1a1a", "#e8e8e8", "white", "#111111"),  # all-channel clip → near-white lamp
}

_SAT_TOOLTIP = {
    "R": "R channel clipped at 255",
    "G": "G channel clipped at 255",
    "B": "B channel clipped at 255",
    "W": "Pure-white pixel — all channels clipped at 255",
}


class RGBHistogramWidget(QWidget):
    """Compact Lightroom-style RGB histogram with per-channel saturation indicators."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot = pg.PlotWidget(background="k")
        layout.addWidget(self._plot, stretch=1)

        vb = self._plot.getViewBox()
        vb.setMouseEnabled(x=False, y=False)
        self._plot.setXRange(0, 256, padding=0)
        self._plot.enableAutoRange(axis="y")
        self._plot.hideButtons()

        for axis in ("left", "bottom"):
            self._plot.getAxis(axis).setStyle(showValues=False)

        self._curve_r = self._make_curve((220, 50, 50, 120))
        self._curve_g = self._make_curve((50, 200, 50, 120))
        self._curve_b = self._make_curve((50, 100, 220, 120))

        for curve in (self._curve_r, self._curve_g, self._curve_b):
            self._plot.addItem(curve)

        # Saturation indicator strip
        strip = QWidget()
        strip.setFixedHeight(16)
        strip.setStyleSheet("background: #111111;")
        row = QHBoxLayout(strip)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        self._sat_labels: dict[str, QLabel] = {}
        for ch in ("R", "G", "B", "W"):
            lbl = QLabel(ch)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(22, 12)
            lbl.setStyleSheet(self._sat_style(ch, active=False))
            lbl.setToolTip(_SAT_TOOLTIP[ch])
            row.addWidget(lbl)
            self._sat_labels[ch] = lbl

        row.addStretch()
        layout.addWidget(strip)

    @staticmethod
    def _make_curve(rgba: tuple) -> pg.PlotCurveItem:
        r, g, b, a = rgba
        return pg.PlotCurveItem(
            fillLevel=0,
            brush=pg.mkBrush(r, g, b, a),
            pen=pg.mkPen(r, g, b, 180),
        )

    @staticmethod
    def _sat_style(ch: str, active: bool) -> str:
        inactive_bg, active_bg, inactive_fg, active_fg = _SAT_STYLE[ch]
        bg = active_bg if active else inactive_bg
        fg = active_fg if active else inactive_fg
        return (
            f"background: {bg}; border-radius: 3px;"
            f" color: {fg}; font-size: 9px; font-weight: bold;"
        )

    def update_frame(self, frame: np.ndarray) -> None:
        """Compute histograms and update saturation lamps from a (H,W,3) uint8 frame."""
        # Saturation check on the full-resolution frame so no clipped pixel is missed.
        sat = [frame[:, :, ch] >= 255 for ch in range(3)]
        for mask, key in zip(sat, ("R", "G", "B")):
            self._sat_labels[key].setStyleSheet(self._sat_style(key, bool(mask.any())))
        # "W" lights when any single pixel has all three channels clipped simultaneously.
        self._sat_labels["W"].setStyleSheet(
            self._sat_style("W", bool((sat[0] & sat[1] & sat[2]).any()))
        )

        # Histogram on downsampled frame for speed.
        h, w = frame.shape[:2]
        sy = max(1, h // _MAX_DIM)
        sx = max(1, w // _MAX_DIM)
        small = frame[::sy, ::sx, :]

        for curve, ch in zip((self._curve_r, self._curve_g, self._curve_b), (0, 1, 2)):
            counts = np.bincount(small[:, :, ch].ravel(), minlength=256)[:256]
            curve.setData(_BIN_X, counts.astype(np.float64))

    def clear(self) -> None:
        """Remove all histogram data and reset saturation lamps."""
        for curve in (self._curve_r, self._curve_g, self._curve_b):
            curve.setData([], [])
        for ch in ("R", "G", "B", "W"):
            self._sat_labels[ch].setStyleSheet(self._sat_style(ch, active=False))
