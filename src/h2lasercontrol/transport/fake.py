"""In-memory transport for tests and simulation. Nothing touches real hardware."""

from __future__ import annotations

import time
from collections.abc import Callable

from .base import Transport

Responder = Callable[[bytes], bytes | None]


class FakeTransport(Transport):
    """`responder(tx) -> reply bytes | None` plays the device.

    `chunk_size` delivers replies in small pieces, like a real port that splits replies.
    `written` records everything sent.
    """

    def __init__(
        self, responder: Responder | None = None, *, chunk_size: int | None = None,
        name: str = "fake",
    ) -> None:
        super().__init__(name)
        self.responder = responder
        self.chunk_size = chunk_size
        self.written: list[bytes] = []
        self._incoming = bytearray()

    def feed(self, data: bytes) -> None:
        """Inject bytes as if the device sent them unprompted."""
        self._incoming += data

    def _open(self) -> None:
        pass

    def _close(self) -> None:
        pass

    def _write(self, data: bytes) -> None:
        self.written.append(data)
        if self.responder is not None:
            reply = self.responder(data)
            if reply:
                self._incoming += reply

    def _read_some(self) -> bytes:
        if not self._incoming:
            time.sleep(0.001)
            return b""
        n = len(self._incoming) if self.chunk_size is None else self.chunk_size
        data = bytes(self._incoming[:n])
        del self._incoming[:n]
        return data

    def _discard_input(self) -> None:
        self._incoming.clear()


class ScriptedResponder:
    """Replies from a fixed script of (expected_tx, reply) pairs; fails on unexpected TX."""

    def __init__(self, script: list[tuple[bytes, bytes | None]]) -> None:
        self.script = list(script)

    def __call__(self, tx: bytes) -> bytes | None:
        if not self.script:
            raise AssertionError(f"unexpected TX {tx!r} (script finished)")
        expected, reply = self.script.pop(0)
        if tx != expected:
            raise AssertionError(f"TX {tx!r}, expected {expected!r}")
        return reply

    @property
    def done(self) -> bool:
        return not self.script
