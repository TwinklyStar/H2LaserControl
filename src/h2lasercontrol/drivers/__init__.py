"""Device drivers and a factory that builds them from config/devices.toml."""

from __future__ import annotations

from ..config import DeviceConfig, resolve_port
from ..oplog import OpLog
from ..transport import SerialTransport, Transport
from .base import Aborted, DeviceError, DeviceTimeout, Driver, action
from .ell14 import Ell14
from .hitmv import Axis, HitMv

__all__ = [
    "Aborted",
    "Axis",
    "DeviceError",
    "DeviceTimeout",
    "Driver",
    "Ell14",
    "HitMv",
    "action",
    "create_driver",
]


def create_driver(cfg: DeviceConfig, oplog: OpLog | None = None,
                  transport: Transport | None = None) -> Driver:
    """Build the driver for one configured device. Without `transport`, a SerialTransport on
    the port found by USB serial number is used (not opened yet: call `connect`)."""
    s = cfg.settings
    if transport is None:
        transport = SerialTransport(resolve_port(cfg), cfg.baudrate, rtscts=cfg.rtscts,
                                    name=cfg.key)
    if cfg.type == "ell14":
        return Ell14(
            cfg.key, transport, oplog,
            address=s.get("address", "0"),
            terminator=s.get("terminator", "\x07").encode("ascii"),
            positions={k: float(v) for k, v in s.get("positions", {}).items()},
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
            speed=tuple(s.get("speed", (100000, 1000000, 200))),
            insert_timeout=float(s.get("insert_timeout_s", 120)),
            move_timeout=float(s.get("move_timeout_s", 90)),
        )
    raise ValueError(f"{cfg.key}: unknown device type {cfg.type!r}")
