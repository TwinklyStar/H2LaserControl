"""Tests for gui/live_view.py — LiveView widget."""
from __future__ import annotations

import numpy as np
import pytest

from h2lasercontrol.laserdaq.config import AppConfig
from h2lasercontrol.laserdaq.gui.live_view import LiveView


def _dummy_frame(H: int = 20, W: int = 30) -> np.ndarray:
    return np.random.default_rng(0).integers(0, 256, (H, W, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Construction and frame display
# ---------------------------------------------------------------------------

def test_live_view_constructs(qapp):
    view = LiveView(AppConfig())
    assert view is not None


def test_live_view_initial_last_frame_is_none(qapp):
    view = LiveView(AppConfig())
    assert view.last_frame is None


def test_live_view_update_frame_stores_last(qapp):
    view = LiveView(AppConfig())
    frame = _dummy_frame()
    view.update_frame(frame)
    assert view.last_frame is not None
    assert view.last_frame.shape == frame.shape


def test_live_view_update_frame_stores_correct_data(qapp):
    view = LiveView(AppConfig())
    frame = _dummy_frame()
    view.update_frame(frame)
    np.testing.assert_array_equal(view.last_frame, frame)


def test_live_view_update_frame_multiple_times(qapp):
    view = LiveView(AppConfig())
    for i in range(3):
        frame = np.full((10, 10, 3), i * 50, dtype=np.uint8)
        view.update_frame(frame)
    assert view.last_frame[0, 0, 0] == pytest.approx(100.0)


def test_live_view_has_no_fit_overlay_api(qapp):
    """Fit overlay / frozen-frame APIs were removed in Feature 9."""
    view = LiveView(AppConfig())
    for name in ("show_overlay", "show_static_frame", "show_channel_frame", "resume_live"):
        assert not hasattr(view, name)


# ---------------------------------------------------------------------------
# ROI box (hidden placeholder; Feature 11 binds it to the auto-gain ROI)
# ---------------------------------------------------------------------------

def test_live_view_roi_hidden_by_default(qapp):
    view = LiveView(AppConfig())
    assert not view._roi.isVisible()


def test_live_view_set_roi_moves_box(qapp):
    view = LiveView(AppConfig())
    view.set_roi(10, 300, 20, 250)
    pos, size = view._roi.pos(), view._roi.size()
    assert (int(pos.x()), int(pos.y())) == (10, 20)
    assert (int(size.x()), int(size.y())) == (290, 230)


def test_live_view_roi_changed_signal_emitted(qapp):
    view = LiveView(AppConfig())
    received: list[tuple] = []
    view.roi_changed.connect(lambda *args: received.append(args))
    view._roi.setPos([10, 20])
    view._roi.setSize([100, 50])
    assert len(received) >= 1
    assert received[-1] == (10, 110, 20, 70)
