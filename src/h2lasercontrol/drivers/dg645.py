"""SRS DG645 delay generator: read every channel, adjust ONE channel (ours) within hard limits.

Protocol: docs/protocols.md "SRS DG645" (manual + read-only checks on our unit 2026-11-20).
ASCII commands ending in LF; queries reply `...` CR LF; set commands reply nothing.

User decisions (2026-11-20, design-document F3b-F3g):
- Our output is CD. Only C (rising edge = laser trigger) is adjusted, as `DLAY 4,0,t` (relative
  to T0). D is linked to C (D = C + width), so it moves along and the width stays fixed.
- The other channels belong to other groups: the program NEVER writes them. `_write` refuses
  anything except our one set command (and the error-queue reads around it).
- Hard limit: nominal - 1.5 us ... nominal + 3 us (config).
- All channels are read; a change made outside the program (front panel, power cycle) is
  written to the operation log.
- Remote changes are not auto-saved by the DG645 (lost at power-off): accepted. The program
  only reports when C is not what it last set.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from ..energy import AngleStore
from ..oplog import OpLog
from ..transport import Transport, TransportTimeout
from .base import DeviceError, DeviceTimeout, Driver, action

CHANNELS = ("T0", "T1", "A", "B", "C", "D", "E", "F", "G", "H")  # manual p. 56, Table 31
WATCHED = CHANNELS[2:]  # A..H: delays that can be read and set
RESOLUTION_S = 5e-12  # manual pp. 17, 27
OUTSIDE = "(outside the program)"  # "user" of log entries for changes we did not make

ERROR_TEXT = {
    10: "illegal value", 11: "illegal mode", 12: "illegal delay (out of range)",
    13: "illegal link", 14: "recall failed", 15: "not allowed (locked by another interface)",
    110: "illegal command", 111: "undefined command", 112: "illegal query", 113: "illegal set",
    114: "null parameter", 115: "extra parameters", 116: "missing parameters",
    117: "parameter overflow", 118: "invalid floating point number", 126: "syntax error",
    170: "communication error", 171: "over run", 254: "too many errors",
}


def channel_index(name: str) -> int:
    try:
        return CHANNELS.index(name.upper())
    except ValueError:
        raise ValueError(f"unknown DG645 channel {name!r}; known: {', '.join(CHANNELS)}") from None


def parse_delay(reply: str) -> tuple[str, float]:
    """`DLAY?c` reply "4,+0.000000500000" -> ("C", 5e-07)."""
    try:
        ref, value = reply.strip().split(",")
        return CHANNELS[int(ref)], float(value)
    except (ValueError, IndexError):
        raise DeviceError(f"unexpected DLAY? reply {reply!r}") from None


def absolute_times(delays: dict[str, tuple[str, float]]) -> dict[str, float]:
    """Seconds after T0 for every channel, following the links (B = A + x ...)."""
    out: dict[str, float] = {"T0": 0.0}

    def resolve(ch: str, depth: int = 0) -> float:
        if ch in out:
            return out[ch]
        if ch not in delays or depth > len(CHANNELS):
            return math.nan
        ref, value = delays[ch]
        out[ch] = resolve(ref, depth + 1) + value
        return out[ch]

    for ch in delays:
        resolve(ch)
    return out


def ms_text(seconds: float) -> str:
    """0.0365804670 -> "36.580 467 ms" (to 1 ps; trailing zero groups dropped)."""
    if math.isnan(seconds):
        return "?"
    s = f"{seconds * 1e3:.9f}"
    whole, frac = s.split(".")
    groups = [frac[0:3], frac[3:6], frac[6:9]]
    while len(groups) > 1 and groups[-1] == "000":
        groups.pop()
    return f"{whole}.{' '.join(groups)} ms"


def delay_text(ref: str, seconds: float) -> str:
    """("T0", 0.0365804670) -> "T0 + 36.580 467 ms";  ("C", 5e-7) -> "C + 0.500 µs"."""
    if ref == "T0":
        return f"T0 + {ms_text(seconds)}"
    t = us_text(seconds)
    return f"{ref} {t[0]} {t[1:]}"


def us_text(seconds: float, sign: bool = True) -> str:
    """Offset in microseconds, 3 decimals (1 ns), more only if needed."""
    us = seconds * 1e6
    for decimals in (3, 6):
        if abs(round(us, decimals) - us) < 5e-7:
            break
    return f"{us:+.{decimals}f} µs" if sign else f"{us:.{decimals}f} µs"


class Dg645(Driver):
    device_type = "dg645"

    def __init__(
        self,
        name: str,
        transport: Transport,
        oplog: OpLog | None = None,
        *,
        channel: str = "C",
        width_channel: str = "D",
        nominal_s: float,
        min_offset_s: float = -1.5e-6,
        max_offset_s: float = 3e-6,
        store: AngleStore | None = None,
        reply_timeout: float = 1.0,
    ) -> None:
        super().__init__(name, transport, oplog)
        self.channel = channel.upper()
        self.ch = channel_index(self.channel)
        self.width_channel = width_channel.upper()
        if self.channel not in WATCHED or self.width_channel not in WATCHED:
            raise ValueError("channel and width_channel must be A..H")
        if not min_offset_s < 0 < max_offset_s:
            raise ValueError("limits must be below and above the nominal value")
        self.nominal_s = float(nominal_s)
        self.min_offset_s = float(min_offset_s)
        self.max_offset_s = float(max_offset_s)
        self.store = store
        self.reply_timeout = reply_timeout
        self.info: dict[str, Any] = {}
        self._seen: dict[str, str] = {}  # channel -> raw `DLAY?` reply last seen

    # --- low level --------------------------------------------------------------------------
    def _query(self, cmd: str) -> str:
        if not cmd.endswith("?") and "?" not in cmd:
            raise ValueError(f"not a query: {cmd!r}")
        tx = cmd.encode("ascii") + b"\n"
        self.transport.reset_input()
        self.transport.write(tx)
        try:
            raw = self.transport.read_until(b"\r\n", self.reply_timeout)
        except TransportTimeout as e:
            self._record(tx, e.partial or None)
            raise DeviceTimeout(f"{self.name}: no reply to {cmd!r} within "
                                f"{self.reply_timeout} s (is the DG645 on?)") from e
        self._record(tx, raw)
        return raw.decode("ascii", "replace").strip()

    def _set_command(self, delay_s: float) -> str:
        return f"DLAY {self.ch},0,{delay_s:.12f}"

    def _write(self, cmd: str) -> None:
        """The ONLY set command that may ever be sent: our channel relative to T0.
        Everything else (other channels, links, *RST, *SAV, REMT ...) is refused here."""
        if not cmd.startswith(f"DLAY {self.ch},0,") or cmd.count(",") != 2:
            raise DeviceError(f"{self.name}: refused to send {cmd!r} (only our channel "
                              f"{self.channel} may be changed)")
        tx = cmd.encode("ascii") + b"\n"
        self.transport.reset_input()
        self.transport.write(tx)
        self._record(tx, None)

    def _errors(self) -> list[int]:
        """Pop the DG645 error queue (`LERR?` until 0; at most 21 entries)."""
        codes = []
        for _ in range(21):
            code = int(self._query("LERR?"))
            if code == 0:
                break
            codes.append(code)
        return codes

    def _read(self, ch: str) -> str:
        return self._query(f"DLAY?{channel_index(ch)}")

    def _read_all(self) -> dict[str, str]:
        return {ch: self._read(ch) for ch in WATCHED}

    # --- state ------------------------------------------------------------------------------
    def _saved(self) -> dict[str, Any]:
        return self.store.get(self.name) if self.store else {}

    def _remember(self, **values: Any) -> None:
        if self.store is not None:
            self.store.update(self.name, **values)

    def _note_outside_changes(self, raw: dict[str, str], since: str) -> list[dict[str, Any]]:
        """Log every channel whose value differs from what we saw last (one log entry each)."""
        changes = []
        old_abs = absolute_times({c: parse_delay(v) for c, v in self._seen.items()})
        new_delays = {c: parse_delay(v) for c, v in raw.items()}
        new_abs = absolute_times(new_delays)
        for ch, value in raw.items():
            before = self._seen.get(ch)
            if before is None or before == value:
                continue
            text = f"{ch}: {delay_text(*parse_delay(before))} → {delay_text(*new_delays[ch])}"
            change = {"channel": ch, "text": text, "old": before, "new": value,
                      "abs_old_s": old_abs.get(ch), "abs_new_s": new_abs.get(ch), "since": since}
            changes.append(change)
            if self.oplog is not None:
                self.oplog.write(device=self.name, action="changed_outside", user=OUTSIDE,
                                 result=change)
            if ch == self.channel:
                now = datetime.now().astimezone().isoformat(timespec="seconds")
                self._remember(last_change={
                    "old_us": round((old_abs[ch] - self.nominal_s) * 1e6, 6),
                    "new_us": round((new_abs[ch] - self.nominal_s) * 1e6, 6),
                    "by": None, "at": now, "outside": True})
        return changes

    def _update_seen(self, raw: dict[str, str], since: str) -> list[dict[str, Any]]:
        changes = self._note_outside_changes(raw, since) if self._seen else []
        if raw != self._seen:
            self._seen = dict(raw)
            self._remember(last_seen=self._seen)
        return changes

    # --- actions ----------------------------------------------------------------------------
    @action()
    def identify(self) -> dict[str, Any]:
        idn = self._query("*IDN?")
        parts = idn.split(",")
        if len(parts) < 4 or parts[1] != "DG645":
            raise DeviceError(f"{self.name}: not a DG645: {idn!r}")
        self.info = {"model": parts[1], "serial": parts[2], "firmware": parts[3]}
        # changes made while the program was closed: compare with what it saw last time
        saved = self._saved()
        self._seen = dict(saved.get("last_seen") or {})
        raw = self._read_all()
        when = saved.get("saved_at", "the last session")
        changes = self._update_seen(raw, since=f"last seen {when}")
        return {**self.info, "channels": raw, "changed_while_closed": [c["channel"] for c in changes]}

    @action()
    def status(self) -> dict[str, Any]:
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        raw = self._read_all()
        self._update_seen(raw, since="the previous reading")
        delays = {c: parse_delay(v) for c, v in raw.items()}
        abs_s = absolute_times(delays)
        ref = delays[self.channel][0]
        ours = abs_s[self.channel]
        wref, width = delays[self.width_channel]
        saved = self._saved()
        last_set = saved.get("last_set")
        problems = []
        if ref != "T0":
            problems.append(f"{self.channel} is set relative to {ref}, not T0: the program "
                            f"will not change it.")
        if wref != self.channel:
            problems.append(f"{self.width_channel} is no longer linked to {self.channel} "
                            f"({self.width_channel} = {wref} …): changing {self.channel} would "
                            f"change the pulse width, so the program will not change it.")
        offset = ours - self.nominal_s
        if not self._in_limits(offset):
            problems.append(f"{self.channel} is outside the allowed range "
                            f"({us_text(self.min_offset_s)} … {us_text(self.max_offset_s)}).")
        outside = (last_set is not None
                   and abs(float(last_set["delay_s"]) - ours) > RESOLUTION_S / 2)
        return {
            "channels": {c: {"ref": delays[c][0], "delay_s": delays[c][1], "abs_s": abs_s[c]}
                         for c in WATCHED},
            "channel": self.channel,
            "width_channel": self.width_channel,
            "delay_s": ours,
            "offset_s": offset,
            "width_s": width if wref == self.channel else None,
            "nominal_s": self.nominal_s,
            "min_offset_s": self.min_offset_s,
            "max_offset_s": self.max_offset_s,
            "problems": problems,
            "last_set": last_set,
            "changed_outside": outside,
            "last_change": saved.get("last_change"),
        }

    def _in_limits(self, offset_s: float) -> bool:
        eps = RESOLUTION_S / 2
        return self.min_offset_s - eps <= offset_s <= self.max_offset_s + eps

    @action()
    def set_offset(self, offset_us: float) -> dict[str, Any]:
        """Set our channel to nominal + offset (µs). Refused outside the hard limits."""
        return self._set(float(offset_us) * 1e-6)

    @action()
    def step(self, delta_us: float) -> dict[str, Any]:
        """Move our channel by `delta_us` from where it is now."""
        ref, rel = parse_delay(self._read(self.channel))
        if ref != "T0":
            raise DeviceError(f"{self.name}: {self.channel} is relative to {ref}, not T0")
        return self._set(rel - self.nominal_s + float(delta_us) * 1e-6)

    def _set(self, offset_s: float) -> dict[str, Any]:
        if not math.isfinite(offset_s) or not self._in_limits(offset_s):
            raise DeviceError(
                f"{us_text(offset_s)} is outside the allowed range {us_text(self.min_offset_s)} "
                f"… {us_text(self.max_offset_s)} from nominal (T0 + {ms_text(self.nominal_s)})")
        target = round(self.nominal_s + offset_s, 12)
        # 1. check the setup is still as agreed (another group may have changed links by hand)
        before = self._read_all()
        self._update_seen(before, since="the previous reading")
        ref, old = parse_delay(before[self.channel])
        if ref != "T0":
            raise DeviceError(f"{self.name}: {self.channel} is relative to {ref}, not T0; "
                              f"not changed")
        wref = parse_delay(before[self.width_channel])[0]
        if wref != self.channel:
            raise DeviceError(f"{self.name}: {self.width_channel} is not linked to "
                              f"{self.channel} (it is relative to {wref}); not changed, "
                              f"because the pulse width would change")
        # 2. old errors (from before us) out of the way, so a new one is really ours
        stale = self._errors()
        # 3. the one set command
        self._write(self._set_command(target))
        # 4. errors? read back: our channel at the target, width channel untouched
        errors = self._errors()
        if errors:
            raise DeviceError(f"{self.name}: the DG645 refused the change: " + ", ".join(
                f"error {c} ({ERROR_TEXT.get(c, '?')})" for c in errors))
        after = self._read_all()
        ref2, new = parse_delay(after[self.channel])
        if ref2 != "T0" or abs(new - target) > RESOLUTION_S:
            raise DeviceError(f"{self.name}: read back {after[self.channel]!r}, "
                              f"expected 0,{target:.12f}")
        if after[self.width_channel] != before[self.width_channel]:
            raise DeviceError(f"{self.name}: {self.width_channel} changed unexpectedly: "
                              f"{before[self.width_channel]} → {after[self.width_channel]}")
        # the other channels must be as before (only ours changed); a change there was made by
        # someone else at the same moment: logged as an outside change, reported here too
        others = [c for c in WATCHED if c != self.channel and after[c] != before[c]]
        self._seen[self.channel] = after[self.channel]
        self._update_seen(after, since="during this change")
        user = self.oplog.user if self.oplog else None
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        change = {"old_us": round((old - self.nominal_s) * 1e6, 6),
                  "new_us": round((new - self.nominal_s) * 1e6, 6),
                  "delay_s": new, "by": user, "at": now}
        self._remember(last_seen=self._seen, last_set={"delay_s": new, "by": user, "at": now},
                       last_change={**change, "outside": False})
        result = {"channel": self.channel, "old_us": change["old_us"], "new_us": change["new_us"],
                  "old": before[self.channel], "new": after[self.channel]}
        if stale:
            result["old_errors"] = stale
        if others:  # changed by someone else at the same moment; logged, not ours
            result["also_changed_meanwhile"] = others
        return result
