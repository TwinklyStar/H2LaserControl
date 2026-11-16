"""Common driver interface.

Every device operation goes through `Driver.execute(action, **args)`, which writes the
operation log (who/what/when, raw commands, result, error). Methods that are operations are
marked with `@action`; `moves=True` marks hardware motion (a "start" entry is logged first, so a
crash during a long move still leaves a record).

Threading: a driver is used from ONE thread (its device worker, Phase 2). The only method that
may be called from another thread is `request_stop()`; long waits watch for it and stop the device.
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from ..oplog import OpLog
from ..transport import Transport

log = logging.getLogger(__name__)


class DeviceError(Exception):
    """The device refused a command, replied unexpectedly or reported an error."""


class DeviceTimeout(DeviceError):
    """The device did not reply / did not finish an operation in time."""


class Aborted(DeviceError):
    """The operation was stopped on request (`request_stop`)."""


@dataclass(frozen=True)
class ActionInfo:
    moves: bool  # True: physically moves hardware -> needs user permission when testing


F = TypeVar("F", bound=Callable[..., Any])


def action(*, moves: bool = False) -> Callable[[F], F]:
    def deco(fn: F) -> F:
        fn.__action__ = ActionInfo(moves=moves)  # type: ignore[attr-defined]
        return fn

    return deco


class Driver:
    device_type: str = "?"

    def __init__(self, name: str, transport: Transport, oplog: OpLog | None = None) -> None:
        self.name = name
        self.transport = transport
        self.oplog = oplog
        self._stop_event = threading.Event()
        self._exchanges: list[tuple[bytes, bytes | None]] | None = None

    # --- operation entry point -----------------------------------------------------------
    @classmethod
    def actions(cls) -> dict[str, ActionInfo]:
        return {
            n: f.__action__
            for n, f in inspect.getmembers(cls, inspect.isfunction)
            if hasattr(f, "__action__")
        }

    def execute(self, action_name: str, **args: Any) -> Any:
        info = self.actions().get(action_name)
        if info is None:
            raise ValueError(f"{self.name}: unknown action {action_name!r}")
        fn = getattr(self, action_name)
        self._stop_event.clear()
        if info.moves:
            self._log(action_name, "start", args)
        self._exchanges = []
        t0 = time.monotonic()
        try:
            result = fn(**args)
        except Exception as e:
            self._log(action_name, "failed", args, error=f"{type(e).__name__}: {e}",
                      t0=t0)
            raise
        finally:
            exchanges, self._exchanges = self._exchanges, None
        self._log(action_name, "done", args, result=result, t0=t0, exchanges=exchanges)
        return result

    def request_stop(self) -> None:
        """Thread-safe: ask the running operation to stop the device and raise `Aborted`."""
        self._stop_event.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def _sleep_or_stop(self, seconds: float) -> bool:
        """Sleep; return True early if a stop was requested."""
        return self._stop_event.wait(seconds)

    # --- common actions ------------------------------------------------------------------
    @action()
    def connect(self) -> Any:
        self.transport.open()
        try:
            return self.identify()
        except Exception:
            self.transport.close()
            raise

    @action()
    def disconnect(self) -> None:
        self.transport.close()

    @property
    def is_connected(self) -> bool:
        return self.transport.is_open

    @action()
    def identify(self) -> Any:
        raise NotImplementedError

    @action()
    def status(self) -> Any:
        raise NotImplementedError

    # --- helpers for subclasses ------------------------------------------------------------
    def _record(self, tx: bytes, rx: bytes | None) -> None:
        """Remember one command/reply pair for the current action's log entry."""
        if self._exchanges is not None:
            self._exchanges.append((tx, rx))

    def _log(self, action_name: str, event: str, args: dict[str, Any], *,
             result: Any = None, error: str | None = None, t0: float | None = None,
             exchanges: list[tuple[bytes, bytes | None]] | None = None) -> None:
        if event == "failed":
            exchanges = self._exchanges
        log.info("%s.%s %s %s%s", self.name, action_name, event, args,
                 f" -> {error or result}" if event != "start" else "")
        if self.oplog is None:
            return
        try:
            self.oplog.write(
                device=self.name, action=action_name, event=event, args=args, result=result,
                error=error, exchanges=exchanges,
                duration_s=None if t0 is None else time.monotonic() - t0,
            )
        except OSError:
            log.exception("could not write operation log")
