"""One worker thread per device. The GUI never touches a driver or a port directly.

GUI thread                          worker thread (QThread)
  service.submit("insert", axis=1) ─▶ driver.execute(...)   (queued, one at a time)
  service.request_stop()  ──────────▶ driver.request_stop()  (thread-safe, works while busy)
  ◀── signals: connection_changed, busy_changed, state_changed, progress, action_done/failed
A timer in the worker polls `driver.snapshot()` while idle (not logged) and detects lost connections.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from ..config import DeviceConfig
from ..drivers import Driver, create_driver
from ..drivers.base import DeviceTimeout
from ..oplog import OpLog
from ..sim import Ell14Sim, HitMvSim, MffSim
from ..transport import FakeTransport, TransportError

log = logging.getLogger(__name__)

POLL_MS = {"hitmv": 1000, "ell14": 2000, "mff": 1000}
LOST_AFTER = 2  # consecutive failed polls before the connection is reported lost


def make_sim_transport(cfg: DeviceConfig) -> FakeTransport | dict[str, FakeTransport]:
    if cfg.type == "mff":  # one simulated flip mount per configured unit
        return {k: FakeTransport(MffSim(serial=int(u["usb_serial"]), flip_polls=4),
                                 name=f"{cfg.key}.{k}-sim")
                for k, u in cfg.settings.get("units", {}).items()}
    if cfg.type == "hitmv":
        # 60 polls x 0.2 s = 12 s per simulated move (real: ~30 s)
        return FakeTransport(HitMvSim(busy_polls=60), name=f"{cfg.key}-sim")
    if cfg.type == "ell14":
        return FakeTransport(Ell14Sim(clean_polls=3), name=f"{cfg.key}-sim")
    raise ValueError(f"no simulator for device type {cfg.type!r}")


class DeviceService(QObject):
    connection_changed = Signal(bool, str)  # connected?, message (port or reason)
    busy_changed = Signal(bool, str)  # busy?, action name
    state_changed = Signal(dict)  # driver.snapshot()
    progress = Signal(dict)  # driver progress during long actions
    action_done = Signal(str, object)  # action, result
    action_failed = Signal(str, str)  # action, message for the user
    _submit = Signal(str, dict)
    _shutdown = Signal()

    def __init__(self, cfg: DeviceConfig, oplog: OpLog, *, sim: bool = False,
                 state_dir: str | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.state_dir = state_dir  # where saved angles are written (sim: separate folder)
        self.key = cfg.key
        self.oplog = oplog
        self.sim = sim
        self.driver: Driver | None = None
        self.busy = False  # written in the worker, read by the GUI (bool assignment is atomic)
        self.connected = False
        self._failed_polls = 0
        self._timer: QTimer | None = None
        self._thread = QThread()
        self._thread.setObjectName(f"device-{cfg.key}")
        self.moveToThread(self._thread)
        self._thread.started.connect(self._on_started)
        self._submit.connect(self._run)
        self._shutdown.connect(self._on_shutdown)

    # --- called from the GUI thread ---------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def submit(self, action: str, **kwargs: Any) -> None:
        self._submit.emit(action, kwargs)

    def request_stop(self) -> None:
        """Call DIRECTLY from the GUI thread (not through a signal connection: this object lives
        in the worker thread, so a queued call would wait until the running action is over)."""
        drv = self.driver
        if drv is not None:
            drv.request_stop()

    def shutdown(self, timeout_ms: int = 15000) -> bool:
        """Stop a running action, disconnect, end the thread. Returns False if it hung."""
        self.request_stop()
        self._shutdown.emit()
        return self._thread.wait(timeout_ms)

    # --- worker thread ----------------------------------------------------------------------
    @Slot()
    def _on_started(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS.get(self.cfg.type, 1000))

    @Slot()
    def _on_shutdown(self) -> None:
        if self._timer:
            self._timer.stop()
        if self.driver is not None and self.driver.is_connected:
            try:
                self.driver.execute("disconnect")
            except Exception:
                log.exception("%s: disconnect failed", self.key)
        self._thread.quit()

    def _new_driver(self) -> Driver:
        transport = make_sim_transport(self.cfg) if self.sim else None
        drv = create_driver(self.cfg, self.oplog, transport, state_dir=self.state_dir)
        drv.progress = self.progress.emit
        return drv

    @Slot(str, dict)
    def _run(self, action: str, kwargs: dict[str, Any]) -> None:
        if action == "connect" and not self.connected:
            try:
                self.driver = self._new_driver()  # port looked up again on every connect
            except Exception as e:  # noqa: BLE001 - e.g. USB serial not found
                self.connection_changed.emit(False, str(e))
                self.action_failed.emit(action, str(e))
                return
        if self.driver is None:
            self.action_failed.emit(action, "not connected")
            return
        self.driver.clear_stop()  # before "busy" enables the STOP button, so no stop is lost
        self._set_busy(True, action)
        try:
            result = self.driver.execute(action, **kwargs)
        except Exception as e:  # noqa: BLE001 - every failure is shown to the user
            self.action_failed.emit(action, str(e))
            if isinstance(e, TransportError) or not self.driver.is_connected:
                self._set_connected(False, str(e))
        else:
            if action == "connect":
                self._set_connected(True, self.driver.connection_text())
            elif action == "disconnect":
                self._set_connected(False, "disconnected")
            self.action_done.emit(action, result)
        finally:
            self._set_busy(False, action)
        self._poll()

    @Slot()
    def _poll(self) -> None:
        if not self.connected or self.busy or self.driver is None:
            return
        try:
            state = self.driver.snapshot()
        except (TransportError, DeviceTimeout) as e:
            self._failed_polls += 1
            if self._failed_polls >= LOST_AFTER:
                self.driver.drop_connection()
                self._set_connected(False, f"connection lost: {e}")
            return
        except Exception as e:  # noqa: BLE001 - unexpected reply: show, keep going
            log.warning("%s: poll failed: %s", self.key, e)
            return
        self._failed_polls = 0
        self.state_changed.emit(state)

    def _set_busy(self, busy: bool, action: str) -> None:
        self.busy = busy
        self.busy_changed.emit(busy, action)

    def _set_connected(self, connected: bool, message: str) -> None:
        self.connected = connected
        self._failed_polls = 0
        self.connection_changed.emit(connected, message)
