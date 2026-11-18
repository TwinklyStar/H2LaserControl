"""Tests for device error / disconnect handling and a capture smoke test.

- No camera → clear status, no crash, button disabled
- Camera that raises on open() → error shown, no crash, clean close
- error_occurred signal → status bar update
- End-to-end smoke: live frame → Capture → PNG + ROOT + config on disk
"""
from __future__ import annotations

import time

import numpy as np

from h2lasercontrol.laserdaq.camera.base import CameraBase
from h2lasercontrol.laserdaq.config import AppConfig
from h2lasercontrol.laserdaq.gui.main_window import AppState, MainWindow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _BrokenCamera(CameraBase):
    """Fake camera that raises RuntimeError on open()."""

    def open(self) -> None:
        raise RuntimeError("No IDS device found")

    def close(self) -> None:
        pass

    def get_exposure_limits(self) -> tuple[float, float]:
        return (100.0, 100_000.0)

    def set_exposure(self, us: float) -> None:
        pass

    def set_gain(self, gain: float) -> None:
        pass

    def get_analog_gain_limits(self) -> tuple[float, float]:
        return (1.0, 12.5)

    def get_digital_gain_limits(self) -> tuple[float, float]:
        return (1.0, 16.0)

    def set_analog_gain(self, gain: float) -> None:
        pass

    def set_digital_gain(self, gain: float) -> None:
        pass

    def frames(self):
        return iter([])


# ===========================================================================
# Step 8.1 — Device error / disconnect handling
# ===========================================================================

class TestDeviceHandling:

    def test_no_camera_shows_no_camera_status(self, qapp):
        """MainWindow with no camera shows 'No camera' in the FPS label."""
        window = MainWindow(AppConfig())
        assert "No camera" in window._fps_label.text()

    def test_no_camera_capture_button_disabled(self, qapp):
        """Capture button is disabled when no camera is configured."""
        window = MainWindow(AppConfig())
        assert not window._capture_btn.isEnabled()

    def test_broken_camera_no_crash(self, qapp):
        """MainWindow with a camera that raises on open() does not raise."""
        # Must not raise any exception
        window = MainWindow(AppConfig(), camera=_BrokenCamera())
        assert window is not None

    def test_broken_camera_shows_error_in_status_bar(self, qapp):
        """Status label shows a camera error message when open() fails."""
        window = MainWindow(AppConfig(), camera=_BrokenCamera())
        msg = window._status_label.text()
        assert "Camera error" in msg or "No IDS device" in msg

    def test_broken_camera_capture_button_disabled(self, qapp):
        """Capture button stays disabled when camera open() fails."""
        window = MainWindow(AppConfig(), camera=_BrokenCamera())
        assert not window._capture_btn.isEnabled()

    def test_broken_camera_close_no_crash(self, qapp):
        """Closing a window whose camera failed to open does not raise."""
        window = MainWindow(AppConfig(), camera=_BrokenCamera())
        window.close()  # must not raise

    def test_camera_error_signal_updates_status_bar(self, qapp):
        """error_occurred signal from controller is shown in the status label."""
        window = MainWindow(AppConfig())
        window._on_camera_error("disk full")
        msg = window._status_label.text()
        assert "Camera error" in msg
        assert "disk full" in msg


# ===========================================================================
# End-to-end smoke (mock, CI)
# ===========================================================================

class TestEndToEndSmoke:

    def test_e2e_capture_produces_bmp_run(self, qapp, tmp_path):
        """Capture saves NNN_HHMMSS.bmp + NNN_HHMMSS_config.toml in the day folder."""
        from PySide6.QtWidgets import QApplication

        from h2lasercontrol.laserdaq.camera.mock import MockCamera
        cfg = AppConfig(output_dir=str(tmp_path / "out"))
        cam = MockCamera(items=[np.full((30, 40, 3), 200, np.uint8)], fps=50.0)
        window = MainWindow(cfg, camera=cam)
        try:
            window._do_capture_and_save()
            for _ in range(400):
                QApplication.processEvents()
                time.sleep(0.01)
                if window._app_state is AppState.LIVE:
                    break
            out = tmp_path / "out"
            assert window._app_state is AppState.LIVE
            bmps = list(out.rglob("*.bmp"))
            assert len(bmps) == 1
            # single capture: NNN_HHMMSS.bmp + NNN_HHMMSS_config.toml, no frame log
            assert bmps[0].with_name(bmps[0].stem + "_config.toml").is_file()
            assert list(out.rglob("frames.csv")) == []
        finally:
            window.close()
