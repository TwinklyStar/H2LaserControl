"""Thorlabs ELL14 rotation mount (Elliptec ASCII protocol). All ELLO panel functions.

Protocol: docs/protocols.md "Thorlabs ELL14" (manual Issue 12 + ELLO capture 2026-11-16).
Command = <addr><cmd>[8 hex data] + terminator; reply = <addr><CODE>[data] CR LF.
Data = signed 32-bit two's complement, 8 uppercase hex digits.
"""

from __future__ import annotations

import time
from typing import Any

from ..oplog import OpLog
from ..transport import Transport, TransportTimeout
from .base import Aborted, DeviceError, DeviceTimeout, Driver, action

STATUS_TEXT = {
    0: "OK",
    1: "communication time out",
    2: "mechanical time out",
    3: "command error or not supported",
    4: "value out of range",
    5: "module isolated",
    6: "module out of isolation",
    7: "initializing error",
    8: "thermal error",
    9: "busy",
    10: "sensor error",
    11: "motor error",
    12: "out of range",
    13: "over current error",
}
BUSY = 9
HOME_DIRECTIONS = {"cw": "0", "ccw": "1"}  # manual p.28 / capture: ELLO "anticlockwise" = ho1
MIN_HOME_OFFSET_DEG = 0.7  # manual p.32: rotation stages need home offset > 0.7 deg
DEFAULT_PULSES_PER_DEG = 143360 / 360  # ELL14; replaced by the value from `in` on connect


class Ell14Error(DeviceError):
    def __init__(self, status: int, command: str) -> None:
        self.status = status
        super().__init__(f"{command}: device status {status} ({STATUS_TEXT.get(status, '?')})")


def encode(value: int) -> str:
    """Signed 32-bit int -> 8 uppercase hex digits (two's complement)."""
    if not -(2**31) <= value < 2**31:
        raise ValueError(f"{value} does not fit in 32 bits")
    return f"{value & 0xFFFFFFFF:08X}"


def decode(hex8: str) -> int:
    v = int(hex8, 16)
    return v - 2**32 if v >= 2**31 else v


def round_half_away(x: float) -> int:
    """Like ELLO's Math.Round(x, MidpointRounding.AwayFromZero)."""
    n = int(abs(x) + 0.5)
    return n if x >= 0 else -n


