"""Tests for Feature 6 — multiple camera support."""
from __future__ import annotations

from h2lasercontrol.laserdaq.camera.mock import MockCamera
from h2lasercontrol.laserdaq.config import AppConfig

# ---------------------------------------------------------------------------
# F6.1 — list_devices() return format
# ---------------------------------------------------------------------------





def test_ids_camera_stores_serial():
    """IDSCamera(serial='X') stores the serial for use in open()."""
    from h2lasercontrol.laserdaq.camera.ids_camera import IDSCamera
    cam = IDSCamera(serial="ABC123", fps=5.0)
    assert cam._serial == "ABC123"


def test_ids_camera_serial_none_by_default():
    from h2lasercontrol.laserdaq.camera.ids_camera import IDSCamera
    cam = IDSCamera()
    assert cam._serial is None


# ---------------------------------------------------------------------------
# F6.2 — pick_camera() selection helper (mocked list_devices)
# ---------------------------------------------------------------------------


def _fake_ids_class(serial: str, display: str):
    """Return a fake IDSCamera-like class whose list_devices() returns one entry."""
    class _Fake:
        _serial = None
        _fps = None
        def __init__(self, **kwargs):
            self._serial = kwargs.get("serial")
            self._fps = kwargs.get("fps")
        @staticmethod
        def list_devices():
            return [(serial, display)]
    return _Fake


















# ---------------------------------------------------------------------------
# F6.3 — camera_label surfaced in GUI status bar
# ---------------------------------------------------------------------------

def test_gui_fps_label_contains_camera_label(qapp):
    """MainWindow with camera_label shows label in the fps status bar."""
    from h2lasercontrol.laserdaq.gui.main_window import MainWindow
    window = MainWindow(AppConfig(), camera_label="IDS  SN:TEST  uEye XS")
    assert "SN:TEST" in window._fps_label.text()
    window.close()


def test_gui_fps_label_no_label_shows_no_camera(qapp):
    """MainWindow without camera_label shows 'No camera' (no trailing dot)."""
    from h2lasercontrol.laserdaq.gui.main_window import MainWindow
    window = MainWindow(AppConfig())
    assert window._fps_label.text() == "No camera"
    window.close()


def test_gui_fps_label_updated_with_label_after_fps_update(qapp):
    """After an FPS update, the camera_label suffix is still present."""
    from h2lasercontrol.laserdaq.gui.main_window import MainWindow
    window = MainWindow(AppConfig(), camera=MockCamera(), camera_label="IDS  SN:TEST  uEye")
    window._camera_fps = 5.0
    window._display_fps = 4.8
    window._update_fps_status()
    assert "SN:TEST" in window._fps_label.text()
    assert "Cam:" in window._fps_label.text()
    window.close()


# ---------------------------------------------------------------------------
# F6.3 — camera_label surfaced in TUI banner lines
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# F6.4 — laserdaq-cli --serial flag
# ---------------------------------------------------------------------------










