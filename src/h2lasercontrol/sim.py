"""Simulated devices: responders for FakeTransport that behave like our real units
(replies taken from the probes/captures in docs/protocols.md). For tests and GUI development
without hardware. They are simplified: motion completes after a few status polls."""

from __future__ import annotations

import struct
from typing import ClassVar

N = 8


class HitMvSim:
    def __init__(self, positions: tuple[int, ...] = (30000000, 30000000), busy_polls: int = 3,
                 homing: tuple[int, int, int, int] = (50000, 500000, 200, 250000),
                 speed: tuple[int, int, int] = (100000, 1000000, 200)) -> None:
        self.pos: list[int | None] = list(positions) + [None] * (N - len(positions))
        self.target = list(self.pos)
        self.start: list[int | None] = list(self.pos)
        self.remaining = [0] * N
        self.coast: list[list[int]] = [[] for _ in range(N)]  # positions shown after L: (decel)
        self.busy_polls = busy_polls
        self.homing = {a: list(homing) for a in range(len(positions))}
        self.speed = {a: list(speed) for a in range(len(positions))}
        self.received: list[str] = []

    def __call__(self, tx: bytes) -> bytes | None:
        cmd = tx.decode("ascii").removesuffix("\r\n")
        self.received.append(cmd)
        reply = self.handle(cmd)
        return None if reply is None else (reply + "\r\n").encode("ascii")

    def _fmt(self, values: list) -> str:
        return ",".join("" if v is None else str(v) for v in values)

    def handle(self, cmd: str) -> str | None:
        code, _, p = cmd.partition(":")
        code = code.upper()
        if code == "?":
            if p == "N":
                return "HIT-MV    "
            if p == "V":
                return "V1.20-001"
            if p == "Z":
                return "1"
            if p[:1] == "D" and int(p[1:]) in self.speed:
                return self._fmt(self.speed[int(p[1:])])
            if p[:1] == "B" and int(p[1:]) in self.homing:
                s, f, r, m = self.homing[int(p[1:])]
                return f"{s},{f},{r},{m}"
            return "NG"
        if code == "Q":
            if p == "S":
                return "00," + self._fmt(["00" if x is not None else None for x in self.pos])
            for a in range(N):
                if self.coast[a]:
                    self.pos[a] = self.coast[a].pop(0)
                elif self.remaining[a]:  # moving: show a position between start and target
                    done = 1 - self.remaining[a] / self.busy_polls
                    self.pos[a] = int(self.start[a] + (self.target[a] - self.start[a]) * done)
            return self._fmt(self.pos)
        if code == "!":
            flags = []
            for a in range(N):
                if self.pos[a] is None:
                    flags.append(None)
                    continue
                flags.append(1 if self.remaining[a] > 0 else 0)
                if self.remaining[a] > 0:
                    self.remaining[a] -= 1
                    if self.remaining[a] == 0:
                        self.pos[a] = self.target[a]
            return self._fmt(flags)
        if code == "L":
            if p == "E":
                self.remaining = [0] * N
            else:
                for a, v in enumerate(p.split(",")):
                    if v == "1" and self.remaining[a]:
                        # like the real unit (2026-11-17): `!:` says ready at once, but the stage
                        # still decelerates for a short distance (Q: changes a few more times)
                        self.remaining[a] = 0
                        cur, tgt = self.pos[a], self.target[a]
                        mid = cur + (tgt - cur) // 2
                        step = 1 if tgt >= cur else -1
                        self.pos[a] = mid
                        self.coast[a] = [mid + step * 40000, mid + step * 79860]
            return "OK"
        if code in ("D", "B"):
            vals = [int(v) for v in p.split(",")]
            axis = vals[0]
            if self.remaining[axis] or self.pos[axis] is None:
                return "NG"
            if code == "D":
                s, f, _r = vals[1:]
                if s > f:
                    return "NG"
                self.speed[axis] = vals[1:]
            else:
                s, f, r, m = vals[1:]
                if not s <= m <= f:
                    return "NG"
                self.homing[axis] = [s, f, r, m]
            return "OK"
        if code in ("H", "M", "A"):
            parts = p.split(",")
            axes = [a for a, v in enumerate(parts) if v]
            if any(self.remaining[a] or self.pos[a] is None for a in axes):
                return "NG"
            for a in axes:
                v = parts[a]
                self.start[a] = self.pos[a]
                if code == "H":
                    self.target[a] = 0
                elif code == "M":
                    self.target[a] = self.pos[a] + int(v)
                else:
                    self.target[a] = int(v)
                self.remaining[a] = self.busy_polls
            return "OK"
        return "NG"


