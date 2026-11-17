"""Thorlabs MFF101 motorized flip mounts (APT binary protocol over FTDI D2XX).

One `Mff` driver handles all flip mounts shown on one GUI tab; each unit has its own USB
connection. A unit that is not plugged in is shown as offline (and retried every few seconds)
without blocking the others.

Protocol (docs/protocols.md § MFF101, verified on unit 37011815 on 2026-11-17):
- 6-byte header `id(2) p1 p2 dest src`; with data: `id(2) len(2) dest|0x80 src` + data.
  Host -> device: dest 0x50, src 0x01.
- MOT_MOVE_JOG `6A 04 01 dir 50 01`: dir 1 -> position 1, dir 2 -> position 2 ("go to", not
  toggle; repeating is harmless). A flip takes ~0.4 s. No MOVE_COMPLETED arrives -> poll.
- MOT_REQ_STATUSBITS `29 04 01 00 50 01` -> bits: 0x01 at position 1, 0x02 at position 2,
  0x10 moving (both directions). At position = limit bit set and not moving.
"""

from __future__ import annotations

import logging
import struct
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from ..oplog import OpLog
from ..transport import Transport, TransportError, TransportTimeout
from .base import DeviceError, DeviceTimeout, Driver, action

log = logging.getLogger(__name__)

HOST, USB = 0x01, 0x50
HW_REQ_INFO, HW_GET_INFO = 0x0005, 0x0006
MOD_IDENTIFY = 0x0223
MOT_MOVE_JOG = 0x046A
MOT_REQ_STATUSBITS, MOT_GET_STATUSBITS = 0x0429, 0x042A
MOT_REQ_MFF_OPERPARAMS, MOT_GET_MFF_OPERPARAMS = 0x0511, 0x0512

BIT_POS1, BIT_POS2 = 0x01, 0x02
BITS_MOVING = 0xF0  # 0x10 seen in both directions; 0x20/0x40/0x80 also mean motion


def header(msg_id: int, p1: int = 0, p2: int = 0) -> bytes:
    return struct.pack("<HBBBB", msg_id, p1, p2, USB, HOST)


def decode_position(bits: int) -> tuple[int | None, bool]:
    """(position 1 | 2 | None, moving)."""
    moving = bool(bits & BITS_MOVING)
    p1, p2 = bool(bits & BIT_POS1), bool(bits & BIT_POS2)
    if moving or p1 == p2:
        return None, moving
    return (1 if p1 else 2), False


def parse_info(data: bytes) -> dict[str, Any]:
    """HW_GET_INFO data (84 bytes, manual p. 59)."""
    serial, = struct.unpack_from("<I", data, 0)
    fw = data[14:18]
    hw, mod, nch = struct.unpack_from("<HHH", data, 78)
    return {
        "serial": str(serial),
        "model": data[4:12].split(b"\0")[0].decode("ascii", "replace"),
        "firmware": f"{fw[2]}.{fw[1]}.{fw[0]}",
        "notes": data[18:66].split(b"\0")[0].decode("ascii", "replace"),
        "hw_version": hw, "mod_state": mod, "channels": nch,
    }


@dataclass
class FlipUnit:
    key: str
    label: str
    usb_serial: str
    transport: Transport
    insert_position: int = 2  # which flipper position (1 or 2) is "insert"; the other "retract"
    error: str | None = None
    info: dict[str, Any] = field(default_factory=dict)
    last_try: float = 0.0

    def position_number(self, name: str) -> int:
        if name == "insert":
            return self.insert_position
        if name == "retract":
            return 3 - self.insert_position
        raise ValueError(f"unknown position {name!r} (insert or retract)")

    def position_name(self, number: int | None) -> str | None:
        if number is None:
            return None
        return "insert" if number == self.insert_position else "retract"


