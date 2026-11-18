"""PicoScope config files: `config/picoscope/*.toml` (the old H2LaserDAQ `config/*.py` files).

One file = one acquisition setup: `title`, `mode` ("continuous" | "snapshot") and
`[digitizers.<name>]` tables with exactly the old DIGITIZER_CONFIGS keys. Each PicoScope tab
offers the files of its mode in a drop-down on its start page (user 2026-11-18).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODES = ("continuous", "snapshot")
REQUIRED = ("model", "serial", "channels", "channel_name", "voltage_range", "timebase",
            "sample_number", "trigger_channel", "trigger_level", "pre_trigger", "trigger_edge",
            "auto_trigger", "output_name")
REQUIRED_3405D = ("offset", "trigger_delay")
REQUIRED_SNAPSHOT = ("snapshot_channel", "refresh_trigger_cnt")


class ScopeConfigError(Exception):
    pass


@dataclass
class ScopeConfig:
    path: Path
    title: str
    mode: str
    digitizers: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name

    def settings(self) -> dict[str, Any]:
        """The dict PicoSession takes."""
        return {"mode": self.mode, "digitizers": self.digitizers, "config": self.name}


def load_scope_config(path: str | os.PathLike[str]) -> ScopeConfig:
    path = Path(path)
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ScopeConfigError(f"{path.name}: cannot be read ({e})") from e
    mode = data.get("mode")
    if mode not in MODES:
        raise ScopeConfigError(f"{path.name}: mode must be 'continuous' or 'snapshot', "
                               f"not {mode!r}")
    digs = data.get("digitizers") or {}
    if not digs:
        raise ScopeConfigError(f"{path.name}: no [digitizers.<name>] table")
    if mode == "snapshot" and len(digs) != 1:
        raise ScopeConfigError(f"{path.name}: snapshot mode needs exactly one digitizer")
    for name, d in digs.items():
        need = REQUIRED + (REQUIRED_3405D if d.get("model") == "3405D" else ()) + (
            REQUIRED_SNAPSHOT if mode == "snapshot" else ())
        missing = [k for k in need if k not in d]
        if missing:
            raise ScopeConfigError(f"{path.name}: [digitizers.{name}] is missing "
                                   + ", ".join(missing))
        if d["model"] not in ("3405D", "2204A"):
            raise ScopeConfigError(f"{path.name}: [digitizers.{name}] model must be "
                                   f"'3405D' or '2204A', not {d['model']!r}")
        if len(d["channels"]) != len(d["channel_name"]):
            raise ScopeConfigError(f"{path.name}: [digitizers.{name}] channels and "
                                   "channel_name must have the same length")
        for ch in d["channels"]:
            if ch not in d["voltage_range"]:
                raise ScopeConfigError(f"{path.name}: [digitizers.{name}] no voltage_range "
                                       f"for channel {ch}")
    return ScopeConfig(path, str(data.get("title", path.stem)), mode, digs)


def list_scope_configs(directory: str | os.PathLike[str], mode: str | None = None
                       ) -> tuple[list[ScopeConfig], list[str]]:
    """Valid configs (of `mode`, sorted by file name) and error texts of the invalid files."""
    configs, errors = [], []
    for p in sorted(Path(directory).glob("*.toml")):
        try:
            c = load_scope_config(p)
        except ScopeConfigError as e:
            errors.append(str(e))
            continue
        if mode is None or c.mode == mode:
            configs.append(c)
    return configs, errors
