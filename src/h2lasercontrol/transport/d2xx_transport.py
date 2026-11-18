"""FTDI D2XX transport (Thorlabs APT devices such as the MFF101 flip mount).

These devices have no COM port: Windows uses FTDI's D2XX driver (`ftd2xx.dll`, installed with
Kinesis). The device is opened by its USB serial number. Set-up as in the Thorlabs protocol
manual (Issue 48, p. 33): 115200 baud, 8N1, purge, reset, RTS/CTS flow control, RTS on.
"""

from __future__ import annotations

import ctypes
import time
from typing import Any

from .base import USB_OPEN_LOCK, Transport, TransportError

FT_OPEN_BY_SERIAL_NUMBER = 1
FT_PURGE_RX, FT_PURGE_TX = 1, 2
FT_FLOW_RTS_CTS = 0x0100
FT_STATUS_TEXT = {1: "invalid handle", 2: "device not found", 3: "device not opened",
                  4: "I/O error (unplugged?)", 5: "insufficient resources", 6: "invalid parameter"}
READ_TIMEOUT_MS = 50  # one _read_some waits at most this long for the first byte

_dll: Any = None


def _load_dll() -> Any:
    global _dll
    if _dll is None:
        try:
            _dll = ctypes.WinDLL("ftd2xx.dll")  # type: ignore[attr-defined]
        except (OSError, AttributeError) as e:
            raise TransportError(
                "FTDI D2XX driver (ftd2xx.dll) not found. Install Thorlabs Kinesis or the "
                "FTDI D2XX driver."
            ) from e
    return _dll


class D2xxTransport(Transport):
    def __init__(self, usb_serial: str, baudrate: int = 115200, *, rtscts: bool = True,
                 name: str | None = None) -> None:
        super().__init__(name or f"d2xx-{usb_serial}")
        self.usb_serial = usb_serial
        self.baudrate = baudrate
        self.rtscts = rtscts
        self.port = f"USB {usb_serial}"  # shown in the GUI like a COM port name
        self._h = ctypes.c_void_p()

    def _check(self, status: int, what: str) -> None:
        if status != 0:
            text = FT_STATUS_TEXT.get(status, f"FT_STATUS {status}")
            raise TransportError(f"{self.name}: {what} failed ({text})")

    def _open(self) -> None:
        d = _load_dll()
        h = ctypes.c_void_p()
        with USB_OPEN_LOCK:  # FT_OpenEx briefly blocks other FTDI COM ports (see base)
            st = d.FT_OpenEx(ctypes.c_char_p(self.usb_serial.encode("ascii")),
                             FT_OPEN_BY_SERIAL_NUMBER, ctypes.byref(h))
        if st == 2:
            raise TransportError(f"USB device {self.usb_serial} not found. Is it plugged in?")
        if st == 3:
            raise TransportError(
                f"USB device {self.usb_serial} is in use by another program. Close Kinesis "
                "(also from the system tray); if that does not help, unplug and re-plug its USB "
                "cable."
            )
        self._check(st, "open")
        self._h = h
        try:
            self._check(d.FT_SetBaudRate(h, self.baudrate), "set baud rate")
            self._check(d.FT_SetDataCharacteristics(h, 8, 0, 0), "set 8N1")
            time.sleep(0.05)
            self._check(d.FT_Purge(h, FT_PURGE_RX | FT_PURGE_TX), "purge")
            time.sleep(0.05)
            self._check(d.FT_ResetDevice(h), "reset")
            if self.rtscts:
                self._check(d.FT_SetFlowControl(h, FT_FLOW_RTS_CTS, 0, 0), "set flow control")
                self._check(d.FT_SetRts(h), "set RTS")
            self._check(d.FT_SetTimeouts(h, READ_TIMEOUT_MS, 1000), "set timeouts")
        except TransportError:
            d.FT_Close(h)
            raise

    def _close(self) -> None:
        if self._h:
            _load_dll().FT_Close(self._h)
            self._h = ctypes.c_void_p()

    def _write(self, data: bytes) -> None:
        written = ctypes.c_ulong()
        self._check(_load_dll().FT_Write(self._h, data, len(data), ctypes.byref(written)), "write")
        if written.value != len(data):
            raise TransportError(f"{self.name}: wrote {written.value}/{len(data)} bytes")

    def _queue(self) -> int:
        q = ctypes.c_ulong()
        self._check(_load_dll().FT_GetQueueStatus(self._h, ctypes.byref(q)), "read status")
        return q.value

    def _read(self, n: int) -> bytes:
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_ulong()
        self._check(_load_dll().FT_Read(self._h, buf, n, ctypes.byref(got)), "read")
        return buf.raw[: got.value]

    def _read_some(self) -> bytes:
        n = self._queue()
        if n == 0:
            first = self._read(1)  # waits up to READ_TIMEOUT_MS
            if not first:
                return b""
            n = self._queue()
            return first + (self._read(n) if n else b"")
        return self._read(n)

    def _discard_input(self) -> None:
        self._check(_load_dll().FT_Purge(self._h, FT_PURGE_RX), "purge input")
