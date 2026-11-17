"""Sigma Koki HIT-MV stage controller, HIT mode. Two linear feedthroughs (axis 0, axis 1).

Protocol: docs/protocols.md "Sigma Koki HIT-MV" (manual + SGSample captures 2026-11-16).
Command = `<code>:<p0>,...,<p7>` CR LF (all 8 slots, empty = no operation); replies end CR LF
and are space-padded. Positions are raw controller units (1 unit = 2 nm real on our stages).

INSERT  = (B: homing speed, F raised to `homing_max_speed`) + `H:` origin return -> position 0
RETRACT = `D:` speed + relative `M:` +30000000, exactly as SGSample does (only from position 0)
Any command except Q ? L ! I O to a busy axis is rejected (`NG`) -> check `!:` first.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..oplog import OpLog
from ..transport import Transport, TransportTimeout
from .base import Aborted, DeviceError, DeviceTimeout, Driver, action

N_SLOTS = 8
# Q:S slave-status bits that mean something went wrong (bit 0 -LS, 1 +LS, 5 scale, 6 driver alarm)
ALARM_BITS = {0: "-limit switch", 1: "+limit switch", 5: "scale alarm", 6: "driver alarm"}


@dataclass
class Axis:
    number: int
    name: str
    inserted: int = 0
    retracted: int = 30000000


def slots(axis: int, value: str) -> str:
    """Parameter list with `value` in the axis slot, e.g. slots(1, "1") -> ",1,,,,,,"."""
    parts = [""] * N_SLOTS
    parts[axis] = value
    return ",".join(parts)


def parse_slots(reply: str) -> list[str | None]:
    parts = [p.strip() for p in reply.split(",")]
    parts += [""] * (N_SLOTS - len(parts))
    return [p if p else None for p in parts[:N_SLOTS]]


def parse_alarms(reply: str) -> dict[int, list[str]]:
    """`Q:S` reply `stm,sts0,...,sts7` (hex bit fields) -> {axis: [alarm names]}."""
    out: dict[int, list[str]] = {}
    for axis, sts in enumerate(p.strip() for p in reply.split(",")[1:]):
        if not sts:
            continue
        bits = int(sts, 16)
        names = [txt for bit, txt in ALARM_BITS.items() if bits >> bit & 1]
        if names:
            out[axis] = names
    return out


class HitMv(Driver):
    device_type = "hitmv"

    def __init__(
        self,
        name: str,
        transport: Transport,
        oplog: OpLog | None = None,
        *,
        axes: dict[int, Axis],
        homing_max_speed: int | None = 1000000,
        speed: tuple[int, int, int] = (100000, 1000000, 200),
        insert_timeout: float = 120.0,
        move_timeout: float = 90.0,
        reply_timeout: float = 2.0,
        poll_interval: float = 0.2,
        settle_interval: float = 0.15,
        settle_timeout: float = 5.0,
    ) -> None:
        super().__init__(name, transport, oplog)
        self.axes = dict(axes)
        self.homing_max_speed = homing_max_speed
        self.speed = speed
        self.insert_timeout = insert_timeout
        self.move_timeout = move_timeout
        self.reply_timeout = reply_timeout
        self.poll_interval = poll_interval
        self.settle_interval = settle_interval
        self.settle_timeout = settle_timeout

    # --- low level --------------------------------------------------------------------------
    def _query(self, cmd: str, *, record: bool = True) -> str:
        tx = cmd.encode("ascii") + b"\r\n"
        self.transport.reset_input()
        self.transport.write(tx)
        try:
            raw = self.transport.read_until(b"\r\n", self.reply_timeout)
        except TransportTimeout as e:
            self._record(tx, e.partial or None)
            raise DeviceTimeout(f"{self.name}: no reply to {cmd!r}") from e
        if record:
            self._record(tx, raw)
        return raw.decode("ascii", "replace").strip()

    def _command(self, cmd: str) -> None:
        reply = self._query(cmd)
        if reply != "OK":
            raise DeviceError(f"{self.name}: {cmd} -> {reply!r} (rejected)")

    def _axis(self, axis: int) -> Axis:
        try:
            return self.axes[axis]
        except KeyError:
            raise ValueError(f"axis {axis} is not configured; configured: {list(self.axes)}") from None

    # --- queries -----------------------------------------------------------------------------
    @action()
    def identify(self) -> dict[str, str]:
        name = self._query("?:N")
        if name != "HIT-MV":
            raise DeviceError(f"{self.name}: device name {name!r}, expected 'HIT-MV'")
        version = self._query("?:V")
        mode = self._query("?:Z")
        if mode != "1":
            raise DeviceError(f"{self.name}: controller is not in HIT mode (?:Z -> {mode!r})")
        return {"name": name, "version": version, "mode": "HIT"}

    def _positions(self, record: bool = True) -> list[int | None]:
        return [None if v is None else int(v) for v in parse_slots(self._query("Q:", record=record))]

    def _busy(self, record: bool = True) -> list[bool | None]:
        return [None if v is None else v == "1" for v in parse_slots(self._query("!:", record=record))]

    def _alarms(self) -> dict[int, list[str]]:
        return parse_alarms(self._query("Q:S"))

    @action()
    def status(self) -> dict[str, Any]:
        pos = self._positions()
        busy = self._busy()
        alarms = self._alarms()
        out = {}
        for n, ax in self.axes.items():
            p = pos[n]
            named = {ax.inserted: "INSERTED", ax.retracted: "RETRACTED"}.get(p) if p is not None else None
            out[ax.name] = {
                "axis": n,
                "connected": p is not None,
                "position": p,
                "named": named,
                "busy": busy[n],
                "alarms": alarms.get(n, []),
            }
        return out

    def snapshot(self) -> dict[str, Any]:
        return {"axes": self.status()}

    @action()
    def get_speed(self, axis: int) -> dict[str, int]:
        s, f, r = (int(v) for v in self._query(f"?:D{axis}").split(","))
        return {"start": s, "max": f, "accel_ms": r}

    @action()
    def get_homing_speed(self, axis: int) -> dict[str, int]:
        s, f, r, m = (int(v) for v in self._query(f"?:B{axis}").split(","))
        return {"start": s, "max": f, "accel_ms": r, "mid": m}

    # --- motion ------------------------------------------------------------------------------
    def _require_ready(self, axis: int) -> int:
        """Axis must be connected, not busy (busy axis -> NG) and standing still. Returns its
        position. (`!:` says ready while still decelerating after `L:` — hardware 2026-11-17 —
        so the position is read twice.)"""
        busy = self._busy()[axis]
        if busy is None:
            raise DeviceError(f"{self.name}: axis {axis} is not connected")
        if busy:
            raise DeviceError(f"{self.name}: axis {axis} is busy")
        pos = self._positions()[axis]
        time.sleep(self.settle_interval)
        pos2 = self._positions()[axis]
        if pos2 != pos:
            raise DeviceError(f"{self.name}: axis {axis} is still moving ({pos} -> {pos2})")
        assert pos is not None
        return pos

    def _wait_settled(self, axes: list[int]) -> None:
        """After a stop: wait until the positions stop changing (deceleration takes ~0.2 s+)."""
        last = self._positions(record=False)
        deadline = time.monotonic() + self.settle_timeout
        while time.monotonic() < deadline:
            time.sleep(self.settle_interval)
            now = self._positions(record=False)
            busy = self._busy(record=False)
            if all(now[a] == last[a] and not busy[a] for a in axes):
                self._positions()  # record the final position in the op-log
                return
            last = now
        raise DeviceTimeout(f"{self.name}: axes {axes} did not settle after stop")

    def _wait_done(self, axis: int, timeout: float) -> int:
        """Poll `!:` until the axis is ready. Stop the axis on timeout or stop request."""
        t0 = time.monotonic()
        while True:
            if self._sleep_or_stop(self.poll_interval):
                self._stop_axes([axis])
                raise Aborted(f"{self.name}: axis {axis} stopped on request")
            if not self._busy(record=False)[axis]:
                break
            if self.progress is not None:
                self._report(axis=axis, position=self._positions(record=False)[axis],
                             elapsed=time.monotonic() - t0)
            if time.monotonic() - t0 > timeout:
                self._stop_axes([axis])
                raise DeviceTimeout(f"{self.name}: axis {axis} still busy after {timeout} s; stopped")
        pos = self._positions()[axis]
        assert pos is not None
        alarms = self._alarms().get(axis)
        if alarms:
            raise DeviceError(f"{self.name}: axis {axis} alarm after move: {alarms}")
        return pos

    @action(moves=True)
    def insert(self, axis: int) -> dict[str, Any]:
        """Insert = origin return (`H:`), ends at position 0. Takes ~62 s (~30 s with fast homing)."""
        ax = self._axis(axis)
        self._require_ready(axis)
        sent_b = None
        if self.homing_max_speed:
            hs = self.get_homing_speed(axis)
            f = self.homing_max_speed
            if not hs["start"] <= hs["mid"] <= f:
                raise DeviceError(f"{self.name}: homing speed {hs} incompatible with F={f}")
            sent_b = f"B:{axis},{hs['start']},{f},{hs['accel_ms']},{hs['mid']}"
            self._command(sent_b)
        self._command(f"H:{slots(axis, '1')}")
        pos = self._wait_done(axis, self.insert_timeout)
        if pos != ax.inserted:
            raise DeviceError(f"{self.name}: after homing axis {axis} is at {pos}, expected 0")
        return {"position": pos, "homing_speed_cmd": sent_b}

    @action(moves=True)
    def retract(self, axis: int) -> dict[str, Any]:
        """Retract = speed `D:` + relative `M:` +travel, as SGSample. Only from the inserted
        position (0), because the relative move only ends at the retracted position from there."""
        ax = self._axis(axis)
        pos = self._require_ready(axis)
        if pos != ax.inserted:
            raise DeviceError(
                f"{self.name}: axis {axis} is at {pos}, not at the inserted position "
                f"{ax.inserted}; retract refused (insert first, or use move_abs)"
            )
        s, f, r = self.speed
        self._command(f"D:{axis},{s},{f},{r}")
        self._command(f"M:{slots(axis, f'{ax.retracted - ax.inserted:+d}')}")
        pos = self._wait_done(axis, self.move_timeout)
        if pos != ax.retracted:
            raise DeviceError(f"{self.name}: axis {axis} ended at {pos}, expected {ax.retracted}")
        return {"position": pos}

    @action(moves=True)
    def move_abs(self, axis: int, units: int) -> dict[str, Any]:
        """Absolute move (`A:`) within the configured range [inserted, retracted]."""
        ax = self._axis(axis)
        lo, hi = sorted((ax.inserted, ax.retracted))
        if not isinstance(units, int) or not lo <= units <= hi:
            raise ValueError(f"target must be an integer within [{lo}, {hi}], not {units!r}")
        self._require_ready(axis)
        s, f, r = self.speed
        self._command(f"D:{axis},{s},{f},{r}")
        self._command(f"A:{slots(axis, f'{units:+d}')}")
        return {"position": self._wait_done(axis, self.move_timeout)}

    @action(moves=True)
    def move_to(self, axis: int, name: str) -> dict[str, Any]:
        """Named position: INSERTED -> insert(), RETRACTED -> retract()."""
        match name.upper():
            case "INSERTED":
                return self.insert(axis)
            case "RETRACTED":
                return self.retract(axis)
        raise ValueError(f"unknown position {name!r} (INSERTED / RETRACTED)")

    @action()
    def stop(self, axis: int | None = None) -> None:
        """Decelerate-stop one axis (or all configured axes)."""
        self._stop_axes(list(self.axes) if axis is None else [axis])

    @action()
    def emergency_stop(self) -> None:
        self._command("L:E")

    def _stop_axes(self, axes: list[int]) -> None:
        """Decelerate-stop and wait until the stages stand still."""
        parts = [""] * N_SLOTS
        for a in axes:
            parts[a] = "1"
        self._command("L:" + ",".join(parts))
        self._wait_settled(axes)
