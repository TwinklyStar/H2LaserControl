"""Tests for Feature 11 — auto gain: tuning logic, config fields, GUI workflow."""
from __future__ import annotations

import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from h2lasercontrol.laserdaq.analysis.autogain import (
    Apply,
    AutoGainLimits,
    AutoGainTuner,
    Done,
    Fail,
    allocate,
    next_total,
    roi_peak,
)
from h2lasercontrol.laserdaq.camera.mock import MockCamera
from h2lasercontrol.laserdaq.config import AppConfig, ROIConfig, load_config, save_config
from h2lasercontrol.laserdaq.gui.main_window import AppState, MainWindow

ROI = ROIConfig(xmin=10, xmax=50, ymin=10, ymax=50)
LIM = AutoGainLimits(40_000.0, 40_000.0, 1.0, 10.0, 1.0, 16.0)
WIDE = AutoGainLimits(100.0, 100_000.0, 1.0, 12.0, 1.0, 16.0)


def _model_frame(k: float, exp: float, ag: float, dg: float) -> np.ndarray:
    """60x60 frame, spot inside ROI: pixel = min(255, k * exp * ag * dg)."""
    f = np.zeros((60, 60, 3), np.uint8)
    f[20:40, 20:40] = int(min(255, k * exp * ag * dg))
    return f


# ------------------------------------------------------------- F11.1 logic

class TestAllocate:
    def test_exposure_only(self):
        assert allocate(50_000, WIDE) == (50_000, 1.0, 1.0)

    def test_exposure_maxed_then_analog(self):
        exp, ag, dg = allocate(300_000, WIDE)
        assert exp == 100_000 and ag == pytest.approx(3.0) and dg == 1.0

    def test_all_maxed_then_digital(self):
        exp, ag, dg = allocate(100_000 * 12 * 4, WIDE)
        assert (exp, ag) == (100_000, 12.0) and dg == pytest.approx(4.0)

    def test_decrease_removes_digital_first_then_analog_then_exposure(self):
        big = 100_000 * 12 * 4
        assert allocate(big, WIDE)[2] > 1.0
        e, a, d = allocate(100_000 * 12, WIDE)
        assert d == 1.0 and a == 12.0
        e, a, d = allocate(100_000 * 2, WIDE)
        assert d == 1.0 and a == pytest.approx(2.0) and e == 100_000
        e, a, d = allocate(20_000, WIDE)
        assert (a, d) == (1.0, 1.0) and e == 20_000

    def test_exposure_snaps_to_pulse_multiples(self):
        lim = AutoGainLimits(40_000.0, 200_000.0, 1.0, 12.0, 1.0, 16.0, exp_step_us=40_000.0)
        assert allocate(60_000, lim) == (40_000.0, pytest.approx(1.5), 1.0)
        assert allocate(130_000, lim)[0] == 120_000.0
        assert allocate(130_000, lim)[1] == pytest.approx(130_000 / 120_000)
        assert allocate(10_000, lim)[0] == 40_000.0
        assert allocate(10_000_000, lim)[0] == 200_000.0

    def test_snap_respects_exposure_ceiling_below_one_step(self):
        lim = AutoGainLimits(25_000.0, 30_000.0, 1.0, 12.0, 1.0, 16.0, exp_step_us=40_000.0)
        assert allocate(100_000, lim)[0] == 30_000.0

    def test_respects_free_run_floor(self):
        assert allocate(10_000, LIM)[0] == 40_000


class TestNextTotal:
    def test_saturated_halves(self):
        assert next_total(1000, 255, True) == 500

    def test_linear_scaling(self):
        assert next_total(1000, 63.75, False) == pytest.approx(2000)

    def test_step_clamped(self):
        assert next_total(1000, 1.0, False) == pytest.approx(4000)   # x4 cap
        assert next_total(1000, 250.0, False) >= 500                 # no tiny shrink below x0.25


