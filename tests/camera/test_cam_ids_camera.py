"""Hardware tests for IDSCamera — Phase 5 (Steps 5.1–5.5).

All tests require the IDS camera to be connected.
The entire file is skipped automatically if ids_peak or ids_peak_ipl are not installed.
Individual tests that need a live device use the hw_camera fixture, which skips
when no device is found.
"""
from __future__ import annotations

import threading

import numpy as np
import pytest
from PySide6.QtCore import Qt

pytest.importorskip("ids_peak", reason="ids_peak SDK not installed")
pytest.importorskip("ids_peak_ipl", reason="ids_peak_ipl not installed")

from h2lasercontrol.laserdaq.camera.controller import AcquisitionController  # noqa: E402
from h2lasercontrol.laserdaq.camera.ids_camera import IDSCamera, TriggerMode  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hw_camera():
    """Open the first available IDS camera; skip if none connected or openable."""
    devices = IDSCamera.list_devices()
    if not devices:
        pytest.skip("No IDS camera connected")
    for serial, _name in devices:
        cam = IDSCamera(serial=serial, fps=5.0)
        try:
            cam.open()
            yield cam
            cam.close()
            return
        except Exception:
            try:
                cam.close()
            except Exception:
                pass
    pytest.skip("No IDS camera openable with control access")


# ---------------------------------------------------------------------------
# Step 5.1 — SDK import + device enumeration
# ---------------------------------------------------------------------------


def test_list_devices_no_crash():
    """list_devices() must return a list of (serial, display_name) tuples and never raise."""
    result = IDSCamera.list_devices()
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, tuple) and len(item) == 2
        assert isinstance(item[0], str)  # serial
        assert isinstance(item[1], str)  # display_name


def test_list_devices_with_camera_connected():
    """With cameras connected list_devices() returns ≥1 tuple with non-empty display_name."""
    result = IDSCamera.list_devices()
    if not result:
        pytest.skip("No IDS camera connected")
    assert len(result) >= 1
    serial, display_name = result[0]
    assert display_name  # non-empty


# ---------------------------------------------------------------------------
# Step 5.2 — Open camera + exposure/gain
# ---------------------------------------------------------------------------


def test_open_close_clean():
    """open() followed by close() must leave the library in a clean state."""
    devices = IDSCamera.list_devices()
    if not devices:
        pytest.skip("No IDS camera connected")
    # Try each serial until one opens (device 0 may be held by another process)
    cam = None
    for serial, _name in devices:
        candidate = IDSCamera(serial=serial, fps=5.0)
        try:
            candidate.open()
            cam = candidate
            break
        except Exception:
            try:
                candidate.close()
            except Exception:
                pass
    if cam is None:
        pytest.skip("No IDS camera openable with control access")
    cam.close()
    assert not cam._lib_initialized
    assert not cam._acquiring


def test_exposure_limits_ordered(hw_camera):
    lo, hi = hw_camera.get_exposure_limits()
    assert lo > 0
    assert hi > lo


def test_set_exposure_mid_range(hw_camera):
    lo, hi = hw_camera.get_exposure_limits()
    mid = (lo + hi) / 2.0
    hw_camera.set_exposure(mid)  # must not raise


def test_set_gain_valid(hw_camera):
    hw_camera.set_gain(1.0)  # must not raise


# ---------------------------------------------------------------------------
# Step 5.3 — Single capture → BGRA array
# ---------------------------------------------------------------------------


def test_trigger_and_grab_dtype(hw_camera):
    frame = hw_camera.trigger_and_grab()
    assert isinstance(frame, np.ndarray)
    assert frame.dtype == np.uint8


def test_trigger_and_grab_shape(hw_camera):
    """Frame must be (H, W, 4) — 4 channels for BGRA."""
    frame = hw_camera.trigger_and_grab()
    assert frame.ndim == 3
    assert frame.shape[2] == 4
    h, w, _ = frame.shape
    assert h > 0 and w > 0


def test_trigger_and_grab_two_consecutive(hw_camera):
    """Two consecutive calls must succeed (buffer requeue works correctly)."""
    f1 = hw_camera.trigger_and_grab()
    f2 = hw_camera.trigger_and_grab()
    assert f1.shape == f2.shape


# ---------------------------------------------------------------------------
# Step 5.4 — Continuous acquisition for live view
# ---------------------------------------------------------------------------


def test_frames_yields_rgb_uint8(hw_camera):
    """frames() must yield (H, W, 3) uint8 RGB arrays."""
    received: list[np.ndarray] = []
    done = threading.Event()

    def grab() -> None:
        for f in hw_camera.frames():
            received.append(f)
            if len(received) >= 3:
                hw_camera._running = False
                done.set()
                break

    t = threading.Thread(target=grab, daemon=True)
    t.start()
    done.wait(timeout=10.0)
    t.join(timeout=3.0)

    assert len(received) >= 3
    for f in received:
        assert f.dtype == np.uint8
        assert f.ndim == 3
        assert f.shape[2] == 3  # RGB (not BGRA)


