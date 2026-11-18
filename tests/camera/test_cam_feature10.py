"""Tests for Feature 10 — 25 Hz recording: uint8 frames, FrameRecorder, controller hook, convert."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from h2lasercontrol.laserdaq.camera.controller import AcquisitionController
from h2lasercontrol.laserdaq.camera.mock import MockCamera
from h2lasercontrol.laserdaq.config import AppConfig
from h2lasercontrol.laserdaq.storage import recorder as rec_mod
from h2lasercontrol.laserdaq.storage.convert import convert_run
from h2lasercontrol.laserdaq.storage.recorder import FrameRecorder, make_run_dir, read_bmp_rgb


def _frames(n: int, H: int = 12, W: int = 16) -> list[np.ndarray]:
    rng = np.random.default_rng(5)
    out = []
    for i in range(n):
        f = rng.integers(0, 256, (H, W, 3), dtype=np.uint8)
        f[0, 0] = (i % 256, 7, 9)
        out.append(f)
    return out


# ---------------------------------------------------------------- F10.1 uint8

def test_mock_camera_yields_uint8(qapp):
    cam = MockCamera(fps=100.0)
    cam.open()
    f = next(iter(cam.frames()))
    cam.close()
    assert f.dtype == np.uint8 and f.ndim == 3 and f.shape[2] == 3


def test_live_view_and_histogram_accept_uint8(qapp):
    from h2lasercontrol.laserdaq.gui.live_view import LiveView
    view = LiveView(AppConfig())
    frame = np.zeros((20, 30, 3), np.uint8)
    frame[0, 0] = 255
    view.update_frame(frame)
    lamps = view._histogram._sat_labels
    assert "#ff3030" in lamps["R"].styleSheet()
    assert "#e8e8e8" in lamps["W"].styleSheet()


# ------------------------------------------------------------ F10.2 recorder

def test_recorder_writes_all_frames_bit_identical(tmp_path):
    frames = _frames(100)
    rec = FrameRecorder(tmp_path / "run", config=AppConfig(), max_queue=200)
    rec.start()
    for i, f in enumerate(frames):
        assert rec.submit(f, cam_frame_id=1000 + i, cam_timestamp_ns=i * 40_000_000)
    stats = rec.stop()
    assert stats.written == 100 and stats.dropped == 0
    bmps = sorted((tmp_path / "run").glob("*.bmp"))
    assert len(bmps) == 100
    for f, p in zip(frames, bmps):
        np.testing.assert_array_equal(read_bmp_rgb(p), f)
    rows = (tmp_path / "run" / "frames.csv").read_text().strip().splitlines()
    assert rows[0].startswith("index,filename")
    assert len(rows) == 101
    assert rows[1].split(",")[4] == "1000"
    assert (tmp_path / "run" / "run_config.toml").exists()


def test_recorder_never_blocks_and_reports_drops(tmp_path, monkeypatch):
    real = rec_mod.cv2.imwrite

    def slow(path, img):
        time.sleep(0.05)
        return real(path, img)

    monkeypatch.setattr(rec_mod.cv2, "imwrite", slow)
    rec = FrameRecorder(tmp_path / "run", max_queue=3)
    rec.start()
    frames = _frames(30)
    worst = 0.0
    results = []
    for f in frames:
        t0 = time.perf_counter()
        results.append(rec.submit(f))
        worst = max(worst, time.perf_counter() - t0)
    stats = rec.stop()
    assert worst < 0.02  # submit() never waits for the slow writer
    assert stats.dropped > 0
    assert stats.written + stats.dropped == stats.submitted == 30
    # indices are assigned at submit time, so only written frames appear in the CSV
    idx = [int(r.split(",")[0]) for r in
           (tmp_path / "run" / "frames.csv").read_text().strip().splitlines()[1:]]
    assert len(idx) == stats.written
    assert idx == sorted(set(idx)) and max(idx) <= 30


def test_recorder_stop_is_idempotent(tmp_path):
    rec = FrameRecorder(tmp_path / "run")
    rec.start()
    assert rec.stop() is rec.stop()


def test_burst_folder_and_photo_names(tmp_path):
    import re
    rec = FrameRecorder(make_run_dir(tmp_path))
    rec.start()
    for f in _frames(3):
        rec.submit(f)
    rec.stop()
    assert re.fullmatch(r"001_\d{6}", rec.run_dir.name)
    names = sorted(p.name for p in rec.run_dir.glob("*.bmp"))
    assert names == ["000001.bmp", "000002.bmp", "000003.bmp"]
    rows = (rec.run_dir / "frames.csv").read_text().splitlines()[1:]
    assert rows[0].split(",")[1] == "000001.bmp"
    assert make_run_dir(tmp_path).name.startswith("002_")


def test_single_capture_files_and_shared_counter(tmp_path):
    from h2lasercontrol.laserdaq.config import load_config
    from h2lasercontrol.laserdaq.storage.recorder import make_single_path
    burst = FrameRecorder(make_run_dir(tmp_path))
    burst.start()
    burst.submit(_frames(1)[0])
    burst.stop()
    stem = make_single_path(tmp_path)
    assert stem.name.startswith("002_")  # counter shared with bursts
    assert stem.parent == burst.run_dir.parent  # same directory as the burst folder
    rec = FrameRecorder(stem, config=AppConfig(exposure_us=1234.0), single=True)
    rec.start()
    assert rec.submit(_frames(1)[0]) is True
    assert rec.submit(_frames(1)[0]) is False  # only one photo per single capture
    stats = rec.stop()
    assert stats.written == 1
    assert (stem.parent / f"{stem.name}.bmp").is_file()
    cfg_file = stem.parent / f"{stem.name}_config.toml"
    assert cfg_file.is_file()
    assert not (stem.parent / "frames.csv").exists()
    assert not list(stem.parent.glob(f"{stem.name}*.csv"))
    cfg = load_config(cfg_file)
    assert cfg.exposure_us == 1234.0
    assert cfg.timestamp  # ISO time of the capture
    assert stats.run_dir == stem.parent / f"{stem.name}.bmp"


def test_burst_config_has_timestamp(tmp_path):
    from h2lasercontrol.laserdaq.config import load_config
    rec = FrameRecorder(tmp_path / "b", config=AppConfig())
    rec.start()
    rec.stop()
    assert load_config(tmp_path / "b" / "run_config.toml").timestamp


def test_convert_path_single_file_and_folder(tmp_path):
    import uproot

    from h2lasercontrol.laserdaq.storage.convert import convert_path
    rec = FrameRecorder(tmp_path / "run")
    rec.start()
    for f in _frames(3):
        rec.submit(f)
    rec.stop()
    bmps = sorted((tmp_path / "run").glob("*.bmp"))
    assert convert_path(bmps[1], root=True) == 1
    assert len(list((tmp_path / "run").glob("*.root"))) == 1
    assert convert_path(tmp_path / "run", root=True) == 3
    roots = sorted((tmp_path / "run").glob("*.root"))
    assert [r.stem for r in roots] == [b.stem for b in bmps]
    with uproot.open(roots[0]) as rf:
        assert set(rf.keys()) >= {"hR;1", "hG;1", "hB;1", "hB_sub;1"}


def _make_day(tmp_path):
    """day/001_120000.bmp (single) + day/002_120001/{000001,000002}.bmp (burst)."""
    day = tmp_path / "day"
    single = FrameRecorder(day / "001_120000", single=True)
    single.start()
    single.submit(_frames(1)[0])
    single.stop()
    burst = FrameRecorder(day / "002_120001")
    burst.start()
    for f in _frames(2):
        burst.submit(f)
    burst.stop()
    return day


def test_convert_recursive_covers_bursts(tmp_path):
    from h2lasercontrol.laserdaq.storage.convert import convert_path
    day = _make_day(tmp_path)
    assert convert_path(day, root=True) == 1  # not recursive: only the single photo
    for r in day.rglob("*.root"):
        r.unlink()
    assert convert_path(day, root=True, recursive=True) == 3
    assert sorted(p.relative_to(day).as_posix() for p in day.rglob("*.root")) == [
        "001_120000.root", "002_120001/000001.root", "002_120001/000002.root"]


def test_convert_recursive_out_dir_mirrors_structure(tmp_path):
    from h2lasercontrol.laserdaq.storage.convert import convert_path
    day = _make_day(tmp_path)
    assert convert_path(day, png=True, root=False, recursive=True, out_dir=tmp_path / "o") == 3
    assert (tmp_path / "o" / "002_120001" / "000002.png").is_file()
    assert (tmp_path / "o" / "001_120000.png").is_file()


def test_bmp_to_root_script_recursive(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    day = _make_day(tmp_path)
    script = Path(__file__).resolve().parents[2] / "tools" / "bmp_to_root.py"
    r = subprocess.run([sys.executable, str(script), str(day), "--recursive"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert len(list(day.rglob("*.root"))) == 3


def test_bmp_to_root_script(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    rec = FrameRecorder(tmp_path / "run")
    rec.start()
    for f in _frames(2):
        rec.submit(f)
    rec.stop()
    script = Path(__file__).resolve().parents[2] / "tools" / "bmp_to_root.py"
    r = subprocess.run([sys.executable, str(script), str(tmp_path / "run")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert len(list((tmp_path / "run").glob("*.root"))) == 2


def test_make_run_dir_unique(tmp_path):
    a = make_run_dir(tmp_path)
    a.mkdir(parents=True)
    b = make_run_dir(tmp_path)
    assert a != b


@pytest.mark.slow
def test_recorder_throughput_exceeds_25fps_full_frame(tmp_path):
    frame = np.random.default_rng(0).integers(0, 256, (1536, 2048, 3), dtype=np.uint8)
    rec = FrameRecorder(tmp_path / "run", max_queue=100)
    rec.start()
    for _ in range(60):
        rec.submit(frame)
    stats = rec.stop()
    assert stats.written / stats.elapsed_s > 25


# ------------------------------------------------------- F10.3 controller hook

def test_controller_records_every_frame_while_display_is_throttled(qapp, tmp_path):
    n = 40
    items = [np.full((8, 8, 3), i, np.uint8) for i in range(n)]
    cam = MockCamera(items=items, fps=200.0)
    ctrl = AcquisitionController(cam, display_fps=5.0)
    shown = []
    ctrl.frame_ready.connect(lambda f: (shown.append(1), ctrl.notify_frame_displayed()),
                             type=__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.DirectConnection)
    finished = []
    done = threading.Event()

    def on_done(stats):
        finished.append(stats)
        done.set()

    ctrl.recording_finished.connect(
        on_done, type=__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.DirectConnection)
    rec = FrameRecorder(tmp_path / "run", max_queue=100)
    ctrl.start()
    ctrl.start_recording(rec, n)
    assert done.wait(10)
    ctrl.stop()
    assert len(finished) == 1
    stats = finished[0]
    assert stats.written + stats.dropped == n
    assert stats.written == n  # queue was large enough
    # frames are distinct and in order (pixel [0,0] carries the index)
    bmps = sorted((tmp_path / "run").glob("*.bmp"))
    vals = [int(read_bmp_rgb(p)[0, 0, 0]) for p in bmps]
    # recording began mid-cycle, so check consecutive (mod n) and all distinct
    assert all((b - a) % n == 1 for a, b in zip(vals, vals[1:]))
    assert len(set(vals)) == n
    assert len(shown) < n  # display really was throttled


def test_controller_stop_recording_finishes_once(qapp, tmp_path):
    cam = MockCamera(items=[np.zeros((8, 8, 3), np.uint8)], fps=100.0)
    ctrl = AcquisitionController(cam)
    from PySide6.QtCore import Qt
    finished = []
    ctrl.recording_finished.connect(finished.append, type=Qt.DirectConnection)
    rec = FrameRecorder(tmp_path / "run")
    ctrl.start()
    ctrl.start_recording(rec, None)
    time.sleep(0.3)
    ctrl.stop_recording()
    ctrl.stop_recording()  # second call is a no-op
    t_end = time.monotonic() + 5
    while not finished and time.monotonic() < t_end:
        time.sleep(0.02)
    ctrl.stop()
    assert len(finished) == 1
    assert finished[0].written > 0


def test_cannot_start_two_recordings(qapp, tmp_path):
    cam = MockCamera(fps=5.0)
    ctrl = AcquisitionController(cam)
    ctrl.start()
    ctrl.start_recording(FrameRecorder(tmp_path / "a"), None)
    with pytest.raises(RuntimeError):
        ctrl.start_recording(FrameRecorder(tmp_path / "b"), None)
    ctrl.stop_recording()
    ctrl.stop()


# --------------------------------------------------------------- F10.6 convert

def test_convert_run_root_and_png(tmp_path):
    import uproot

    from h2lasercontrol.laserdaq.storage.images import save_rgb_png  # noqa: F401
    frames = _frames(3)
    rec = FrameRecorder(tmp_path / "run")
    rec.start()
    for f in frames:
        rec.submit(f)
    rec.stop()
    n = convert_run(tmp_path / "run", root=True, png=True)
    assert n == 3
    for i, f in enumerate(frames, start=1):
        stem = sorted((tmp_path / "run").glob("*.bmp"))[i - 1].with_suffix("")
        assert stem.name == f"{i:06d}"
        import imageio.v3 as iio
        np.testing.assert_array_equal(iio.imread(stem.with_suffix(".png")), f)
        with uproot.open(stem.with_suffix(".root")) as rf:
            hR = rf["hR"].values()
            hB_sub = rf["hB_sub"].values()
        np.testing.assert_array_equal(hR, np.flipud(f[:, :, 0]).T.astype(float))
        assert not hB_sub.any()


def test_convert_range_and_out_dir(tmp_path):
    rec = FrameRecorder(tmp_path / "run")
    rec.start()
    for f in _frames(5):
        rec.submit(f)
    rec.stop()
    n = convert_run(tmp_path / "run", png=True, out_dir=tmp_path / "pngs", frame_range=(2, 3))
    assert n == 2
    assert [p.name[:6] for p in sorted((tmp_path / "pngs").glob("*.png"))] == ["000002", "000003"]






# ------------------------------------------------------------ F10.5 exposure cap

def test_hardware_exposure_ceiling_follows_camera_fps(qapp):
    from h2lasercontrol.laserdaq.gui.main_window import MainWindow
    window = MainWindow(AppConfig(), camera=MockCamera(exposure_limits=(100.0, 900_000.0)))
    try:
        window._hw_radio.setChecked(True)
        window._on_fps_updated(2.0)  # slow DISPLAY fps must not move the ceiling
        assert window._exposure_spin.maximum() != pytest.approx(500_000.0)
        window._on_camera_fps_updated(10.0)
        assert window._exposure_spin.maximum() == pytest.approx(100_000.0)
    finally:
        window.close()




# ------------------------------------------------ shutdown robustness (camera hang)

def test_controller_stop_flushes_open_recording(qapp, tmp_path):
    cam = MockCamera(items=[np.zeros((8, 8, 3), np.uint8)], fps=100.0)
    ctrl = AcquisitionController(cam)
    ctrl.start()
    ctrl.start_recording(FrameRecorder(tmp_path / "run"), None)
    time.sleep(0.3)
    ctrl.stop()  # window closed mid-recording
    assert not ctrl.recording
    run = tmp_path / "run"
    rows = (run / "frames.csv").read_text().strip().splitlines()[1:]
    assert len(rows) == len(list(run.glob("*.bmp"))) > 0
    ctrl.stop()  # idempotent


def test_stop_is_prompt_at_very_low_fps(qapp):
    """A 2 s frame-pacing sleep must not outlast the controller's join."""
    cam = MockCamera(items=[np.zeros((8, 8, 3), np.uint8)], fps=0.5)
    ctrl = AcquisitionController(cam)
    ctrl.start()
    time.sleep(0.3)
    t0 = time.monotonic()
    ctrl.stop()
    assert time.monotonic() - t0 < 1.0


