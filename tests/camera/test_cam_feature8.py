"""Tests for Feature 8 — overlapping RGB histogram in live view.

F8.1  RGBHistogramWidget: construction, update_frame, clear, minimum height.
F8.2  LiveView integration: built-in histogram hidden, histogram updated/cleared
      on frame display calls.
"""
from __future__ import annotations

import numpy as np
import pytest

from h2lasercontrol.laserdaq.config import AppConfig
from h2lasercontrol.laserdaq.gui.histogram import RGBHistogramWidget
from h2lasercontrol.laserdaq.gui.live_view import LiveView

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uniform_frame(H: int, W: int, r: float, g: float, b: float) -> np.ndarray:
    frame = np.empty((H, W, 3), dtype=np.uint8)
    frame[:, :, 0] = r
    frame[:, :, 1] = g
    frame[:, :, 2] = b
    return frame


# ===========================================================================
# F8.1 — RGBHistogramWidget
# ===========================================================================

def test_rgb_histogram_constructs(qapp):
    """RGBHistogramWidget constructs without error."""
    widget = RGBHistogramWidget()
    assert widget is not None


def test_rgb_histogram_update_frame_peaks(qapp):
    """Each channel curve peaks near its uniform value after update_frame."""
    widget = RGBHistogramWidget()
    frame = _uniform_frame(50, 50, r=200.0, g=100.0, b=50.0)
    widget.update_frame(frame)

    x_r, y_r = widget._curve_r.getData()
    x_g, y_g = widget._curve_g.getData()
    x_b, y_b = widget._curve_b.getData()

    assert y_r is not None and len(y_r) > 0
    assert x_r[y_r.argmax()] == pytest.approx(200, abs=1)

    assert y_g is not None and len(y_g) > 0
    assert x_g[y_g.argmax()] == pytest.approx(100, abs=1)

    assert y_b is not None and len(y_b) > 0
    assert x_b[y_b.argmax()] == pytest.approx(50, abs=1)


def test_rgb_histogram_saturation_lamps(qapp):
    """Saturation lamps activate only for channels that reach 255."""
    widget = RGBHistogramWidget()
    frame = _uniform_frame(50, 50, r=255.0, g=128.0, b=50.0)
    widget.update_frame(frame)
    # R is saturated → active colour; G and B are not
    assert "#ff3030" in widget._sat_labels["R"].styleSheet()
    assert "#ff3030" not in widget._sat_labels["G"].styleSheet()
    assert "#ff3030" not in widget._sat_labels["B"].styleSheet()


def test_rgb_histogram_saturation_lamps_clear(qapp):
    """clear() resets all saturation lamps to inactive."""
    from h2lasercontrol.laserdaq.gui.histogram import _SAT_STYLE
    widget = RGBHistogramWidget()
    widget.update_frame(_uniform_frame(10, 10, 255.0, 255.0, 255.0))
    widget.clear()
    for ch in ("R", "G", "B", "W"):
        _, active_color, _, _ = _SAT_STYLE[ch]
        assert active_color not in widget._sat_labels[ch].styleSheet()


def test_rgb_histogram_w_lamp_all_saturated(qapp):
    """W lamp lights when a pixel has all three channels at 255."""
    widget = RGBHistogramWidget()
    frame = _uniform_frame(10, 10, 255.0, 255.0, 255.0)
    widget.update_frame(frame)
    assert "#e8e8e8" in widget._sat_labels["W"].styleSheet()


def test_rgb_histogram_w_lamp_partial_saturation(qapp):
    """W lamp stays off when only some channels are saturated (no single white pixel)."""
    widget = RGBHistogramWidget()
    # R=255 top half, B=255 bottom half — no pixel has all three at once
    frame = np.zeros((20, 10, 3), dtype=np.uint8)
    frame[:10, :, 0] = 255.0   # R saturated in top rows
    frame[10:, :, 2] = 255.0   # B saturated in bottom rows
    widget.update_frame(frame)
    assert "#e8e8e8" not in widget._sat_labels["W"].styleSheet()


def test_rgb_histogram_clear_empties_curves(qapp):
    """After clear(), all three curves have no data."""
    widget = RGBHistogramWidget()
    widget.update_frame(_uniform_frame(20, 20, 128.0, 128.0, 128.0))
    widget.clear()

    for curve in (widget._curve_r, widget._curve_g, widget._curve_b):
        x, _ = curve.getData()
        assert x is None or len(x) == 0


def test_rgb_histogram_minimum_height(qapp):
    """Widget does not impose a minimum height larger than 200 px."""
    widget = RGBHistogramWidget()
    assert widget.minimumHeight() <= 200


# ===========================================================================
# F8.2 — LiveView integration
# ===========================================================================

def test_live_view_builtin_histogram_hidden(qapp):
    """The built-in pyqtgraph HistogramLUTWidget is hidden on construction."""
    view = LiveView(AppConfig())
    assert not view._image_view.ui.histogram.isVisible()


def test_live_view_update_frame_populates_histogram(qapp):
    """update_frame populates the RGB histogram's red curve with non-empty data."""
    view = LiveView(AppConfig())
    view.update_frame(_uniform_frame(40, 60, 128.0, 64.0, 32.0))
    x, y = view._histogram._curve_r.getData()
    assert x is not None and len(x) > 0
