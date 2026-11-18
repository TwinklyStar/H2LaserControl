"""One PicoScope tab = one session: a set of digitizers started / paused / stopped together.

Plain Python (no Qt), so it can be tested without a GUI. The tab calls `poll()` from a timer;
it returns the data items for the plots and keeps `state` up to date.

Every user action (start, pause, resume, stop) and every failure goes to the operation log.
"""

from __future__ import annotations

import logging
import os
from queue import Empty, Queue
from typing import Any

from ...oplog import OpLog
from .digitizer import Digitizer, resolve_data_path
from .virtual import VirtualDigitizer

_log = logging.getLogger(__name__)

# overall state of a session
STOPPED, STARTING, RUNNING, PAUSED, STOPPING = "stopped", "starting", "running", "paused", "stopping"


class PicoSession:
    def __init__(self, key: str, settings: dict[str, Any], oplog: OpLog, *, sim: bool = False,
                 base_dir: str | os.PathLike[str] = ".") -> None:
        self.key = key
        self.settings = settings
        self.oplog = oplog
        self.sim = sim
        self.base_dir = base_dir
        self.mode = settings.get("mode", "continuous")
        self.configs: dict[str, dict[str, Any]] = {
            name: {"run_mode": self.mode, **cfg}
            for name, cfg in settings.get("digitizers", {}).items()
        }
        if not self.configs:
            raise ValueError(f"[devices.{key}] has no digitizers")
        if self.mode == "snapshot" and len(self.configs) != 1:
            raise ValueError(f"[devices.{key}]: snapshot mode needs exactly one digitizer")
        self.queue: Queue = Queue()
        self.digitizers: dict[str, Digitizer] = {}
        self.states: dict[str, str] = {}
        self.errors: dict[str, str] = {}
        self.warnings: dict[str, str] = {}
        self.rates: dict[str, float] = {}
        self.state = STOPPED
        self._stop_requested = False

    # --- channel layout for the views ---------------------------------------------------------
    def channel_names(self) -> list[str]:
        return [n for cfg in self.configs.values() for n in cfg["channel_name"]]

    def channel_groups(self) -> list[list[str]]:
        return [list(cfg["channel_name"]) for cfg in self.configs.values()]

    def data_path(self, cfg: dict[str, Any]) -> str:
        return str(resolve_data_path(cfg.get("data_path", "data/picoscope"), self.base_dir))

    # --- user actions -------------------------------------------------------------------------
    def start(self) -> None:
        if self.state != STOPPED:
            return
        while True:  # drop leftovers of the previous run
            try:
                self.queue.get_nowait()
            except Empty:
                break
        cls = VirtualDigitizer if self.sim else Digitizer
        self.digitizers = {name: cls(name, cfg, self.queue, self.data_path(cfg))
                           for name, cfg in self.configs.items()}
        self.states = {name: STARTING for name in self.digitizers}
        self.errors, self.warnings, self.rates = {}, {}, {}
        self._stop_requested = False
        self.state = STARTING
        self.oplog.write(device=self.key, action="start", args={
            "config": self.settings.get("config"),
            "mode": self.mode,
            "scopes": {n: f"{c.get('model')} {c.get('serial')}" for n, c in self.configs.items()},
            "outputs": {n: c.get("output_name") for n, c in self.configs.items()},
        })
        for d in self.digitizers.values():
            d.start()

    def pause(self) -> None:
        if self.state not in (RUNNING, STARTING):
            return
        for d in self.digitizers.values():
            d.pause()
        self.oplog.write(device=self.key, action="pause")
        self._update_state()

    def resume(self) -> None:
        if self.state != PAUSED:
            return
        for d in self.digitizers.values():
            d.resume()
        self.oplog.write(device=self.key, action="resume")
        self._update_state()

    def stop(self) -> None:
        """Ask all digitizers to stop (returns at once; files are closed in their threads)."""
        if self.state == STOPPED or self._stop_requested:
            return
        self._stop_requested = True
        for d in self.digitizers.values():
            d.stop()
        self.oplog.write(device=self.key, action="stop", event="start")
        self.state = STOPPING

    def shutdown(self, timeout: float = 15.0) -> None:
        """Program exit: stop and wait until the files are closed."""
        self.stop()
        for d in self.digitizers.values():
            d.join(timeout)
            if d.is_alive():
                _log.error("%s: digitizer %s did not stop within %.0f s", self.key, d.device,
                           timeout)
        self.poll()

    # --- polling (GUI timer) ------------------------------------------------------------------
    def poll(self) -> list[dict[str, Any]]:
        """Drain the queue. Returns the data items (for the plots), handles the rest."""
        data = []
        while True:
            try:
                item = self.queue.get_nowait()
            except Empty:
                break
            kind = item.get("type")
            src = item.get("source", "")
            if kind == "status":
                self.states[src] = item["state"]
                if item["state"] == "error":
                    self.errors[src] = item.get("message", "")
                    self.oplog.write(device=self.key, action="acquire", event="failed",
                                     args={"scope": src}, error=item.get("message", ""))
            elif kind == "warning":
                if item.get("message"):
                    self.warnings[src] = item["message"]
                else:
                    self.warnings.pop(src, None)
            elif kind == "rate":
                self.rates[src] = item["hz"]
            elif kind == "file":
                _log.info("%s/%s writing %s", self.key, src, item["path"])
            else:
                data.append(item)
        self._update_state()
        return data

    def _update_state(self) -> None:
        if not self.digitizers:
            self.state = STOPPED
            return
        finished = {"stopped", "error"}
        states = [self.states.get(n, STARTING) for n in self.digitizers]
        alive = [s for s in states if s not in finished]
        if not alive:
            if self.state != STOPPED:
                files = [f for d in self.digitizers.values() for f in d.files]
                result: dict[str, Any] = {"files": files}
                skipped = {n: d.skipped for n, d in self.digitizers.items() if d.skipped}
                if skipped:  # waveforms lost to failed readouts (gaps in the data)
                    result["skipped_waveforms"] = skipped
                reconnects = {n: d.reconnects for n, d in self.digitizers.items()
                              if d.reconnects}
                if reconnects:
                    result["reconnects"] = reconnects
                if self._stop_requested:
                    self.oplog.write(device=self.key, action="stop", result=result)
                self.state = STOPPED
            return
        if self._stop_requested:
            self.state = STOPPING
        elif any(s == STARTING for s in alive):
            self.state = STARTING
        elif all(s == PAUSED for s in alive) or (
                any(d._paused.is_set() for d in self.digitizers.values())):
            self.state = PAUSED
        else:
            self.state = RUNNING