def test_frames_resolution(hw_camera):
    """frames() frames must have positive height and width."""
    frame: np.ndarray | None = None
    done = threading.Event()

    def grab() -> None:
        nonlocal frame
        for f in hw_camera.frames():
            frame = f
            hw_camera._running = False
            done.set()
            break

    t = threading.Thread(target=grab, daemon=True)
    t.start()
    done.wait(timeout=10.0)
    t.join(timeout=3.0)

    assert frame is not None
    h, w, _ = frame.shape
    assert h > 0 and w > 0


def test_frames_drop_in_for_controller(qapp):
    """IDSCamera must be a drop-in replacement for MockCamera in AcquisitionController."""
    devices = IDSCamera.list_devices()
    if not devices:
        pytest.skip("No IDS camera connected")

    # Try each device by serial; any may be locked or in a dirty SDK state.
    for serial, _name in devices:
        cam = IDSCamera(serial=serial, fps=5.0)
        received: list[np.ndarray] = []
        done = threading.Event()
        ctrl = AcquisitionController(cam)

        def on_frame(f: np.ndarray) -> None:
            received.append(f)
            ctrl.notify_frame_displayed()
            if len(received) >= 3:
                done.set()

        ctrl.frame_ready.connect(on_frame, Qt.ConnectionType.DirectConnection)
        try:
            ctrl.start()
        except Exception:
            try:
                ctrl.stop()
            except Exception:
                pass
            continue

        done.wait(timeout=10.0)
        ctrl.stop()

        assert len(received) >= 3
        for f in received:
            assert f.dtype == np.uint8
            assert f.ndim == 3
            assert f.shape[2] == 3
        return  # success — done

    pytest.skip("No IDS camera openable with control access")


# ---------------------------------------------------------------------------
# Step 5.5 — Trigger modes
# ---------------------------------------------------------------------------


def test_free_run_sets_trigger_mode_off(hw_camera):
    """set_trigger_mode(FREE_RUN) must set TriggerMode node to 'Off'."""
    from typing import cast

    from ids_peak import ids_peak  # local import — file already skipped if not available

    hw_camera.set_trigger_mode(TriggerMode.FREE_RUN)
    val = cast(
        ids_peak.EnumerationNode, hw_camera._nodemap.FindNode("TriggerMode")
    ).CurrentEntry().SymbolicValue()
    assert val == "Off"


def test_software_trigger_sets_nodes(hw_camera):
    """set_trigger_mode(SOFTWARE) must set TriggerMode=On, TriggerSource=Software."""
    from typing import cast

    from ids_peak import ids_peak

    hw_camera.set_trigger_mode(TriggerMode.SOFTWARE)
    nm = hw_camera._nodemap
    mode = cast(ids_peak.EnumerationNode,
                nm.FindNode("TriggerMode")).CurrentEntry().SymbolicValue()
    source = cast(ids_peak.EnumerationNode,
                  nm.FindNode("TriggerSource")).CurrentEntry().SymbolicValue()
    assert mode == "On"
    assert source == "Software"


def test_hardware_trigger_sets_nodes(hw_camera):
    """set_trigger_mode(HARDWARE) must set TriggerMode=On, TriggerSource=Line0 (TTL)."""
    from typing import cast

    from ids_peak import ids_peak

    nm = hw_camera._nodemap
    # Skip gracefully if Line0 is not an available trigger source on this camera
    src_node = cast(ids_peak.EnumerationNode, nm.FindNode("TriggerSource"))
    available = [e.StringValue() for e in src_node.AvailableEntries()]
    if "Line0" not in available:
        pytest.skip(f"Line0 not available on this device (available: {available})")

    hw_camera.set_trigger_mode(TriggerMode.HARDWARE)
    mode = cast(ids_peak.EnumerationNode,
                nm.FindNode("TriggerMode")).CurrentEntry().SymbolicValue()
    source = cast(ids_peak.EnumerationNode,
                  nm.FindNode("TriggerSource")).CurrentEntry().SymbolicValue()
    assert mode == "On"
    assert source == "Line0"


def test_software_trigger_capture_no_ext_trigger(hw_camera):
    """In software trigger mode, trigger_and_grab() must work without an external TTL pulse."""
    hw_camera.set_trigger_mode(TriggerMode.SOFTWARE)
    frame = hw_camera.trigger_and_grab()
    assert frame is not None
    assert frame.dtype == np.uint8
    assert frame.ndim == 3