def test_window_shutdown_is_idempotent_and_stops_camera(qapp):
    from h2lasercontrol.laserdaq.gui.main_window import MainWindow
    cam = MockCamera(fps=50.0)
    w = MainWindow(AppConfig(), camera=cam)
    w.shutdown()
    w.shutdown()
    assert cam._running is False
    w.close()


def test_ids_open_failure_leaves_camera_reopenable():
    """A failed open() must release the SDK library (else the next open() is corrupted)."""
    from unittest import mock

    from h2lasercontrol.laserdaq.camera import ids_camera
    with mock.patch.object(ids_camera, "ids_peak") as peak:
        peak.DeviceManager.Instance.return_value.Devices.return_value = []
        cam = ids_camera.IDSCamera()
        with pytest.raises(RuntimeError, match="No IDS device"):
            cam.open()
        assert cam._lib_initialized is False
        peak.Library.Close.assert_called_once()


def test_ids_dead_control_channel_gives_clear_error():
    from unittest import mock

    from h2lasercontrol.laserdaq.camera import ids_camera
    with mock.patch.object(ids_camera, "ids_peak") as peak:
        desc = mock.MagicMock()
        desc.IsOpenable.return_value = True
        desc.OpenDevice.return_value.RemoteDevice.return_value.NodeMaps.return_value = []
        peak.DeviceManager.Instance.return_value.Devices.return_value = [desc]
        cam = ids_camera.IDSCamera()
        with pytest.raises(RuntimeError, match="not responding"):
            cam.open()
        assert cam._lib_initialized is False