class Mff(Driver):
    device_type = "mff"

    def __init__(self, name: str, units: list[FlipUnit], oplog: OpLog | None = None, *,
                 move_timeout: float = 3.0, poll_interval: float = 0.05,
                 retry_interval: float = 5.0, reply_timeout: float = 1.0) -> None:
        if not units:
            raise ValueError(f"{name}: no flip mount units configured")
        super().__init__(name, units[0].transport, oplog)
        self.units = {u.key: u for u in units}
        self.move_timeout = move_timeout
        self.poll_interval = poll_interval
        self.retry_interval = retry_interval
        self.reply_timeout = reply_timeout
        self._wanted = False  # connected by the user -> offline units are retried

    # --- low level ----------------------------------------------------------------------------
    def _unit(self, key: str) -> FlipUnit:
        u = self.units.get(key)
        if u is None:
            raise ValueError(f"{self.name}: unknown unit {key!r} (configured: {list(self.units)})")
        if not u.transport.is_open:
            raise DeviceError(f"{u.label} is not connected" + (f": {u.error}" if u.error else ""))
        return u

    def _read_msg(self, u: FlipUnit, deadline: float) -> bytes:
        try:
            hdr = u.transport.read_exact(6, max(0.0, deadline - time.monotonic()))
            if hdr[4] & 0x80:
                n, = struct.unpack_from("<H", hdr, 2)
                return hdr + u.transport.read_exact(n, max(0.2, deadline - time.monotonic()))
            return hdr
        except TransportTimeout as e:
            raise DeviceTimeout(f"{u.label}: no reply from the flip mount") from e

    def _query(self, u: FlipUnit, tx: bytes, want: int, *, record: bool = True) -> bytes:
        """Send a request and return the reply with message id `want` (other messages that
        arrive in between, e.g. unsolicited ones, are skipped)."""
        u.transport.reset_input()
        u.transport.write(tx)
        deadline = time.monotonic() + self.reply_timeout
        while True:
            msg = self._read_msg(u, deadline)
            mid, = struct.unpack_from("<H", msg)
            if mid == want:
                if record:
                    self._record(tx, msg)
                return msg
            log.debug("%s: skipped message 0x%04X %s", u.key, mid, msg.hex(" "))

    def _send(self, u: FlipUnit, tx: bytes) -> None:
        u.transport.reset_input()
        u.transport.write(tx)
        self._record(tx, None)

    def _status_bits(self, u: FlipUnit, *, record: bool = True) -> int:
        msg = self._query(u, header(MOT_REQ_STATUSBITS, 1), MOT_GET_STATUSBITS, record=record)
        return struct.unpack_from("<I", msg, 8)[0]

    def _identify_unit(self, u: FlipUnit) -> dict[str, Any]:
        msg = self._query(u, header(HW_REQ_INFO), HW_GET_INFO)
        if len(msg) < 6 + 84:
            raise DeviceError(f"{u.label}: short identification reply")
        info = parse_info(msg[6:])
        if not info["model"].upper().startswith("MFF"):
            raise DeviceError(f"{u.label}: device is {info['model']!r}, not a flip mount (MFF)")
        if info["serial"] != u.usb_serial:
            raise DeviceError(f"{u.label}: serial {info['serial']} but {u.usb_serial} configured")
        return info

    def _open_unit(self, u: FlipUnit) -> dict[str, Any]:
        u.last_try = time.monotonic()
        try:
            u.transport.open()
            u.info = self._identify_unit(u)
        except (TransportError, DeviceError) as e:
            u.transport.close()
            u.error = str(e)
            return {"error": u.error}
        u.error = None
        return u.info

    def _lose(self, u: FlipUnit, e: Exception) -> None:
        log.warning("%s: %s lost: %s", self.name, u.key, e)
        u.transport.close()
        u.error = f"connection lost: {e}"
        u.last_try = time.monotonic()

    @contextmanager
    def _guard(self, u: FlipUnit) -> Iterator[None]:
        """A USB failure of one unit takes only that unit offline (DeviceError), not the tab."""
        try:
            yield
        except TransportError as e:
            self._lose(u, e)
            raise DeviceError(f"{u.label}: connection lost ({e})") from e

    # --- connection -----------------------------------------------------------------------------
    @action()
    def connect(self) -> dict[str, Any]:
        result = {u.key: self._open_unit(u) for u in self.units.values()}
        if not self.is_connected:
            raise DeviceError("; ".join(f"{u.label}: {u.error}" for u in self.units.values()))
        self._wanted = True
        return result

    @action()
    def disconnect(self) -> None:
        self._wanted = False
        for u in self.units.values():
            u.transport.close()
            u.error = None

    @property
    def is_connected(self) -> bool:
        return any(u.transport.is_open for u in self.units.values())

    def connection_text(self) -> str:
        n = sum(u.transport.is_open for u in self.units.values())
        where = [str(getattr(u.transport, "port", "") or "simulated")
                 for u in self.units.values() if u.transport.is_open]
        return f"{n} of {len(self.units)} units: {', '.join(where)}"

    def drop_connection(self) -> None:
        for u in self.units.values():
            u.transport.close()

    # --- read-only ------------------------------------------------------------------------------
    @action()
    def identify(self) -> dict[str, Any]:
        return {k: self._identify_unit(u) for k, u in self.units.items() if u.transport.is_open}

    @action()
    def status(self) -> dict[str, Any]:
        return self._state(record=True)

    def snapshot(self) -> dict[str, Any]:
        """Polled by the GUI (not logged). Retries offline units every `retry_interval` s.
        Raises only when no unit is reachable any more."""
        if self._wanted:
            for u in self.units.values():
                if not u.transport.is_open and time.monotonic() - u.last_try >= self.retry_interval:
                    self._open_unit(u)
        state = self._state(record=False)
        if not self.is_connected:
            raise TransportError("no flip mount reachable: "
                                 + "; ".join(f"{u.label}: {u.error}" for u in self.units.values()))
        return state

    def _state(self, *, record: bool) -> dict[str, Any]:
        units = {}
        for k, u in self.units.items():
            entry: dict[str, Any] = {"label": u.label, "connected": False, "error": u.error}
            if u.transport.is_open:
                try:
                    bits = self._status_bits(u, record=record)
                except (TransportError, DeviceError) as e:
                    self._lose(u, e)
                    entry["error"] = u.error
                else:
                    pos, moving = decode_position(bits)
                    entry.update(connected=True, error=None, position=u.position_name(pos),
                                 moving=moving, bits=f"0x{bits:08X}")
            units[k] = entry
        return {"units": units}

    @action()
    def get_transit_time(self, unit: str) -> int:
        """Flip time setting in ms (read-only; we never change device settings)."""
        u = self._unit(unit)
        with self._guard(u):
            msg = self._query(u, header(MOT_REQ_MFF_OPERPARAMS, 1), MOT_GET_MFF_OPERPARAMS)
        return struct.unpack_from("<i", msg, 8)[0]

    @action()
    def flash_led(self, unit: str) -> None:
        """Blink the unit's LED, to see which physical flip mount this is."""
        u = self._unit(unit)
        with self._guard(u):
            self._send(u, header(MOD_IDENTIFY))

    # --- motion -----------------------------------------------------------------------------------
    @action(moves=True)
    def insert(self, unit: str) -> dict[str, Any]:
        return self._flip(unit, "insert")

    @action(moves=True)
    def retract(self, unit: str) -> dict[str, Any]:
        return self._flip(unit, "retract")

    def _flip(self, key: str, name: str) -> dict[str, Any]:
        u = self._unit(key)
        with self._guard(u):
            return self._flip_unit(u, key, name)

    def _flip_unit(self, u: FlipUnit, key: str, name: str) -> dict[str, Any]:
        target = u.position_number(name)
        pos, moving = decode_position(self._status_bits(u))
        if pos == target and not moving:
            return {"unit": key, "position": name, "note": "already there"}
        # A flip cannot be stopped halfway (no stop message for the MFF); it takes ~0.5 s.
        self._send(u, header(MOT_MOVE_JOG, 1, target))
        t0 = time.monotonic()
        while True:
            time.sleep(self.poll_interval)
            elapsed = time.monotonic() - t0
            bits = self._status_bits(u, record=False)
            pos, moving = decode_position(bits)
            self._report(unit=key, moving=True, elapsed=elapsed)
            if pos == target and not moving:
                self._status_bits(u)  # once more, recorded: the final state goes into the log
                return {"unit": key, "position": name, "duration_s": round(elapsed, 2)}
            if elapsed > self.move_timeout:
                raise DeviceTimeout(
                    f"{u.label} did not reach '{name}' within {self.move_timeout:.0f} s "
                    f"(status 0x{bits:08X}). Is it blocked?"
                )
