"""Transport layer: moves raw bytes to and from one device. It knows nothing about protocols.

Implementations: `SerialTransport` (now), `FakeTransport` (tests/simulation). A TCP transport
(DG645 over LAN, later) only has to implement the same four small methods.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Self

log = logging.getLogger(__name__)

# Opening a D2XX device by serial (flip mounts) briefly opens every FTDI chip to compare serials,
# so a COM port on an FTDI adapter (ELL14 COM3, HIT-MV COM4) opened at the same moment fails
# with "Access is denied" (hardware test 2026-11-18: COM3 blocked for the ~130 ms of each
# FT_OpenEx). All devices connect in parallel at program start, so opens take turns.
USB_OPEN_LOCK = threading.Lock()


class TransportError(Exception):
    """The connection cannot be used (cannot open, closed, write failed)."""


class TransportTimeout(TransportError):
    """No complete reply within the timeout. `partial` holds whatever bytes did arrive."""

    def __init__(self, message: str, partial: bytes = b"") -> None:
        super().__init__(message)
        self.partial = partial


class Transport(ABC):
    """Byte pipe to one device.

    Subclasses implement `_open`, `_close`, `_write`, `_read_some`, `_discard_input`;
    this class adds buffering (`read_until`, `read_exact`) and raw-byte debug logging.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._rxbuf = bytearray()
        self._open_flag = False

    # --- to implement -------------------------------------------------------------------
    @abstractmethod
    def _open(self) -> None: ...

    @abstractmethod
    def _close(self) -> None: ...

    @abstractmethod
    def _write(self, data: bytes) -> None: ...

    @abstractmethod
    def _read_some(self) -> bytes:
        """Return the bytes available now, waiting a short time (<= ~50 ms) for at least one.
        Return b"" if nothing arrived."""

    @abstractmethod
    def _discard_input(self) -> None:
        """Drop bytes received by the OS/driver but not read yet."""

    # --- public API ---------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._open_flag

    def open(self) -> None:
        if self._open_flag:
            return
        self._open()
        self._rxbuf.clear()
        self._open_flag = True
        log.debug("%s opened", self.name)

    def close(self) -> None:
        if not self._open_flag:
            return
        self._open_flag = False
        self._close()
        log.debug("%s closed", self.name)

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def write(self, data: bytes) -> None:
        self._require_open()
        log.debug("%s TX %r", self.name, data)
        self._write(data)

    def reset_input(self) -> None:
        """Forget any unread input (stale replies) before sending a new command."""
        self._require_open()
        self._discard_input()
        if self._rxbuf:
            log.debug("%s discarded %r", self.name, bytes(self._rxbuf))
        self._rxbuf.clear()

    def read_until(self, terminator: bytes, timeout: float) -> bytes:
        """Read up to and including `terminator`. Bytes after it stay buffered for the next read.

        Raises TransportTimeout (with the partial data) if the terminator does not arrive."""
        self._require_open()
        deadline = time.monotonic() + timeout
        while True:
            idx = self._rxbuf.find(terminator)
            if idx >= 0:
                return self._take(idx + len(terminator))
            if time.monotonic() >= deadline:
                partial = self._take(len(self._rxbuf), log_it=False)
                log.debug("%s RX timeout, partial %r", self.name, partial)
                raise TransportTimeout(
                    f"{self.name}: no {terminator!r} within {timeout:.1f} s", partial
                )
            self._rxbuf += self._read_some()

    def read_exact(self, n: int, timeout: float) -> bytes:
        """Read exactly `n` bytes (for binary protocols)."""
        self._require_open()
        deadline = time.monotonic() + timeout
        while len(self._rxbuf) < n:
            if time.monotonic() >= deadline:
                partial = self._take(len(self._rxbuf), log_it=False)
                raise TransportTimeout(f"{self.name}: {len(partial)}/{n} bytes", partial)
            self._rxbuf += self._read_some()
        return self._take(n)

    # --- helpers ------------------------------------------------------------------------
    def _take(self, n: int, log_it: bool = True) -> bytes:
        data = bytes(self._rxbuf[:n])
        del self._rxbuf[:n]
        if log_it:
            log.debug("%s RX %r", self.name, data)
        return data

    def _require_open(self) -> None:
        if not self._open_flag:
            raise TransportError(f"{self.name}: not open")
