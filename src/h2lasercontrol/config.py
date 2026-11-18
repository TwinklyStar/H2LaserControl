"""Load config/devices.toml and resolve COM ports by USB serial number."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROGRAM_DIR = Path(__file__).resolve().parents[2]  # the project folder (data/, config/, logs/)
DEFAULT_CONFIG = PROGRAM_DIR / "config" / "devices.toml"
# streaming DAQ devices (F8): opened through vendor SDKs, no COM port / baud rate
DAQ_TYPES = {"picoscope", "ids_camera"}


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
        # a device with `units` (flip mounts) has one USB connection per unit, set per unit
        multi = "units" in table
        if table.get("type") in DAQ_TYPES:
            devices[key] = DeviceConfig(key=key, type=table["type"],
                                        usb_serial=table.get("usb_serial"), port=None,
                                        baudrate=0, settings=table)
            if table["type"] == "picoscope" and not table.get("digitizers"):
                raise ConfigError(f"[devices.{key}] needs [devices.{key}.digitizers.<name>]")
            continue
        try:
            devices[key] = DeviceConfig(
                key=key,
                type=table["type"],
                usb_serial=table.get("usb_serial"),
                port=table.get("port"),
                baudrate=int(table.get("baudrate", 115200) if multi else table["baudrate"]),
                rtscts=bool(table.get("rtscts", multi)),
                settings=table,
            )
        except KeyError as e:
            raise ConfigError(f"[devices.{key}] is missing {e}") from e
        if multi:
            for ukey, unit in table["units"].items():
                if not unit.get("usb_serial"):
                    raise ConfigError(f"[devices.{key}.units.{ukey}] needs usb_serial")
        elif not (devices[key].usb_serial or devices[key].port):
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
