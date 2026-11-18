"""Live view widget — pyqtgraph ImageView with RGB histogram and the auto-gain ROI box."""
from __future__ import annotations

import logging
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..config import AppConfig, ROIConfig
from .histogram import RGBHistogramWidget


class LiveView(QWidget):
    """Displays camera frames; hosts the draggable auto-gain ROI box (bound to config.gain_roi)."""

    roi_changed = Signal(int, int, int, int)  # xmin, xmax, ymin, ymax

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        # The ROI box edits config.gain_roi in place (full-resolution pixel coordinates).
        self._active_roi: ROIConfig = config.gain_roi
        self._syncing = False
        self._bounds: tuple[int, int] | None = None
        self._last_frame: np.ndarray | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._image_view = pg.ImageView()
        ui = self._image_view.ui
        ui.histogram.hide()
        ui.roiPlot.hide()
        ui.roiBtn.hide()
        ui.menuBtn.hide()
        layout.addWidget(self._image_view, stretch=1)

        self._histogram = RGBHistogramWidget()
        self._histogram.setFixedHeight(70)
        layout.addWidget(self._histogram)

        r = self._active_roi
        self._roi = pg.RectROI(
            [r.xmin, r.ymin],
            [r.xmax - r.xmin, r.ymax - r.ymin],
            pen=pg.mkPen("y", width=2),
        )
        self._image_view.addItem(self._roi)
        self._roi.sigRegionChanged.connect(self._on_roi_changed)
        self._roi.setVisible(False)  # hidden until shown via set_roi_visible()

    # ---- Frame display ----

    def update_frame(self, frame: np.ndarray) -> None:
        """Display a (H, W, 3) uint8 RGB frame."""
        t0 = time.monotonic()
        self._last_frame = frame  # full-res kept for capture/analysis
        if frame.shape[:2] != self._bounds:
            self._bounds = frame.shape[:2]
            h, w = self._bounds
            self._roi.maxBounds = QRectF(0, 0, w, h)  # keep the ROI inside the image
        # Downsample 2× for display: setImage on 2048×1536 takes ~120 ms (queue overflows);
        # at 1024×768 it takes ~30 ms, comfortably within the 100 ms frame interval.
        img = frame[::2, ::2, :]
        # pyqtgraph ImageView: first axis = column (x), second = row (y) → transpose
        img = img.transpose(1, 0, 2)
        # autoLevels=False avoids a full-image min/max scan on every frame.
        # scale=(2, 2): the displayed image is half resolution; this keeps the ViewBox
        # coordinate space in FULL-resolution pixels so the ROI box coordinates match
        # the frame the auto-gain tuner reads.  It must be passed on every call:
        # ImageView.setImage() resets the item transform each time.
        self._image_view.setImage(
            img, autoLevels=False, levels=(0, 255), autoHistogramRange=False, scale=(2.0, 2.0)
        )
        self._histogram.update_frame(frame)
        logging.getLogger("laserdaq.liveview").debug(
            "setImage %.1f ms  shape=%s", (time.monotonic() - t0) * 1000, img.shape
        )

    @property
    def last_frame(self) -> np.ndarray | None:
        return self._last_frame

    # ---- ROI ----

    def set_roi_visible(self, visible: bool) -> None:
        self._roi.setVisible(visible)

    def set_roi(self, xmin: int, xmax: int, ymin: int, ymax: int) -> None:
        """Move the ROI programmatically; the bound ROIConfig is updated."""
        self._roi.setPos([xmin, ymin])
        self._roi.setSize([xmax - xmin, ymax - ymin])

    def bind_roi(self, roi: ROIConfig) -> None:
        """Bind the box to another ROIConfig (e.g. after loading a config) without editing it."""
        self._active_roi = roi
        self._syncing = True
        try:
            self._roi.setPos([roi.xmin, roi.ymin])
            self._roi.setSize([roi.xmax - roi.xmin, roi.ymax - roi.ymin])
        finally:
            self._syncing = False

    def set_roi_locked(self, locked: bool) -> None:
        """Freeze the box (no drag / resize) while auto gain runs."""
        self._roi.translatable = not locked
        self._roi.resizable = not locked
        for handle in self._roi.getHandles():
            handle.setVisible(not locked)
            handle.setEnabled(not locked)

    @property
    def roi_config(self) -> ROIConfig:
        return self._active_roi

    # ---- Private ----

    def _on_roi_changed(self) -> None:
        if self._syncing:
            return
        pos = self._roi.pos()
        size = self._roi.size()
        self._active_roi.xmin = int(pos.x())
        self._active_roi.ymin = int(pos.y())
        self._active_roi.xmax = int(pos.x() + size.x())
        self._active_roi.ymax = int(pos.y() + size.y())
        self.roi_changed.emit(
            self._active_roi.xmin,
            self._active_roi.xmax,
            self._active_roi.ymin,
            self._active_roi.ymax,
        )
