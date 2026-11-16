"""Load config/devices.toml and resolve COM ports by USB serial number."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "devices.toml"


class ConfigError(Exception):
    pass


class PortNotFound(ConfigError):
    pass


@dataclass
class DeviceConfig:
    key: str
    type: str
    usb_serial: str | None
    port: str | None
    baudrate: int
    rtscts: bool = False
    settings: dict[str, Any] = field(default_factory=dict)  # the whole TOML table


def load_config(path: str | os.PathLike[str] = DEFAULT_CONFIG) -> dict[str, DeviceConfig]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    devices = {}
    for key, table in data.get("devices", {}).items():
        try:
            devices[key] = DeviceConfig(
                key=key,
                type=table["type"],
                usb_serial=table.get("usb_serial"),
                port=table.get("port"),
                baudrate=int(table["baudrate"]),
                rtscts=bool(table.get("rtscts", False)),
                settings=table,
            )
        except KeyError as e:
            raise ConfigError(f"[devices.{key}] is missing {e}") from e
        if not (devices[key].usb_serial or devices[key].port):
            raise ConfigError(f"[devices.{key}] needs usb_serial or port")
    return devices


def resolve_port(cfg: DeviceConfig, ports: list[Any] | None = None) -> str:
    """COM port for a device. By USB serial number if configured (COM numbers can change).

    If `usb_serial` is set but not found, this is an error: falling back to the configured COM
    number could open a *different* device. `port` is used only when `usb_serial` is not set.
    `ports` = objects with `.device` and `.serial_number` (default: pyserial's comports())."""
    if not cfg.usb_serial:
        assert cfg.port
        return cfg.port
    if ports is None:
        from serial.tools import list_ports

        ports = list(list_ports.comports())
    for p in ports:
        if p.serial_number == cfg.usb_serial:
            return p.device
    found = ", ".join(f"{p.device}={p.serial_number}" for p in ports) or "none"
    raise PortNotFound(
        f"{cfg.key}: no COM port with USB serial {cfg.usb_serial} (last known {cfg.port}). "
        f"Is it plugged in and powered? Ports found: {found}"
    )
