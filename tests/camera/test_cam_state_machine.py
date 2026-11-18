"""Tests for the LIVE <-> RUNNING state machine and sidebar visibility."""
from __future__ import annotations

import numpy as np

from h2lasercontrol.laserdaq.config import AppConfig
from h2lasercontrol.laserdaq.gui.main_window import AppState, MainWindow


def _frame(H: int = 20, W: int = 30) -> np.ndarray:
    return np.random.default_rng(0).uniform(0, 255, (H, W, 3))


def test_app_states():
    assert {s.name for s in AppState} == {"LIVE", "RUNNING", "AUTOGAIN"}


def test_default_app_state_is_live(qapp):
    window = MainWindow(AppConfig())
    assert window._app_state is AppState.LIVE


def test_live_state_visibility(qapp):
    window = MainWindow(AppConfig())
    window._camera_ready = True  # simulate a working camera attached
    window._set_state(AppState.LIVE)
    assert window._capture_btn.isEnabled()
    assert not window._run_btn.isHidden()
    assert not window._acq_group.isHidden()
    assert not window._trigger_group.isHidden()
    assert window._run_progress_label.isHidden()
    assert window._stop_run_btn.isHidden()


def test_running_state_visibility(qapp):
    window = MainWindow(AppConfig())
    window._camera_ready = True
    window._set_state(AppState.RUNNING)
    assert not window._capture_btn.isEnabled()
    assert window._run_btn.isHidden()
    assert window._acq_group.isHidden()
    assert window._trigger_group.isHidden()
    assert not window._run_progress_label.isHidden()
    assert not window._stop_run_btn.isHidden()


def test_set_state_live_reverses_running(qapp):
    window = MainWindow(AppConfig())
    window._camera_ready = True
    window._set_state(AppState.RUNNING)
    window._set_state(AppState.LIVE)
    assert window._capture_btn.isEnabled()
    assert window._stop_run_btn.isHidden()


def test_capture_button_disabled_without_camera(qapp):
    window = MainWindow(AppConfig())
    window._set_state(AppState.LIVE)
    assert not window._capture_btn.isEnabled()


def test_capture_without_camera_stays_live(qapp, tmp_path):
    window = MainWindow(AppConfig(output_dir=str(tmp_path / "out")))
    window._do_capture_and_save()
    assert window._app_state is AppState.LIVE


def test_removed_widgets_are_gone(qapp):
    window = MainWindow(AppConfig())
    for name in (
        "_analysis_grp", "_seed_group", "_readout_group", "_cal_result_group",
        "_fit_btn", "_save_btn", "_cancel_btn", "_calibrate_btn", "_mode_actions",
    ):
        assert not hasattr(window, name), name
