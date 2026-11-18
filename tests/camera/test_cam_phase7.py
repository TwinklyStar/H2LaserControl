"""Tests for the multi-frame recording run in the GUI (state machine, BMP output)."""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtWidgets import QApplication

from h2lasercontrol.laserdaq.camera.mock import MockCamera
from h2lasercontrol.laserdaq.config import AppConfig
from h2lasercontrol.laserdaq.gui.main_window import AppState, MainWindow


def _cam(fps: float = 50.0) -> MockCamera:
    return MockCamera(items=[np.full((40, 40, 3), 90, np.uint8)], fps=fps)


def _wait_live(window: MainWindow, timeout_s: float = 8.0) -> None:
    t_end = time.monotonic() + timeout_s
    while time.monotonic() < t_end:
        QApplication.processEvents()
        time.sleep(0.01)
        if window._app_state is AppState.LIVE:
            return


def _window(tmp_path, fps: float = 50.0) -> MainWindow:
    return MainWindow(AppConfig(output_dir=str(tmp_path / "out")), camera=_cam(fps))


class TestRecordingRun:

    def test_run_without_camera_stays_live(self, qapp):
        window = MainWindow(AppConfig())
        window._do_start_run(3)
        assert window._app_state is AppState.LIVE

    def test_run_enters_running_state(self, qapp, tmp_path):
        window = _window(tmp_path, fps=5.0)  # slow camera: run cannot finish instantly
        try:
            window._do_start_run(100)
            assert window._app_state is AppState.RUNNING
            assert window._run_total == 100
        finally:
            window._stop_run()
            _wait_live(window)
            window.close()

    def test_run_completes_with_n_bmps(self, qapp, tmp_path):
        window = _window(tmp_path)
        try:
            window._do_start_run(5)
            _wait_live(window)
            assert window._app_state is AppState.LIVE
            bmps = list((tmp_path / "out").rglob("*.bmp"))
            assert len(bmps) == 5
            assert "Recorded 5/5" in window._status_label.text()
        finally:
            window.close()

    def test_stop_run_finalises_consistently(self, qapp, tmp_path):
        window = _window(tmp_path, fps=20.0)
        try:
            window._do_start_run(1000)
            t_end = time.monotonic() + 3
            while time.monotonic() < t_end and not list((tmp_path / "out").rglob("*.bmp")):
                QApplication.processEvents()
                time.sleep(0.02)
            window._stop_run()
            _wait_live(window)
            assert window._app_state is AppState.LIVE
            run = next((tmp_path / "out").rglob("frames.csv")).parent
            rows = (run / "frames.csv").read_text().strip().splitlines()[1:]
            assert len(rows) == len(list(run.glob("*.bmp")))
            assert 0 < len(rows) < 1000
        finally:
            window.close()

    def test_run_button_visible_in_live(self, qapp):
        window = MainWindow(AppConfig())
        assert not window._run_btn.isHidden()

    def test_stop_button_and_progress_visible_during_run(self, qapp, tmp_path):
        window = _window(tmp_path, fps=5.0)
        try:
            window._do_start_run(100)
            assert not window._stop_run_btn.isHidden()
            assert not window._run_progress_label.isHidden()
            assert window._acq_group.isHidden()
        finally:
            window._stop_run()
            _wait_live(window)
            window.close()

    def test_cannot_start_run_while_running(self, qapp, tmp_path):
        window = _window(tmp_path, fps=5.0)
        try:
            window._do_start_run(10)
            window._do_start_run(99)
            assert window._run_total == 10
        finally:
            window._stop_run()
            _wait_live(window)
            window.close()

    def test_display_fps_lowered_while_recording_and_restored(self, qapp, tmp_path):
        window = _window(tmp_path, fps=5.0)
        try:
            window._do_start_run(100)
            assert window._controller._min_interval == 1.0 / window._DISPLAY_FPS_RECORDING
            window._stop_run()
            _wait_live(window)
            assert window._controller._min_interval == 1.0 / window._DISPLAY_FPS_LIVE
        finally:
            window.close()

    def test_dropped_frames_shown_prominently(self, qapp, tmp_path):
        from pathlib import Path

        from h2lasercontrol.laserdaq.storage.recorder import RecordStats
        window = MainWindow(AppConfig())
        window._on_recording_finished(RecordStats(10, 8, 2, 1.0, 5.0, 9.0, Path("x")))
        assert "DROPPED" in window._status_label.text()
        assert "color" in window._status_label.styleSheet()
