"""Read-only probe of HIT-MV and ELL14. Sends ONLY query commands; nothing moves.

Usage: python tools/probe_readonly.py [--hitmv COM4] [--ell COM3]
"""

import argparse
import time

import serial

HITMV_BAUDS = [38400, 9600, 19200, 57600, 4800]  # factory default first
HITMV_QUERIES = ["?:N", "?:V", "?:Z", "Q:", "Q:S", "!:", "?:P", "?:S"]
ELL_QUERIES = ["0in", "0gs", "0gp"]


def show(direction: str, data: bytes) -> None:
    print(f"  {direction} {data!r}")


def query(
    ser: serial.Serial, cmd: str, suffix: bytes = b"\r\n", terminator: bytes = b"\r\n",
    timeout: float = 1.0,
) -> bytes:
    ser.reset_input_buffer()
    tx = cmd.encode("ascii") + suffix
    show("TX", tx)
    ser.write(tx)
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        buf += ser.read(ser.in_waiting or 1)
        if buf.endswith(terminator):
            break
    show("RX", buf)
    return buf


def probe_hitmv(port: str) -> None:
    print(f"=== HIT-MV on {port} ===")
    for baud in HITMV_BAUDS:
        print(f"-- trying {baud} baud, 8N1, RTS/CTS")
        with serial.Serial(port, baud, timeout=0.2, rtscts=True) as ser:
            if query(ser, "?:N").strip():
                for cmd in HITMV_QUERIES[1:]:
                    query(ser, cmd)
                print(f"HIT-MV responds at {baud} baud")
                return
    print("HIT-MV: no response at any baud rate (check RTS/CTS, cable, interface memory switch)")


def probe_ell(port: str) -> None:
    print(f"=== ELL14 on {port} ===")
    with serial.Serial(port, 9600, timeout=0.2) as ser:
        for cmd in ELL_QUERIES:
            query(ser, cmd, suffix=b"")  # Elliptec commands need no line terminator


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hitmv", default="COM4")
    ap.add_argument("--ell", default="COM3")
    args = ap.parse_args()
    for fn, port in ((probe_hitmv, args.hitmv), (probe_ell, args.ell)):
        try:
            fn(port)
        except serial.SerialException as e:
            print(f"!! cannot use {port}: {e}  (is the vendor software still open?)")


if __name__ == "__main__":
    main()
