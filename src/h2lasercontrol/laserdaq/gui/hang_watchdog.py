"""Detects a frozen GUI thread and dumps every thread's stack to the fault log.

A QTimer on the GUI thread refreshes a heartbeat; a background thread checks it.  If the
heartbeat is older than ``timeout_s`` the stack of ALL threads is written once, which shows
exactly which call the GUI thread (and the acquisition thread) are stuck in.
"""
from __future__ import annotations

import faulthandler
import logging
import threading
import time
from typing import Callable, TextIO

from PySide6.QtCore import QObject, QTimer

_log = logging.getLogger("laserdaq.watchdog")


class HangWatchdog(QObject):
    def __init__(
        self,
        out: TextIO | None = None,
        timeout_s: float = 3.0,
        dump: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._timeout = timeout_s
        self._out = out
        self._dump = dump
        self._beat = time.monotonic()
        self._stop = threading.Event()
        self._dumped = False
        self.dumps = 0
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._heartbeat)
        self._thread = threading.Thread(target=self._watch, daemon=True, name="daq-watchdog")

    def start(self) -> None:
        self._beat = time.monotonic()
        self._timer.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._timer.stop()

    def _heartbeat(self) -> None:
        self._beat = time.monotonic()

    def _watch(self) -> None:
        while not self._stop.wait(0.25):
            stuck = time.monotonic() - self._beat
            if stuck > self._timeout and not self._dumped:
                self._dumped = True
                self.dumps += 1
                _log.error("GUI thread has not responded for %.1f s - dumping all stacks", stuck)
                try:
                    if self._dump is not None:
                        self._dump()
                    elif self._out is not None:
                        self._out.write(f"\n=== GUI frozen {stuck:.1f} s at "
                                        f"{time.strftime('%H:%M:%S')} ===\n")
                        self._out.flush()
                        faulthandler.dump_traceback(file=self._out, all_threads=True)
                        self._out.flush()
                except Exception:  # noqa: BLE001
                    _log.exception("could not dump stacks")
            elif stuck <= self._timeout and self._dumped:
                self._dumped = False
                _log.warning("GUI thread responsive again")