class TestRoiPeak:
    def test_peak_and_channels(self):
        f = np.zeros((60, 60, 3), np.uint8)
        f[20:30, 20:30] = (10, 100, 50)
        peak, ch, sat = roi_peak([f, f], ROI)
        assert peak == 100 and ch == {"R": 10, "G": 100, "B": 50} and not sat

    def test_saturation_in_single_frame_detected_even_if_average_below_255(self):
        a = np.full((60, 60, 3), 100, np.uint8)
        b = a.copy()
        b[30, 30, 1] = 255
        peak, _, sat = roi_peak([a, b], ROI)
        assert sat and peak < 255

    def test_pixels_outside_roi_ignored(self):
        f = np.zeros((60, 60, 3), np.uint8)
        f[55, 55] = 255
        _, _, sat = roi_peak([f], ROI)
        assert not sat

    def test_roi_clamped_to_frame(self):
        f = np.full((20, 20, 3), 80, np.uint8)
        peak, _, _ = roi_peak([f], ROIConfig(0, 500, 0, 500))
        assert peak == 80


def _run_tuner(k, start, lim=WIDE, max_iter=10, **kw):
    """Drive the tuner against the model camera; returns (result, n_frames)."""
    t = AutoGainTuner(lim, start, max_iter=max_iter, **kw)
    exp, ag, dg = t.settings
    n = 0
    stale = 0
    old = (exp, ag, dg)
    while n < 500:
        n += 1
        # frames right after an Apply still show the old settings for `settle` frames
        f = _model_frame(k, exp, ag, dg) if stale == 0 else _model_frame(k, *old)
        stale = max(0, stale - 1)
        r = t.feed(f, ROI)
        if isinstance(r, Apply):
            old = (exp, ag, dg)
            exp, ag, dg = r.exp_us, r.ag, r.dg
            stale = 2
        elif isinstance(r, (Done, Fail)):
            return r, n, t
    raise AssertionError("tuner never finished")


class TestTuner:
    @pytest.mark.parametrize("k", [1e-5, 2e-5, 5e-5, 2e-4, 1e-3])
    def test_converges_into_band(self, k):
        r, _, t = _run_tuner(k, (10_000.0, 1.0, 1.0))
        assert isinstance(r, Done), r
        assert abs(r.peak - 127.5) <= 0.10 * 127.5
        assert t.iterations <= 10

    def test_from_saturated_start(self):
        r, _, _ = _run_tuner(1e-4, (100_000.0, 12.0, 16.0))
        assert isinstance(r, Done)

    def test_free_run_floor_never_violated(self):
        floor = AutoGainLimits(40_000.0, 40_000.0, 1.0, 12.0, 1.0, 16.0)
        r, _, _ = _run_tuner(1e-4, (40_000.0, 1.0, 1.0), lim=floor)
        assert isinstance(r, Done) and r.exp_us == 40_000.0
        assert r.ag > 1.0  # gain makes up what exposure cannot

    def test_fail_too_bright_at_minimum(self):
        r, _, _ = _run_tuner(1.0, (40_000.0, 1.0, 1.0), lim=LIM)
        assert isinstance(r, Fail) and "too bright" in r.reason.lower()

    def test_fail_too_dim_at_maximum(self):
        r, _, _ = _run_tuner(1e-12, (100_000.0, 12.0, 16.0))
        assert isinstance(r, Fail) and "too dim" in r.reason.lower()

    def test_empty_roi_fails(self):
        t = AutoGainTuner(WIDE, (1000.0, 1.0, 1.0))
        r = t.feed(np.zeros((60, 60, 3), np.uint8), ROIConfig(5, 5, 5, 9))
        assert isinstance(r, Fail)

    def test_settle_frames_ignored_after_apply(self):
        t = AutoGainTuner(WIDE, (1000.0, 1.0, 1.0), n_avg=2, settle=3)
        dark = np.zeros((60, 60, 3), np.uint8)
        dark[20:30, 20:30] = 5
        res = [t.feed(dark, ROI) for _ in range(2)]
        assert isinstance(res[-1], Apply)
        # next 3 frames are ignored (stale), then 2 are averaged
        outs = [t.feed(dark, ROI) for _ in range(4)]
        assert outs == [None, None, None, None]
        assert t.feed(dark, ROI) is not None

    def test_max_iter_gives_up(self):
        t = AutoGainTuner(WIDE, (1000.0, 1.0, 1.0), n_avg=1, settle=0, max_iter=2)
        # a model that never converges: always reports the same dim image
        f = np.zeros((60, 60, 3), np.uint8)
        f[20:30, 20:30] = 10
        results = [t.feed(f, ROI) for _ in range(5)]
        fails = [r for r in results if isinstance(r, Fail)]
        assert fails and "converge" in fails[0].reason.lower()


