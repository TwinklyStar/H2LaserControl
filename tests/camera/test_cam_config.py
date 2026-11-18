"""Tests for config.py — round-trip TOML, defaults, legacy-key handling."""
from __future__ import annotations

import dataclasses
import pathlib

import pytest

from h2lasercontrol.laserdaq.config import AppConfig, load_config, save_config

CONFIGS_DIR = pathlib.Path(__file__).resolve().parents[2] / "config" / "camera"

_REMOVED_FIELDS = (
    "analysis_enabled", "subtract_background", "use_calibration", "channel",
    "cal_roi", "seed", "background_path", "mm_per_px",
    "save_blue_png", "save_overlay_png", "save_csv", "dev_signal_path",
)


def test_roundtrip_defaults(tmp_path):
    cfg = AppConfig()
    path = tmp_path / "cfg.toml"
    save_config(cfg, path)
    assert load_config(path) == cfg


def test_roundtrip_all_fields_modified(tmp_path):
    cfg = AppConfig(
        output_dir="runs/2026",
        save_root=False,
        save_rgb_png=False,
        exposure_us=40_000.0,
        exposure_max=True,
        analog_gain=2.5,
        digital_gain=1.5,
    )
    path = tmp_path / "modified.toml"
    save_config(cfg, path)
    assert load_config(path) == cfg


def test_removed_fields_are_gone():
    names = {f.name for f in dataclasses.fields(AppConfig)}
    for removed in _REMOVED_FIELDS:
        assert removed not in names


def test_legacy_keys_and_tables_are_ignored(tmp_path):
    """A pre-Feature-9 TOML (analysis keys + [roi]/[cal_roi]/[seed]) still loads."""
    path = tmp_path / "legacy.toml"
    path.write_text(
        'analysis_enabled = true\n'
        'subtract_background = true\n'
        'channel = "B"\n'
        'background_path = "bg.bmp"\n'
        'mm_per_px = 0.05\n'
        'output_dir = "legacy_out"\n'
        'save_blue_png = true\n'
        'exposure_us = 12345.0\n'
        'analog_gain = 3.0\n'
        '\n[roi]\nxmin = 1\nxmax = 2\nymin = 3\nymax = 4\n'
        '\n[cal_roi]\nxmin = 1\nxmax = 2\nymin = 3\nymax = 4\n'
        '\n[seed]\nA = 40.0\nx0 = 1.0\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.output_dir == "legacy_out"
    assert cfg.exposure_us == 12345.0
    assert cfg.analog_gain == 3.0
    assert cfg.digital_gain == 1.0
    saved = tmp_path / "resaved.toml"
    save_config(cfg, saved)
    text = saved.read_text(encoding="utf-8")
    for removed in _REMOVED_FIELDS:
        assert removed not in text
    assert "[roi]" not in text  # legacy table gone; the new one is [gain_roi]


def test_old_gain_key_maps_to_analog_gain(tmp_path):
    path = tmp_path / "old_gain.toml"
    path.write_text("gain = 5.0\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.analog_gain == 5.0
    assert cfg.digital_gain == 1.0


def test_default_toml_file_loads():
    cfg = load_config(CONFIGS_DIR / "default.toml")
    assert cfg.output_dir == "data/camera"  # H2LaserControl merge (was "output")


@pytest.mark.parametrize("toml_path", sorted(CONFIGS_DIR.glob("*.toml")), ids=lambda p: p.name)
def test_every_shipped_config_loads(toml_path):
    cfg = load_config(toml_path)
    assert isinstance(cfg, AppConfig)
