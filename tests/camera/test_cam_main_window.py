"""Tests for gui/main_window.py — shell, capture, exposure / gain controls."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QToolBar

from h2lasercontrol.laserdaq.camera.mock import MockCamera
from h2lasercontrol.laserdaq.config import AppConfig
from h2lasercontrol.laserdaq.gui.main_window import MainWindow


def _wait(cond, timeout_s: float = 3.0) -> bool:
    """Camera settings are written by the acquisition thread; wait until they land."""
    import time

    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def _frame(H: int = 20, W: int = 30) -> np.ndarray:
    return np.random.default_rng(0).integers(0, 256, (H, W, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------

def test_main_window_constructs(qapp):
    window = MainWindow(AppConfig())
    assert window is not None


def test_main_window_has_no_mode_toolbar(qapp):
    window = MainWindow(AppConfig())
    assert window.findChildren(QToolBar) == []


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def test_capture_without_camera_shows_message(qapp, tmp_path):
    window = MainWindow(AppConfig(output_dir=str(tmp_path / "out")))
    window._do_capture_and_save()
    assert "No frame" in window._status_label.text()
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# Step 4.8 — Exposure / gain controls
# ---------------------------------------------------------------------------

def test_exposure_spin_range_set_from_camera_limits(qapp):
    cam = MockCamera(exposure_limits=(200.0, 60_000.0))
    window = MainWindow(AppConfig(), camera=cam)
    assert window._exposure_spin.minimum() == pytest.approx(200.0)
    assert window._exposure_spin.maximum() == pytest.approx(60_000.0)
    window.close()


def test_exposure_spin_clamped_to_camera_max(qapp):
    cam = MockCamera(exposure_limits=(100.0, 50_000.0))
    window = MainWindow(AppConfig(), camera=cam)
    window._exposure_spin.setValue(999_999.0)
    assert window._exposure_spin.value() == pytest.approx(50_000.0)
    window.close()


def test_exposure_spin_clamped_to_camera_min(qapp):
    cam = MockCamera(exposure_limits=(500.0, 50_000.0))
    window = MainWindow(AppConfig(), camera=cam)
    window._exposure_spin.setValue(1.0)
    assert window._exposure_spin.value() == pytest.approx(500.0)
    window.close()


def test_exposure_change_calls_camera_setter(qapp):
    cam = MockCamera(exposure_limits=(100.0, 100_000.0))
    window = MainWindow(AppConfig(), camera=cam)
    window._exposure_spin.setValue(25_000.0)
    assert _wait(lambda: cam.exposure_us == pytest.approx(25_000.0))
    window.close()


def test_analog_gain_change_calls_camera_setter(qapp):
    cam = MockCamera()
    window = MainWindow(AppConfig(), camera=cam)
    window._analog_gain_slider.setValue(int(3.5 * 100))
    assert _wait(lambda: cam.analog_gain == pytest.approx(3.5))
    window.close()


def test_digital_gain_change_calls_camera_setter(qapp):
    cam = MockCamera()
    window = MainWindow(AppConfig(), camera=cam)
    window._digital_gain_slider.setValue(int(2.0 * 100))
    assert _wait(lambda: cam.digital_gain == pytest.approx(2.0))
    window.close()


def test_gain_slider_ranges_set_from_camera(qapp):
    cam = MockCamera()
    window = MainWindow(AppConfig(), camera=cam)
    assert window._analog_gain_slider.maximum() == int(12.5 * 100)
    assert window._digital_gain_slider.maximum() == int(16.0 * 100)
    window.close()


def test_exposure_max_checkbox_pins_to_ceiling(qapp):
    cam = MockCamera(exposure_limits=(100.0, 50_000.0))
    window = MainWindow(AppConfig(), camera=cam)
    window._exposure_max_check.setChecked(True)
    assert _wait(lambda: cam.exposure_us == pytest.approx(window._exposure_spin.maximum()))
    assert not window._exposure_spin.isEnabled()
    window.close()


def test_exposure_max_unchecked_re_enables_spin(qapp):
    cam = MockCamera(exposure_limits=(100.0, 50_000.0))
    window = MainWindow(AppConfig(), camera=cam)
    window._exposure_max_check.setChecked(True)
    window._exposure_max_check.setChecked(False)
    assert window._exposure_spin.isEnabled()
    window.close()


def test_exposure_max_tracks_fps_change(qapp):
    cam = MockCamera(exposure_limits=(100.0, 100_000.0))
    window = MainWindow(AppConfig(), camera=cam)
    window._exposure_max_check.setChecked(True)
    # Lower FPS tightens the ceiling
    window._cam_fps_spin.setValue(20.0)
    window._update_exposure_limit()
    expected_max = min(100_000.0, 1_000_000.0 / 20.0)
    assert _wait(lambda: cam.exposure_us == pytest.approx(expected_max))
    window.close()


def test_exposure_manual_edit_ignored_when_max_checked(qapp):
    cam = MockCamera(exposure_limits=(100.0, 50_000.0))
    window = MainWindow(AppConfig(), camera=cam)
    window._exposure_max_check.setChecked(True)
    assert _wait(lambda: cam.exposure_us == pytest.approx(window._exposure_spin.maximum()))
    pinned = cam.exposure_us
    # Directly invoking the slot as if user typed in the spinbox
    window._on_exposure_changed(1000.0)
    _wait(lambda: False, 0.3)  # give a (wrong) queued write the chance to land
    assert cam.exposure_us == pytest.approx(pinned)
    window.close()


def test_config_exposure_max_loaded_pins_checkbox(qapp):
    cam = MockCamera(exposure_limits=(100.0, 50_000.0))
    cfg = AppConfig(exposure_max=True)
    window = MainWindow(cfg, camera=cam)
    assert window._exposure_max_check.isChecked()
    assert not window._exposure_spin.isEnabled()
    window.close()