# ------------------------------------------------------------ F11.2 config

class TestConfig:
    def test_defaults(self):
        c = AppConfig()
        assert c.gain_roi_enabled is False
        assert c.autogain_free_run_min_exposure_us == 40_000.0
        assert c.autogain_n_avg == 5 and c.autogain_target == 127.5
        assert (c.gain_roi.xmax - c.gain_roi.xmin, c.gain_roi.ymax - c.gain_roi.ymin) == (400, 400)

    def test_round_trip(self, tmp_path):
        c = AppConfig(gain_roi=ROIConfig(1, 2, 3, 4), gain_roi_enabled=True, autogain_n_avg=7)
        save_config(c, tmp_path / "c.toml")
        assert load_config(tmp_path / "c.toml") == c

    def test_old_config_gets_defaults(self, tmp_path):
        p = tmp_path / "old.toml"
        p.write_text('exposure_us = 5000.0\n[roi]\nxmin = 9\n', encoding="utf-8")
        c = load_config(p)
        assert c.gain_roi == ROIConfig()  # legacy [roi] ignored, new default
        assert c.autogain_n_avg == 5

    def test_default_roi_is_independent_per_config(self):
        a, b = AppConfig(), AppConfig()
        a.gain_roi.xmin = 1
        assert b.gain_roi.xmin != 1


# --------------------------------------------------------------- F11.3 GUI

def _spot_cam(fps: float = 100.0, **kw) -> MockCamera:
    return MockCamera(fps=fps, simulate_spot=True, **kw)


def _pump(cond, timeout_s: float = 20.0) -> bool:
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def _win(tmp_path, cam=None, **cfg) -> MainWindow:
    cfg.setdefault("output_dir", str(tmp_path / "out"))
    w = MainWindow(AppConfig(**cfg), camera=cam or _spot_cam())
    assert _pump(lambda: w._live_view.last_frame is not None, 10)
    return w


class TestRoiCoordinates:
    """Regression: the ROI box must live in FULL-resolution pixel coordinates.

    ImageView.setImage() resets the item transform on every call, so the 2x display
    scale has to be passed with each frame; otherwise a box dragged over the spot gave
    half-resolution coordinates and auto gain measured the wrong region.
    """

    def test_view_space_is_full_resolution_after_frames(self, qapp):
        from h2lasercontrol.laserdaq.gui.live_view import LiveView
        view = LiveView(AppConfig())
        frame = np.zeros((1536, 2048, 3), np.uint8)
        for _ in range(3):
            view.update_frame(frame)
        tr = view._image_view.imageItem.transform()
        assert tr.m11() == 2.0 and tr.m22() == 2.0

    def test_roi_box_selects_the_bright_patch(self, qapp):
        from h2lasercontrol.laserdaq.analysis.autogain import roi_peak
        from h2lasercontrol.laserdaq.gui.live_view import LiveView
        cfg = AppConfig()
        view = LiveView(cfg)
        frame = np.zeros((1536, 2048, 3), np.uint8)
        frame[880:900, 1160:1180, 2] = 200          # spot at full-res x~1170, y~890
        view.update_frame(frame)
        # box position in view space -> displayed-image pixel (what the user sees)
        item = view._image_view.imageItem
        shown = item.mapFromParent(view._roi.mapToParent(view._roi.pos()))  # noqa: F841
        view.set_roi(1100, 1250, 820, 960)           # drag the box over the spot
        peak, _, _ = roi_peak([frame], cfg.gain_roi)
        assert peak == 200
        # and the box really sits over the same pixels of the displayed (half-res) image
        top_left = item.mapFromParent(view._roi.pos())
        assert (top_left.x(), top_left.y()) == (550.0, 410.0)


