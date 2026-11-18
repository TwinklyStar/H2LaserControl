"""Serial-port transport (pyserial). Used for every device that appears as a COM port."""

from __future__ import annotations

import time

import serial

from .base import USB_OPEN_LOCK, Transport, TransportError

_POLL = 0.05  # seconds _read_some waits for the first byte
_RETRY_S = 0.5  # one retry when the port is busy for a moment (another program enumerating FTDI)


class SerialTransport(Transport):
    def __init__(
        self,
        port: str,
        baudrate: int,
        *,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
        rtscts: bool = False,
        write_timeout: float = 2.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name or port)
        self.port = port
        self._settings = {
            "baudrate": baudrate,
            "bytesize": bytesize,
            "parity": parity,
            "stopbits": stopbits,
            "rtscts": rtscts,
            "timeout": _POLL,
            "write_timeout": write_timeout,
        }
        self._ser: serial.Serial | None = None

    def _open(self) -> None:
        for attempt in (1, 2):
            try:
                with USB_OPEN_LOCK:  # not while a D2XX device is being opened (see base)
                    self._ser = serial.Serial(port=self.port, **self._settings)
                return
            except serial.SerialException as e:
                busy = "Access is denied" in str(e) or "PermissionError" in str(e)
                if attempt == 1 and busy:
                    time.sleep(_RETRY_S)
                    continue
                raise TransportError(
                    f"cannot open {self.port}: {e} (is the vendor software still using it?)"
                ) from e

    def _close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def _write(self, data: bytes) -> None:
        assert self._ser is not None
        try:
            self._ser.write(data)
            self._ser.flush()
        except serial.SerialTimeoutException as e:
            # with RTS/CTS a write blocks while the device holds CTS low (off / cable unplugged)
            raise TransportError(f"{self.name}: write timed out (device off? CTS low?)") from e
        except serial.SerialException as e:
            raise TransportError(f"{self.name}: write failed: {e}") from e

    def _read_some(self) -> bytes:
        assert self._ser is not None
        try:
            return self._ser.read(self._ser.in_waiting or 1)
        except serial.SerialException as e:
            raise TransportError(f"{self.name}: read failed: {e}") from e

    def _discard_input(self) -> None:
        assert self._ser is not None
        self._ser.reset_input_buffer()