class Ell14Sim:
    IN = "IN0E1140112420251801016800023000"  # our unit (probe 2026-11-16)

    def __init__(self, address: str = "0", position: int = 0x3040, home_offset: int = 0x500,
                 jog: int = 0x7C7, clean_polls: int = 2, st_replies: bool = True) -> None:
        self.address = address
        self.pos = position
        self.home_offset = home_offset
        self.jog = jog
        self.clean_polls = clean_polls
        self.cleaning = 0
        self.st_replies = st_replies
        self.received: list[str] = []

    @staticmethod
    def _h(v: int) -> str:
        return f"{v & 0xFFFFFFFF:08X}"

    @staticmethod
    def _d(s: str) -> int:
        v = int(s, 16)
        return v - 2**32 if v >= 2**31 else v

    def __call__(self, tx: bytes) -> bytes | None:
        cmd = tx.decode("ascii").rstrip("\x07\r\n")
        self.received.append(cmd)
        if not cmd or cmd[0] != self.address:
            return None
        reply = self.handle(cmd[1:3], cmd[3:])
        return None if reply is None else f"{self.address}{reply}\r\n".encode("ascii")

    def handle(self, c: str, data: str) -> str | None:
        if self.cleaning and c not in ("gs", "st"):
            return "GS09"
        match c:
            case "in":
                return self.IN
            case "gs":
                if self.cleaning:
                    self.cleaning -= 1
                    return "GS09"
                return "GS00"
            case "gp":
                return "PO" + self._h(self.pos)
            case "gv":
                return "GV64"
            case "ho":
                self.pos = 0
                return "PO" + self._h(self.pos)
            case "ma":
                self.pos = self._d(data)
                return "PO" + self._h(self.pos)
            case "mr":
                self.pos += self._d(data)
                return "PO" + self._h(self.pos)
            case "fw" | "bw":
                if self.jog == 0:
                    return None  # continuous jog: runs until st
                self.pos += self.jog if c == "fw" else -self.jog
                return "PO" + self._h(self.pos)
            case "go":
                return "HO" + self._h(self.home_offset)
            case "so":
                self.home_offset = self._d(data)
                return "GS00"
            case "gj":
                return "GJ" + self._h(self.jog)
            case "sj":
                self.jog = self._d(data)
                return "GS00"
            case "cm" | "om":
                self.cleaning = self.clean_polls
                return "GS09"
            case "st":
                self.cleaning = 0
                return "GS00" if self.st_replies else None
        return "GS03"


