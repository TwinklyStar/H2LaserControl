"""Tests for Feature 1 — per-run config snapshot + config file selector.

F1.1  A run_config.toml is written once per recorded run (FrameRecorder).
F1.2  Config file selector combo box in the sidebar.
"""
from __future__ import annotations

import pathlib

import numpy as np

from h2lasercontrol.laserdaq.config import AppConfig, save_config
from h2lasercontrol.laserdaq.gui.main_window import MainWindow
from h2lasercontrol.laserdaq.storage.recorder import FrameRecorder


def _dummy_frame(H: int = 8, W: int = 10) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, (H, W, 3), dtype=np.uint8)


# ===========================================================================
# F1.1 — *_config.toml saved alongside every capture
# ===========================================================================

class TestConfigToml:

    def test_run_writes_one_config_toml(self, tmp_path):
        """A recorded run writes exactly one run_config.toml (not one per frame)."""
        cfg = AppConfig(output_dir=str(tmp_path / "out"))
        rec = FrameRecorder(tmp_path / "out" / "run", config=cfg)
        rec.start()
        for _ in range(3):
            rec.submit(_dummy_frame())
        rec.stop()
        toml_files = list(pathlib.Path(tmp_path / "out").rglob("*.toml"))
        assert [f.name for f in toml_files] == ["run_config.toml"]

    def test_config_snapshot_matches_settings(self, tmp_path):
        from h2lasercontrol.laserdaq.config import load_config
        cfg = AppConfig(exposure_us=42_000.0, analog_gain=2.5)
        rec = FrameRecorder(tmp_path / "run", config=cfg)
        rec.start()
        rec.stop()
        back = load_config(tmp_path / "run" / "run_config.toml")
        assert back.exposure_us == 42_000.0
        assert back.analog_gain == 2.5


# ===========================================================================
# F1.2 — Config file selector
# ===========================================================================

class TestConfigSelector:

    def test_startup_combo_shows_default_toml(self, qapp):
        """On startup the combo box displays 'default.toml'."""
        window = MainWindow(AppConfig())
        assert window._config_combo.currentText() == "default.toml"

    def test_load_session_config_replaces_config(self, qapp, tmp_path):
        """_load_session_config() replaces self._config with the loaded values."""
        custom = AppConfig(output_dir="custom_out", exposure_us=33_000.0, analog_gain=2.0)
        toml_path = tmp_path / "custom.toml"
        save_config(custom, toml_path)

        window = MainWindow(AppConfig())
        window._load_session_config(toml_path)

        assert window._config.output_dir == "custom_out"
        assert window._config.exposure_us == 33_000.0
        assert window._config.analog_gain == 2.0

    def test_load_session_config_updates_gain_slider(self, qapp, tmp_path):
        """Gain slider and label reflect the loaded config."""
        toml_path = tmp_path / "gain.toml"
        save_config(AppConfig(analog_gain=3.0, digital_gain=2.0), toml_path)

        window = MainWindow(AppConfig())
        window._load_session_config(toml_path)

        assert window._analog_gain_slider.value() == 300
        assert window._digital_gain_slider.value() == 200
        assert window._analog_gain_label.text() == "3.00"

    def test_load_invalid_config_shows_error(self, qapp, tmp_path):
        """A non-existent path shows an error in the status label."""
        window = MainWindow(AppConfig())
        window._load_session_config(tmp_path / "nonexistent.toml")
        assert "error" in window._status_label.text().lower()

    def test_load_invalid_config_preserves_existing_config(self, qapp, tmp_path):
        """Loading a bad path leaves self._config unchanged."""
        cfg = AppConfig(output_dir="keep_me")
        window = MainWindow(cfg)
        window._load_session_config(tmp_path / "nonexistent.toml")
        assert window._config.output_dir == "keep_me"

    def test_refresh_config_list_preserves_selection(self, qapp):
        """_refresh_config_list() keeps the current combo text if the file still exists."""
        window = MainWindow(AppConfig())
        initial = window._config_combo.currentText()
        assert initial  # at least default.toml
        window._refresh_config_list()
        assert window._config_combo.currentText() == initial
