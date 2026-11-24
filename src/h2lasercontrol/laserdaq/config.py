"""Typed config dataclass + TOML loader/saver."""
from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ROIConfig:
    xmin: int = 824    # default: 400 x 400 box centred in a 2048 x 1536 frame
    xmax: int = 1224
    ymin: int = 568
    ymax: int = 968


@dataclass
class AppConfig:
    output_dir: str = "data/camera"  # H2LaserControl merge (was "output")

    # Output toggles
    save_root: bool = True
    save_rgb_png: bool = True

    # Acquisition settings (µs for exposure, linear for gain)
    exposure_us: float = 10_000.0
    exposure_max: bool = False  # pin exposure to hardware ceiling
    analog_gain: float = 1.0
    digital_gain: float = 1.0

    # Trigger (H2LaserControl, Shifter tab F9c): "free_run" or "hardware", and the free-run
    # frame rate. Empty / 0 = not stored: loading the file leaves the camera's trigger as it is.
    # Written only when set, so files without them stay unchanged.
    trigger_mode: str = ""
    trigger_fps: float = 0.0

    # Auto gain (Feature 11): ROI over the laser spot; NOT a fit ROI
    gain_roi: ROIConfig = field(default_factory=ROIConfig)
    gain_roi_enabled: bool = False
    autogain_free_run_min_exposure_us: float = 40_000.0  # one laser pulse; free run only
    autogain_n_avg: int = 5
    autogain_target: float = 127.5

    # Set automatically when a recording starts (ISO time); empty in hand-written configs.
    timestamp: str = ""


def _write_toml(d: dict, prefix: str = "") -> list[str]:
    """Convert a dataclasses.asdict() dict to TOML lines, handling sub-tables."""
    simple: list[str] = []
    tables: list[tuple[str, dict]] = []

    for k, v in d.items():
        if isinstance(v, dict):
            tables.append((k, v))
        elif isinstance(v, bool):
            simple.append(f"{k} = {'true' if v else 'false'}")
        elif v is None:
            simple.append(f'{k} = ""')
        elif isinstance(v, str):
            escaped = v.replace("\\", "\\\\")
            simple.append(f'{k} = "{escaped}"')
        elif isinstance(v, int):
            simple.append(f"{k} = {v}")
        elif isinstance(v, float):
            simple.append(f"{k} = {v!r}")
        else:
            raise TypeError(f"Cannot serialize type {type(v).__name__!r} for key {k!r}")

    lines = simple[:]
    for k, v in tables:
        section = f"{prefix}.{k}" if prefix else k
        lines.append(f"\n[{section}]")
        lines.extend(_write_toml(v, section))
    return lines


def save_config(cfg: AppConfig, path: str | Path) -> None:
    """Write *cfg* to a TOML file at *path*."""
    d = asdict(cfg)
    for key, unset in (("trigger_mode", ""), ("trigger_fps", 0.0)):
        if d.get(key) == unset:
            del d[key]
    lines = _write_toml(d)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_config(path: str | Path) -> AppConfig:
    """Load an AppConfig from a TOML file at *path*."""
    with open(path, "rb") as f:
        data = tomllib.load(f)

    # Keep [gain_roi]; drop sub-tables left over from removed features ([roi], [seed], ...).
    roi_tbl = data.get("gain_roi")
    data = {k: v for k, v in data.items() if not isinstance(v, dict)}
    if isinstance(roi_tbl, dict):
        roi_fields = {f.name for f in dataclasses.fields(ROIConfig)}
        data["gain_roi"] = ROIConfig(**{k: int(v) for k, v in roi_tbl.items() if k in roi_fields})

    # Backward compat: old TOML key 'gain' maps to 'analog_gain'
    if "gain" in data:
        if "analog_gain" not in data:
            data["analog_gain"] = data.pop("gain")
        else:
            data.pop("gain")

    app_fields = {f.name for f in dataclasses.fields(AppConfig)}
    return AppConfig(**{k: v for k, v in data.items() if k in app_fields})