class Dg645Sim:
    """DG645 (ASCII). Settings and replies as our unit s/n004497 on 2026-11-20 (read-only probe).
    Set commands reply nothing; errors go to a queue read with `LERR?`."""

    IDN = "Stanford Research Systems,DG645,s/n004497,ver1.17.116"
    REAL: ClassVar[dict[int, tuple[int, float]]] = {  # channel -> (reference channel, seconds)
        2: (0, 0.0370266), 3: (2, -0.0000001),
        4: (0, 0.036580467), 5: (4, 0.0000005),
        6: (0, 0.0369991), 7: (6, 0.00004),
        8: (0, 0.0370306), 9: (8, 0.0000025),
    }

    def __init__(self) -> None:
        self.delays: dict[int, tuple[int, float]] = dict(self.REAL)
        self.errors: list[int] = []
        self.received: list[str] = []
        self.remote = False  # REM LED: front panel locked

    def __call__(self, tx: bytes) -> bytes | None:
        reply = None
        for cmd in tx.decode("ascii").replace("\r", "\n").replace(";", "\n").split("\n"):
            cmd = cmd.strip()
            if cmd:
                self.received.append(cmd)
                reply = self.handle(cmd)
        return None if reply is None else (reply + "\r\n").encode("ascii")

    def _abs(self, ch: int) -> float:
        if ch in (0, 1):
            return 0.0
        ref, t = self.delays[ch]
        return self._abs(ref) + t

    def handle(self, cmd: str) -> str | None:
        mnemonic = cmd[:4].upper()  # "DLAY", "LERR", "*IDN", "*CLS" (manual p. 44)
        rest = cmd[len(mnemonic):].strip()
        query = rest.startswith("?")
        args = [a.strip() for a in rest.lstrip("?").split(",")] if rest.lstrip("?") else []
        try:
            if mnemonic == "*IDN" and query:
                return self.IDN
            if mnemonic == "LERR" and query:
                return str(self.errors.pop(0) if self.errors else 0)
            if mnemonic == "*CLS":
                self.errors.clear()
                return None
            if mnemonic in ("LCAL", "REMT"):  # real unit: any command -> remote; LCAL -> local
                self.remote = mnemonic == "REMT"
                return None
            self.remote = True
            if mnemonic == "DLAY" and query:
                ref, t = self.delays[int(args[0])]
                return f"{ref},{t:+.12f}"
            if mnemonic == "LINK" and query:
                return str(self.delays[int(args[0])][0])
            if mnemonic == "DLAY" and len(args) == 3:
                c, d, t = int(args[0]), int(args[1]), float(args[2])
                if c < 2 or d == 1 or d == c or c not in self.delays:
                    self.errors.append(13)
                    return None
                old = self.delays[c]
                self.delays[c] = (d, round(t / 5e-12) * 5e-12)
                if not 0 <= self._abs(c) <= 2000:
                    self.delays[c] = old
                    self.errors.append(12)
                return None
        except (ValueError, IndexError, KeyError):
            self.errors.append(10)
            return None
        self.errors.append(110)
        return None


class MffSim:
    """MFF101 flip mount (APT binary). Replies as unit 37011815 did on 2026-11-17."""

    def __init__(self, serial: int = 37011815, position: int = 2, flip_polls: int = 3,
                 model: bytes = b"MFF002") -> None:
        self.serial = serial
        self.model = model
        self.pos: int | None = position
        self.target = position
        self.moving = 0  # status polls left until the flip ends
        self.flip_polls = flip_polls
        self.received: list[bytes] = []

    @staticmethod
    def _msg(mid: int, data: bytes) -> bytes:
        return struct.pack("<HHBB", mid, len(data), 0x81, 0x50) + data

    def __call__(self, tx: bytes) -> bytes | None:
        self.received.append(tx)
        mid, _chan, p2 = struct.unpack_from("<HBB", tx)
        if mid == 0x0005:  # HW_REQ_INFO
            data = (struct.pack("<I", self.serial) + self.model.ljust(8, b"\0")
                    + struct.pack("<H", 16) + bytes([3, 0, 1, 0])
                    + b"APT Filter Flipper".ljust(48, b"\0") + bytes(12)
                    + struct.pack("<HHH", 2, 0, 1))
            return self._msg(0x0006, data)
        if mid == 0x0429:  # MOT_REQ_STATUSBITS
            if self.moving:
                self.moving -= 1
                bits = 0x10
                if self.moving == 0:
                    self.pos = self.target
            else:
                bits = {1: 0x01, 2: 0x02}.get(self.pos or 0, 0)
            return self._msg(0x042A, struct.pack("<HI", 1, 0x90000000 | bits))
        if mid == 0x046A:  # MOT_MOVE_JOG: go to position p2
            if p2 in (1, 2) and not (p2 == self.pos and not self.moving):
                self.target = p2
                self.pos = None
                self.moving = self.flip_polls
            return None
        if mid == 0x0511:  # MOT_REQ_MFF_OPERPARAMS (values of our unit)
            data = struct.pack("<HiiHHiHHi", 1, 500, 508, 1, 1, 200, 3, 0x10, 200) + bytes(6)
            return self._msg(0x0512, data)
        return None  # MOD_IDENTIFY and anything else: no reply