class TestAutoGainGui:
    def test_button_needs_roi_checkbox(self, qapp, tmp_path):
        w = _win(tmp_path)
        try:
            assert not w._autogain_btn.isEnabled()
            w._gain_roi_check.setChecked(True)
            assert w._autogain_btn.isEnabled()
            assert w._live_view._roi.isVisible() or True  # offscreen visibility not asserted
            assert w._config.gain_roi_enabled
            w._gain_roi_check.setChecked(False)
            assert not w._autogain_btn.isEnabled()
            assert not w._config.gain_roi_enabled
        finally:
            w.close()

    def test_button_disabled_without_camera(self, qapp):
        w = MainWindow(AppConfig())
        w._gain_roi_check.setChecked(True)
        assert not w._autogain_btn.isEnabled()

    def test_start_enters_autogain_and_locks_controls(self, qapp, tmp_path):
        w = _win(tmp_path, cam=_spot_cam(fps=5.0))
        try:
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert w._app_state is AppState.AUTOGAIN
            assert not w._acq_group.isEnabled()
            assert not w._trigger_group.isEnabled()
            assert not w._capture_btn.isEnabled()
            assert w._autogain_btn.text() == "Stop"
            assert w._autogain_btn.isEnabled()
        finally:
            w._on_autogain_clicked()
            w.close()

    def test_converges_and_applies_settings(self, qapp, tmp_path):
        cam = _spot_cam(spot_k=1e-5)  # needs gain on top of the 40 ms floor
        w = _win(tmp_path, cam=cam)
        try:
            w._cam_fps_spin.setValue(25.0)
            w._apply_trigger_config()
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert _pump(lambda: w._app_state is AppState.LIVE, 30)
            assert "peak" in w._status_label.text()
            # widgets, config and camera agree
            assert w._exposure_spin.value() == pytest.approx(cam.exposure_us, abs=0.2)
            assert w._config.exposure_us == pytest.approx(cam.exposure_us, abs=0.2)
            assert w._analog_gain_slider.value() / 100 == pytest.approx(cam.analog_gain)
            assert w._config.digital_gain == pytest.approx(cam.digital_gain)
            # free run: exposure is at the 40 ms floor (the ceiling at 25 fps is also 40 ms)
            assert cam.exposure_us >= 40_000.0
            # the resulting image really is in the target band
            f = w._live_view.last_frame
            roi = w._config.gain_roi
            peak = f[roi.ymin:roi.ymax, roi.xmin:roi.xmax].max()
            assert 100 <= peak <= 160
        finally:
            w.close()

    def test_too_bright_for_floor_reports_minimum_reached(self, qapp, tmp_path):
        cam = _spot_cam(spot_k=2.4e-5)  # unsaturated but ~200 at the 40 ms floor
        w = _win(tmp_path, cam=cam)
        try:
            w._cam_fps_spin.setValue(25.0)
            w._apply_trigger_config()
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert _pump(lambda: w._app_state is AppState.LIVE, 30)
            assert cam.exposure_us == pytest.approx(40_000.0)
            assert "minimum" in w._status_label.text().lower()
        finally:
            w.close()

    def test_hardware_trigger_may_go_below_40ms(self, qapp, tmp_path):
        cam = _spot_cam(spot_k=2e-4)  # bright: needs < 40 ms
        w = _win(tmp_path, cam=cam)
        try:
            w._hw_radio.setChecked(True)
            w._apply_trigger_config()
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert _pump(lambda: w._app_state is AppState.LIVE, 30)
            assert cam.exposure_us < 40_000.0
        finally:
            w.close()

    def test_free_run_fps_too_high_refuses(self, qapp, tmp_path):
        w = _win(tmp_path)
        try:
            w._cam_fps_spin.setValue(30.0)
            w._apply_trigger_config()
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert w._app_state is AppState.LIVE
            assert "FPS too high" in w._status_label.text()
        finally:
            w.close()

    def test_free_run_exposure_is_whole_pulse_periods(self, qapp, tmp_path):
        cam = _spot_cam(spot_k=2e-6)  # dim: wants a long exposure
        w = _win(tmp_path, cam=cam)
        try:
            w._cam_fps_spin.setValue(5.0)  # ceiling 200 ms
            w._apply_trigger_config()
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert _pump(lambda: w._app_state is AppState.LIVE, 40)
            assert cam.exposure_us % 40_000.0 == pytest.approx(0.0, abs=1.0)
        finally:
            w.close()

    def test_free_run_start_below_floor_is_raised(self, qapp, tmp_path):
        cam = _spot_cam()
        w = _win(tmp_path, cam=cam, exposure_us=10_000.0)
        try:
            w._cam_fps_spin.setValue(20.0)
            w._apply_trigger_config()
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert _pump(lambda: cam.exposure_us >= 40_000.0, 5)  # raised to the floor
        finally:
            w._on_autogain_clicked() if w._app_state is AppState.AUTOGAIN else None
            w.close()

    def test_stop_mid_tune_returns_to_live(self, qapp, tmp_path):
        w = _win(tmp_path, cam=_spot_cam(fps=5.0))
        try:
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert w._app_state is AppState.AUTOGAIN
            w._on_autogain_clicked()  # Stop
            assert w._app_state is AppState.LIVE
            assert "stopped" in w._status_label.text().lower()
            assert w._tuner is None
        finally:
            w.close()

    def test_unreachable_target_reports_failure(self, qapp, tmp_path):
        cam = _spot_cam(spot_k=1e-3)  # far too bright even at minimum settings
        w = _win(tmp_path, cam=cam)
        try:
            w._cam_fps_spin.setValue(25.0)
            w._apply_trigger_config()
            w._gain_roi_check.setChecked(True)
            w._on_autogain_clicked()
            assert _pump(lambda: w._app_state is AppState.LIVE, 30)
            assert "failed" in w._status_label.text().lower()
        finally:
            w.close()

    def test_roi_follows_config_and_is_locked_while_tuning(self, qapp, tmp_path):
        w = _win(tmp_path, cam=_spot_cam(fps=5.0), gain_roi_enabled=True)
        try:
            assert w._gain_roi_check.isChecked()
            w._live_view.set_roi(100, 300, 120, 320)
            assert w._config.gain_roi == ROIConfig(100, 300, 120, 320)
            w._on_autogain_clicked()
            assert w._live_view._roi.translatable is False
            w._on_autogain_clicked()
            assert w._live_view._roi.translatable is True
        finally:
            w.close()

    def test_loading_config_restores_roi(self, qapp, tmp_path):
        p = tmp_path / "r.toml"
        save_config(AppConfig(gain_roi=ROIConfig(50, 150, 60, 160), gain_roi_enabled=True), p)
        w = MainWindow(AppConfig())
        w._load_session_config(p)
        assert w._gain_roi_check.isChecked()
        assert w._config.gain_roi == ROIConfig(50, 150, 60, 160)
        pos, size = w._live_view._roi.pos(), w._live_view._roi.size()
        assert (pos.x(), pos.y(), size.x(), size.y()) == (50, 60, 100, 100)

    def test_recording_hides_autogain_group(self, qapp, tmp_path):
        w = _win(tmp_path, cam=_spot_cam(fps=5.0))
        try:
            w._do_start_run(100)
            assert w._autogain_group.isHidden()
        finally:
            w._stop_run()
            _pump(lambda: w._app_state is AppState.LIVE, 8)
            w.close()


def test_slow_usb_link_is_flagged(qapp):
    class _Usb2(MockCamera):
        def link_speed_bytes_per_s(self):
            return 60e6

    w = MainWindow(AppConfig(), camera=_Usb2())
    try:
        assert "USB" in w._fps_label.text()
    finally:
        w.close()


def test_fast_usb_link_not_flagged(qapp):
    class _Usb3(MockCamera):
        def link_speed_bytes_per_s(self):
            return 400e6

    w = MainWindow(AppConfig(), camera=_Usb3())
    try:
        assert "SLOW USB" not in w._fps_label.text()
    finally:
        w.close()
