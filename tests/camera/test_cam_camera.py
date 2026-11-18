"""Tests for camera/mock.py and camera/controller.py (Step 4.2)."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import Qt

from h2lasercontrol.laserdaq.camera.controller import AcquisitionController
from h2lasercontrol.laserdaq.camera.mock import MockCamera

# ---------------------------------------------------------------------------
# MockCamera unit tests
# ---------------------------------------------------------------------------

def test_mock_camera_open_close():
    cam = MockCamera()
    cam.open()
    assert cam._running
    cam.close()
    assert not cam._running


def test_mock_camera_exposure_limits():
    cam = MockCamera(exposure_limits=(500.0, 80_000.0))
    lo, hi = cam.get_exposure_limits()
    assert lo == pytest.approx(500.0)
    assert hi == pytest.approx(80_000.0)


def test_mock_camera_set_exposure_clamped():
    cam = MockCamera(exposure_limits=(100.0, 50_000.0))
    cam.set_exposure(999_999.0)
    assert cam.exposure_us == pytest.approx(50_000.0)
    cam.set_exposure(1.0)
    assert cam.exposure_us == pytest.approx(100.0)
    cam.set_exposure(20_000.0)
    assert cam.exposure_us == pytest.approx(20_000.0)


def test_mock_camera_set_gain_stores_value():
    cam = MockCamera()
    cam.set_gain(2.5)
    assert cam.gain == pytest.approx(2.5)


def test_mock_camera_dual_gain():
    cam = MockCamera()
    cam.set_analog_gain(5.0)
    assert cam.analog_gain == pytest.approx(5.0)
    cam.set_digital_gain(3.0)
    assert cam.digital_gain == pytest.approx(3.0)


def test_mock_camera_gain_limits():
    cam = MockCamera()
    assert cam.get_analog_gain_limits() == (1.0, 12.5)
    assert cam.get_digital_gain_limits() == (1.0, 16.0)


def test_mock_camera_frames_yields_ndarray():
    H, W = 20, 30
    frame = np.zeros((H, W, 3), dtype=np.float64)
    cam = MockCamera(items=[frame])
    cam.open()
    gen = cam.frames()
    result = next(gen)
    cam.close()
    assert isinstance(result, np.ndarray)
    assert result.shape == (H, W, 3)


def test_mock_camera_frames_cycles_items():
    a = np.ones((4, 4, 3)) * 10
    b = np.ones((4, 4, 3)) * 20
    cam = MockCamera(items=[a, b])
    cam.open()
    gen = cam.frames()
    f1 = next(gen)
    f2 = next(gen)
    f3 = next(gen)
    cam.close()
    assert f1[0, 0, 0] == pytest.approx(10.0)
    assert f2[0, 0, 0] == pytest.approx(20.0)
    assert f3[0, 0, 0] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# AcquisitionController tests
# ---------------------------------------------------------------------------

def test_controller_emits_frames(qapp):
    """Controller must emit ≥3 frames after start()."""
    frame = np.zeros((8, 10, 3), dtype=np.float64)
    cam = MockCamera(items=[frame])
    ctrl = AcquisitionController(cam)

    received: list[np.ndarray] = []
    event = threading.Event()

    def on_frame(f):
        received.append(f)
        ctrl.notify_frame_displayed()  # release back-pressure for next frame
        if len(received) >= 3:
            event.set()

    ctrl.frame_ready.connect(on_frame, Qt.ConnectionType.DirectConnection)
    ctrl.start()
    event.wait(timeout=5.0)
    ctrl.stop()

    assert len(received) >= 3
    assert all(isinstance(f, np.ndarray) for f in received)


def test_controller_emission_from_background_thread(qapp):
    """Frames must be emitted from a non-main thread."""
    frame = np.zeros((8, 10, 3), dtype=np.float64)
    cam = MockCamera(items=[frame])
    ctrl = AcquisitionController(cam)

    emit_threads: list[threading.Thread] = []
    event = threading.Event()

    def on_frame(f):
        emit_threads.append(threading.current_thread())
        ctrl.notify_frame_displayed()  # release back-pressure for next frame
        if len(emit_threads) >= 2:
            event.set()

    ctrl.frame_ready.connect(on_frame, Qt.ConnectionType.DirectConnection)
    ctrl.start()
    event.wait(timeout=5.0)
    ctrl.stop()

    assert len(emit_threads) >= 2
    main = threading.main_thread()
    assert all(t is not main for t in emit_threads)


def test_controller_stops_emission(qapp):
    """After stop(), no more frames are emitted."""
    frame = np.zeros((4, 4, 3), dtype=np.float64)
    cam = MockCamera(items=[frame])
    ctrl = AcquisitionController(cam)

    started = threading.Event()
    received: list[int] = []

    def on_frame(f):
        received.append(1)
        started.set()

    ctrl.frame_ready.connect(on_frame, Qt.ConnectionType.DirectConnection)
    ctrl.start()
    started.wait(timeout=3.0)
    ctrl.stop()

    count_at_stop = len(received)
    time.sleep(0.1)
    assert len(received) == count_at_stop  # no frames after stop
