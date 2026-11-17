"""Device drivers and a factory that builds them from config/devices.toml."""

from __future__ import annotations

import os
from pathlib import Path

from ..config import DEFAULT_CONFIG, DeviceConfig, resolve_port
from ..energy import AngleStore
from ..oplog import OpLog
from ..transport import D2xxTransport, SerialTransport, Transport
from .base import Aborted, DeviceError, DeviceTimeout, Driver, action
from .ell14 import Ell14
from .hitmv import Axis, HitMv
from .mff import FlipUnit, Mff

__all__ = [
    "Aborted",
    "Axis",
    "DeviceError",
    "DeviceTimeout",
    "Driver",
    "Ell14",
    "FlipUnit",
    "HitMv",
    "Mff",
    "action",
    "create_driver",
]


def create_driver(cfg: DeviceConfig, oplog: OpLog | None = None,
                  transport: Transport | dict[str, Transport] | None = None,
                  state_dir: str | os.PathLike[str] | None = None) -> Driver:
    """Build the driver for one configured device. Without `transport`, a SerialTransport on
    the port found by USB serial number is used (not opened yet: call `connect`).
    Flip mounts (`mff`): one D2XX transport per unit, or `transport` = {unit key: Transport}.
    `state_dir`: where program-written state lives (saved_angles.json); default config/."""
    s = cfg.settings
    if cfg.type == "mff":
        units = []
        for ukey, u in s.get("units", {}).items():
            t = (transport[ukey] if isinstance(transport, dict)
                 else D2xxTransport(str(u["usb_serial"]), cfg.baudrate, rtscts=cfg.rtscts,
                                    name=f"{cfg.key}.{ukey}"))
            units.append(FlipUnit(ukey, u.get("label", ukey), str(u["usb_serial"]), t,
                                  insert_position=int(u.get("insert_position", 2))))
        return Mff(cfg.key, units, oplog, move_timeout=float(s.get("move_timeout_s", 3)))
    if isinstance(transport, dict):
        raise TypeError(f"{cfg.key}: one transport expected")
    if transport is None:
        transport = SerialTransport(resolve_port(cfg), cfg.baudrate, rtscts=cfg.rtscts,
                                    name=cfg.key)
    if cfg.type == "ell14":
        return Ell14(
            cfg.key, transport, oplog,
            address=s.get("address", "0"),
            terminator=s.get("terminator", "\x07").encode("ascii"),
            positions={k: float(v) for k, v in s.get("positions", {}).items()},
            angle_store=AngleStore(Path(state_dir or DEFAULT_CONFIG.parent) / "saved_angles.json"),
        )
    if cfg.type == "hitmv":
        axes = {}
        for num, a in s.get("axes", {}).items():
            pos = a.get("positions", {})
            axes[int(num)] = Axis(int(num), a["name"], inserted=int(pos.get("INSERTED", 0)),
                                  retracted=int(pos.get("RETRACTED", 30000000)))
        return HitMv(
            cfg.key, transport, oplog,
            axes=axes,
            homing_max_speed=s.get("homing_max_speed") or None,
            exclusive_axes=bool(s.get("exclusive_axes", True)),
            speed=tuple(s.get("speed", (100000, 1000000, 200))),
            insert_timeout=float(s.get("insert_timeout_s", 120)),
            move_timeout=float(s.get("move_timeout_s", 90)),
        )
    raise ValueError(f"{cfg.key}: unknown device type {cfg.type!r}")
