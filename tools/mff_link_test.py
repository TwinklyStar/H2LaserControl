"""Read-only USB link stability test for one MFF101 flip mount (FTDI D2XX). Never moves it.

Sends only queries and checks every reply byte for byte against the first reply:
  A. N status queries (MOT_REQ_STATUSBITS, 12-byte reply) back to back
  B. N info queries (HW_REQ_INFO, 90-byte reply) back to back
  C. N open -> info -> close cycles (like reconnecting)
  D. optional soak: one status query every --soak-interval s for --soak-minutes (like the GUI)
  E. optional flips (MOVES THE UNIT, only with --allow-motion): --flips N flips, status polled
     as fast as possible during each flip (link check while the motor runs); always ends at the
     starting position.
Counts timeouts, wrong/short replies, stray bytes and open failures; prints latency stats.

Usage: python tools/mff_link_test.py 37006391 [--n 2000] [--cycles 50] [--soak-minutes 0]
       [--flips 20 --allow-motion]
Close Kinesis (and our GUI if it uses this unit) first.
"""
from __future__ import annotations

import argparse
import statistics
import time

from h2lasercontrol.transport import D2xxTransport

STATUS = bytes([0x29, 0x04, 0x01, 0x00, 0x50, 0x01])
INFO = bytes([0x05, 0x00, 0x00, 0x00, 0x50, 0x01])


class Counter:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = 0
        self.timeouts = 0
        self.wrong = 0
        self.stray = 0
        self.lat: list[float] = []
        self.events: list[str] = []

    def report(self) -> str:
        n = self.ok + self.timeouts + self.wrong
        s = (f"{self.name}: {n} queries, ok {self.ok}, timeouts {self.timeouts}, "
             f"wrong replies {self.wrong}, stray bytes {self.stray}")
        if self.lat:
            ms = sorted(x * 1000 for x in self.lat)
            s += (f"\n    latency ms: min {ms[0]:.2f}, median {statistics.median(ms):.2f}, "
                  f"p99 {ms[int(len(ms) * 0.99) - 1]:.2f}, max {ms[-1]:.2f}")
        for e in self.events[:10]:
            s += f"\n    ! {e}"
        return s


def query(t: D2xxTransport, tx: bytes, n: int, expect: bytes | None, c: Counter) -> bytes | None:
    t0 = time.perf_counter()
    t.write(tx)
    try:
        rx = t.read_exact(n, timeout=1.0)
    except Exception as e:  # noqa: BLE001 - count every kind of failure
        c.timeouts += 1
        c.events.append(f"{time.strftime('%H:%M:%S')} timeout: {e}")
        time.sleep(0.2)
        t.reset_input()
        return None
    c.lat.append(time.perf_counter() - t0)
    if expect is not None and rx != expect:
        c.wrong += 1
        c.events.append(f"{time.strftime('%H:%M:%S')} wrong reply {rx.hex(' ')}")
        time.sleep(0.2)
        t.reset_input()
        return None
    if t._queue():  # bytes beyond the expected reply
        c.stray += 1
        extra = t._read(t._queue())
        c.events.append(f"{time.strftime('%H:%M:%S')} stray bytes {extra.hex(' ')}")
    c.ok += 1
    return rx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("serial")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--cycles", type=int, default=50)
    ap.add_argument("--soak-minutes", type=float, default=0)
    ap.add_argument("--soak-interval", type=float, default=0.2)
    ap.add_argument("--flips", type=int, default=0)
    ap.add_argument("--allow-motion", action="store_true")
    a = ap.parse_args()
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "unit", a.serial)

    t = D2xxTransport(a.serial)
    t.open()
    first_status = query(t, STATUS, 12, None, Counter("first"))
    first_info = query(t, INFO, 90, None, Counter("first"))
    print("status reply:", first_status.hex(" ") if first_status else None)
    print("info reply ok:", bool(first_info))

    a_c, b_c = Counter("A status"), Counter("B info")
    t0 = time.perf_counter()
    for _ in range(a.n):
        query(t, STATUS, 12, first_status, a_c)
    print(a_c.report(), f"\n    took {time.perf_counter() - t0:.1f} s")
    t0 = time.perf_counter()
    for _ in range(a.n // 4):
        query(t, INFO, 90, first_info, b_c)
    print(b_c.report(), f"\n    took {time.perf_counter() - t0:.1f} s")
    t.close()

    c_c = Counter("C reopen")
    open_fail = 0
    open_ms: list[float] = []
    for _ in range(a.cycles):
        t0 = time.perf_counter()
        try:
            t.open()
        except Exception as e:  # noqa: BLE001
            open_fail += 1
            c_c.events.append(f"open failed: {e}")
            time.sleep(0.5)
            continue
        open_ms.append((time.perf_counter() - t0) * 1000)
        query(t, INFO, 90, first_info, c_c)
        t.close()
    print(c_c.report(), f"\n    open failures {open_fail}/{a.cycles}",
          f"open time ms: median {statistics.median(open_ms):.0f}, max {max(open_ms):.0f}"
          if open_ms else "")

    if a.soak_minutes > 0:
        d_c = Counter("D soak")
        t.open()
        end = time.monotonic() + a.soak_minutes * 60
        while time.monotonic() < end:
            query(t, STATUS, 12, first_status, d_c)
            time.sleep(a.soak_interval)
        t.close()
        print(d_c.report())

    if a.flips > 0:
        if not a.allow_motion:
            raise SystemExit("--flips moves the unit: add --allow-motion")
        flip_test(t, a.flips)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "done")


def status_bits(t: D2xxTransport, c: Counter) -> int | None:
    rx = query(t, STATUS, 12, None, c)
    if rx is None:
        return None
    if rx[:8] != bytes.fromhex("2a 04 06 00 81 50 01 00"):
        c.ok -= 1
        c.wrong += 1
        c.events.append(f"{time.strftime('%H:%M:%S')} bad status reply {rx.hex(' ')}")
        return None
    return int.from_bytes(rx[8:12], "little")


def position(bits: int | None) -> int | None:
    if bits is None or bits & 0xF0:
        return None
    return {0x01: 1, 0x02: 2}.get(bits & 0x03)


def flip_test(t: D2xxTransport, flips: int) -> None:
    c = Counter("E status during flips")
    t.open()
    try:
        start = position(status_bits(t, c))
        if start is None:
            raise SystemExit("start position unknown: not flipping")
        flips += flips % 2  # even number: end where we started
        times, polls_per_flip = [], []
        for i in range(flips):
            target = 2 if position(status_bits(t, c)) == 1 else 1
            t0 = time.perf_counter()
            t.write(bytes([0x6A, 0x04, 0x01, target, 0x50, 0x01]))
            n = 0
            while True:
                n += 1
                bits = status_bits(t, c)
                if position(bits) == target:
                    break
                if time.perf_counter() - t0 > 3.0:
                    c.events.append(f"flip {i + 1} to {target}: not there after 3 s")
                    break
            times.append(time.perf_counter() - t0)
            polls_per_flip.append(n)
            time.sleep(0.3)
        print(c.report())
        print(f"    {flips} flips, time to arrive s: min {min(times):.3f}, "
              f"median {statistics.median(times):.3f}, max {max(times):.3f}; "
              f"status polls per flip: median {statistics.median(polls_per_flip):.0f}")
    finally:
        end = position(status_bits(t, c))
        if end != start and start is not None:
            t.write(bytes([0x6A, 0x04, 0x01, start, 0x50, 0x01]))
            time.sleep(1.0)
            end = position(status_bits(t, c))
        print(f"    start position {start}, end position {end}")
        t.close()


if __name__ == "__main__":
    main()