class Ell14(Driver):
    device_type = "ell14"

    def __init__(
        self,
        name: str,
        transport: Transport,
        oplog: OpLog | None = None,
        *,
        address: str = "0",
        terminator: bytes = b"\x07",
        positions: dict[str, float] | None = None,
        reply_timeout: float = 2.0,
        move_timeout: float = 10.0,
        clean_timeout: float = 900.0,
        clean_poll: float = 2.0,
        stop_reply_timeout: float = 3.0,
    ) -> None:
        super().__init__(name, transport, oplog)
        if len(address) != 1 or address not in "0123456789ABCDEF":
            raise ValueError(f"bad ELL address {address!r}")
        self.address = address
        self.terminator = terminator
        self.positions = dict(positions or {})
        self.reply_timeout = reply_timeout
        self.move_timeout = move_timeout
        self.clean_timeout = clean_timeout
        self.clean_poll = clean_poll
        self.stop_reply_timeout = stop_reply_timeout
        self.pulses_per_deg = DEFAULT_PULSES_PER_DEG
        self.info: dict[str, Any] = {}

    # --- low level --------------------------------------------------------------------------
    def _send(self, cmd: str, data: str = "") -> bytes:
        tx = f"{self.address}{cmd}{data}".encode("ascii") + self.terminator
        self.transport.reset_input()
        self.transport.write(tx)
        return tx

    def _read(self, tx: bytes, timeout: float) -> tuple[str, str]:
        """Read one reply -> (CODE, data). Records the exchange."""
        try:
            raw = self.transport.read_until(b"\r\n", timeout)
        except TransportTimeout as e:
            self._record(tx, e.partial or None)
            raise DeviceTimeout(f"{self.name}: no reply to {tx!r} within {timeout} s") from e
        self._record(tx, raw)
        text = raw.decode("ascii", "replace").strip()
        if len(text) < 3 or text[0] != self.address:
            raise DeviceError(f"{self.name}: unexpected reply {raw!r} to {tx!r}")
        return text[1:3].upper(), text[3:]

    def _request(self, cmd: str, data: str = "", *, expect: str,
                 timeout: float | None = None) -> str:
        """Send and wait for reply code `expect`. A `GS` with an error status raises Ell14Error."""
        tx = self._send(cmd, data)
        code, payload = self._read(tx, self.reply_timeout if timeout is None else timeout)
        if code == expect:
            return payload
        if code == "GS":
            raise Ell14Error(int(payload, 16), f"{cmd}{data}")
        raise DeviceError(f"{self.name}: {cmd}{data} -> {code}{payload}, expected {expect}")

    def _move(self, cmd: str, data: str = "") -> float:
        """Motion commands reply `PO` when the move is finished (`GS` = not completed/error)."""
        return self._deg(decode(self._request(cmd, data, expect="PO", timeout=self.move_timeout)))

    def _deg(self, pulses: int) -> float:
        return round(pulses / self.pulses_per_deg, 4)

    def _pulses(self, deg: float) -> int:
        return round_half_away(deg * self.pulses_per_deg)

    # --- identification / status --------------------------------------------------------------
    @action()
    def identify(self) -> dict[str, Any]:
        p = self._request("in", expect="IN")
        # e.g. 0E 11401124 2025 18 01 0168 00023000  (manual p.10)
        if len(p) != 30:
            raise DeviceError(f"{self.name}: bad IN reply {p!r}")
        info = {
            "type": int(p[0:2], 16),
            "serial": p[2:10],
            "year": int(p[10:14]),
            "firmware": p[14:16],
            "hardware": p[16:18],
            "travel": int(p[18:22], 16),
            "pulses_per_travel": int(p[22:30], 16),
        }
        if info["type"] != 14:
            raise DeviceError(f"{self.name}: device type {info['type']} is not an ELL14")
        self.pulses_per_deg = info["pulses_per_travel"] / info["travel"]
        self.info = info
        return info

    @action()
    def status(self) -> dict[str, Any]:
        """Device status. Note: reading it clears a stored error (manual)."""
        code = int(self._request("gs", expect="GS"), 16)
        return {"code": code, "text": STATUS_TEXT.get(code, "?")}

    @action()
    def get_position(self) -> float:
        return self._deg(decode(self._request("gp", expect="PO")))

    @action()
    def get_velocity(self) -> int:
        """Velocity in % of maximum (read-only; `sv` is not used)."""
        return int(self._request("gv", expect="GV"), 16)

    # --- motion ------------------------------------------------------------------------------
    @action(moves=True)
    def home(self, direction: str = "ccw") -> float:
        """Home. ELLO uses anticlockwise (`ho1`)."""
        try:
            d = HOME_DIRECTIONS[direction]
        except KeyError:
            raise ValueError(f"direction must be 'cw' or 'ccw', not {direction!r}") from None
        return self._move("ho", d)

    @action(moves=True)
    def move_abs(self, deg: float) -> float:
        if not 0 <= deg < 360:
            raise ValueError(f"absolute angle must be 0 <= deg < 360, not {deg}")
        return self._move("ma", encode(self._pulses(deg)))

    @action(moves=True)
    def move_rel(self, deg: float) -> float:
        if not -360 <= deg <= 360 or deg == 0:
            raise ValueError(f"relative angle must be non-zero and within +-360, not {deg}")
        return self._move("mr", encode(self._pulses(deg)))

    @action(moves=True)
    def move_to(self, name: str) -> float:
        """Move to a named angle from config."""
        try:
            deg = self.positions[name]
        except KeyError:
            raise ValueError(f"unknown position {name!r}; known: {list(self.positions)}") from None
        return self.move_abs(deg)

    @action(moves=True)
    def jog_forward(self) -> float:
        self._require_jog_step()
        return self._move("fw")

    @action(moves=True)
    def jog_backward(self) -> float:
        self._require_jog_step()
        return self._move("bw")

    def _require_jog_step(self) -> None:
        # jog step 0 = continuous rotation until `st`; manual: needs velocity 50-70 % or the
        # unit may overheat. Not supported (open decision) -> refuse.
        if self._get_jog_pulses() == 0:
            raise DeviceError(f"{self.name}: jog step is 0 (continuous jog) - not allowed")

    # --- settings ----------------------------------------------------------------------------
    @action()
    def get_home_offset(self) -> float:
        return self._deg(decode(self._request("go", expect="HO")))

    @action()
    def set_home_offset(self, deg: float) -> None:
        """Changes the factory-set home offset (ours: 3.214 deg). Must be > 0.7 deg."""
        if not MIN_HOME_OFFSET_DEG < deg < 360:
            raise ValueError(f"home offset must be {MIN_HOME_OFFSET_DEG} < deg < 360, not {deg}")
        self._set("so", self._pulses(deg))

    @action()
    def get_jog_step(self) -> float:
        return self._deg(self._get_jog_pulses())

    @action()
    def set_jog_step(self, deg: float) -> None:
        if not 0 < deg <= 360:
            raise ValueError("jog step must be 0 < deg <= 360 (0 = continuous is not allowed)")
        self._set("sj", self._pulses(deg))

    def _get_jog_pulses(self) -> int:
        return decode(self._request("gj", expect="GJ"))

    def _set(self, cmd: str, pulses: int) -> None:
        code = int(self._request(cmd, encode(pulses), expect="GS"), 16)
        if code != 0:
            raise Ell14Error(code, cmd)

    # --- cleaning / stop -----------------------------------------------------------------------
    @action(moves=True)
    def clean(self) -> dict[str, Any]:
        """Clean mechanics (`cm`): full-range back-and-forth for a few minutes."""
        return self._long_run("cm")

    @action(moves=True)
    def clean_and_optimize(self) -> dict[str, Any]:
        """Clean and re-tune motor frequencies (`om`); several minutes, changes device settings."""
        return self._long_run("om")

    def _long_run(self, cmd: str) -> dict[str, Any]:
        """Start cm/om (reply GS09 = busy), poll `gs` until GS00. Stop on request/timeout."""
        code = int(self._request(cmd, expect="GS"), 16)
        if code not in (0, BUSY):
            raise Ell14Error(code, cmd)
        t0 = time.monotonic()
        while code == BUSY:
            if self._sleep_or_stop(self.clean_poll):
                self._stop()
                raise Aborted(f"{self.name}: {cmd} stopped on request")
            if time.monotonic() - t0 > self.clean_timeout:
                self._stop()
                raise DeviceTimeout(f"{self.name}: {cmd} not finished in {self.clean_timeout} s")
            code = int(self._request("gs", expect="GS"), 16)
        if code != 0:
            raise Ell14Error(code, cmd)
        return {"duration_s": round(time.monotonic() - t0, 1)}

    @action()
    def stop(self) -> dict[str, Any]:
        """Stop cleaning/optimizing or a continuous jog."""
        return self._stop()

    def _stop(self) -> dict[str, Any]:
        # Manual: `st` replies GS (GS09 and/or GS00). Capture: only one GS00 for st+gs, so it is
        # not certain that `st` replies. Read GS until GS00; if nothing comes, ask with `gs`.
        tx = self._send("st")
        replies = []
        deadline = time.monotonic() + self.stop_reply_timeout
        while time.monotonic() < deadline:
            try:
                code, payload = self._read(tx, max(0.01, deadline - time.monotonic()))
            except DeviceTimeout:
                break
            replies.append(f"{code}{payload}")
            if code == "GS" and int(payload, 16) == 0:
                return {"st_replies": replies}
        final = self.status()
        if final["code"] != 0:
            raise Ell14Error(final["code"], "st")
        return {"st_replies": replies, "gs": final["code"]}