# --------------------------------------------- settings written on the acquisition thread

def test_settings_are_written_by_the_acquisition_thread(qapp):
    seen = []

    class _Spy(MockCamera):
        def set_exposure(self, us):
            seen.append(threading.current_thread().name)
            super().set_exposure(us)

    cam = _Spy(fps=100.0)
    ctrl = AcquisitionController(cam)
    ctrl.start()
    ctrl.apply_settings(exposure_us=20_000.0)
    t_end = time.monotonic() + 3
    while not seen and time.monotonic() < t_end:
        time.sleep(0.01)
    ctrl.stop()
    assert seen == ["daq-acq"]
    assert cam.exposure_us == 20_000.0


def test_settings_latest_value_wins_and_direct_when_stopped(qapp):
    cam = MockCamera(fps=100.0)
    ctrl = AcquisitionController(cam)
    ctrl.apply_settings(analog_gain=2.0)  # not running: written immediately
    assert cam.analog_gain == 2.0
    ctrl.start()
    for g in (3.0, 4.0, 5.0):
        ctrl.apply_settings(analog_gain=g)
    t_end = time.monotonic() + 3
    while cam.analog_gain != 5.0 and time.monotonic() < t_end:
        time.sleep(0.01)
    ctrl.stop()
    assert cam.analog_gain == 5.0


def test_pause_flushes_pending_settings(qapp):
    cam = MockCamera(fps=0.5)  # frames far apart: the write would wait a long time
    ctrl = AcquisitionController(cam)
    ctrl.start()
    time.sleep(0.2)
    ctrl.apply_settings(digital_gain=3.0)
    ctrl.pause()
    assert cam.digital_gain == 3.0
    ctrl.resume()
    ctrl.stop()


def test_hang_watchdog_dumps_once_when_gui_blocked(qapp):
    from PySide6.QtWidgets import QApplication

    from h2lasercontrol.laserdaq.gui.hang_watchdog import HangWatchdog
    dumps = []
    wd = HangWatchdog(timeout_s=0.4, dump=lambda: dumps.append(1))
    wd.start()
    try:
        QApplication.processEvents()
        time.sleep(1.2)  # the "GUI thread" (this one) does not process events
        assert dumps == [1]
        t_end = time.monotonic() + 1.0
        while time.monotonic() < t_end:  # responsive again
            QApplication.processEvents()
            time.sleep(0.02)
        assert dumps == [1]
    finally:
        wd.stop()
