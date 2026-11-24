"""Shifter tab logic (design-document F9): one-click measurements as sequences of steps.

A sequence is a list of steps; the runner starts a step only after the previous one has
finished (a feedthrough is fully inserted before the snapshot opens, user 2026-11-24). Device
steps go through the device's own worker (`DeviceService.request` -> `Driver.execute`, so every
move is logged as usual); scope and camera steps use the DAQ tabs (the same scope sessions and
the same open camera as the DAQ tabs: nothing is opened twice).

Stop halts the running step (motor stop, scope stop, camera run stop); nothing is undone.
"Return to operating state" is its own sequence and goes on after a failed step (it should get
as close to the operating state as it can) and reports every failure at the end.
"""

from __future__ import annotations

import itertools
import os
import time
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .config import PROGRAM_DIR
from .daq.picoscope.averaging import WaveAverager

SHIFTER_CONFIG = PROGRAM_DIR / "config" / "shifter.toml"
POLL_MS = 100

# outcome of a sequence
DONE, STOPPED, FAILED = "done", "stopped", "failed"


# --- settings ---------------------------------------------------------------------------------
@dataclass
class ShifterSettings:
    pulses: int = 1000
    photos: int = 100
    energy_percent_355: float = 10.0
    trigger_rate_hz: float = 25.0
    max_energy_tolerance_deg: float = 0.1
    hitmv: str = "hitmv"
    vuv_pd_axis: int = 0
    mirror_axis: int = 1
    flipmounts: str = "flipmounts"
    blocker_355: str = "flip1"
    blocker_820: str = "flip2"
    ell14: str = "ell14"
    dg645: str = "dg645"
    vuv_scope: str = "vuv_pd"
    monitor_scope: str = "scope_monitor"
    camera: str = "camera"
    vuv_scope_config: str = "H2PD_261103.toml"
    camera_config_122: str = "H2_122_Jun20.toml"
    camera_config_355: str = "H2_355_Jun20.toml"
    monitor_channels: list[str] = field(default_factory=lambda: ["NO_cell"])


def load_shifter_settings(path: str | os.PathLike[str] = SHIFTER_CONFIG) -> ShifterSettings:
    """config/shifter.toml; a missing file gives the defaults. Unknown keys are an error (typo)."""
    if not Path(path).exists():
        return ShifterSettings()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    known = {f.name for f in fields(ShifterSettings)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"{path}: unknown setting(s) {sorted(unknown)}")
    return ShifterSettings(**data)


# --- what the steps work with -----------------------------------------------------------------
class ShifterContext:
    """The devices of the program, as the Shifter tab sees them.
    services / panels: device key -> DeviceService / DevicePanel (Control tabs);
    daq: device key -> ScopeTab / CameraTab (DAQ tabs)."""

    def __init__(self, settings: ShifterSettings, services: dict[str, Any],
                 panels: dict[str, Any], daq: dict[str, Any], oplog: Any) -> None:
        self.settings = settings
        self.services = services
        self.panels = panels
        self.daq = daq
        self.oplog = oplog
        # chosen in the function boxes (drop-downs); keys: "vuv", "122", "355"
        self.choice: dict[str, str] = {"vuv": settings.vuv_scope_config,
                                       "122": settings.camera_config_122,
                                       "355": settings.camera_config_355}
        # camera config before the first profile measurement (put back by Return)
        self.camera_config_before: str | None = None

    @property
    def vuv(self) -> Any:
        return self.daq.get(self.settings.vuv_scope)

    @property
    def monitor(self) -> Any:
        return self.daq.get(self.settings.monitor_scope)

    @property
    def camera(self) -> Any:
        return self.daq.get(self.settings.camera)

    def hitmv_axis_name(self, axis: int) -> str | None:
        panel = self.panels.get(self.settings.hitmv)
        if panel is None:
            return None
        return panel.cfg.settings.get("axes", {}).get(str(axis), {}).get("name")

    def flip_label(self, unit: str) -> str:
        panel = self.panels.get(self.settings.flipmounts)
        if panel is None:
            return unit
        return panel.cfg.settings.get("units", {}).get(unit, {}).get("label", unit)


# --- steps ------------------------------------------------------------------------------------
class Step:
    """One step. `begin` starts it; it ends by calling run.step_done(result) or
    run.step_failed(message) (also later, e.g. from `poll` or a signal)."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.detail = ""  # live text shown next to the running step (e.g. "512 / 1000")

    def estimate_s(self, ctx: ShifterContext) -> float:
        return 2.0

    def begin(self, run: SequenceRunner) -> None:
        raise NotImplementedError

    def poll(self, run: SequenceRunner) -> None:
        """Called every POLL_MS while the step runs."""

    def halt(self, run: SequenceRunner) -> None:
        """Stop pressed: stop the device. The step still ends through done / failed."""

    def cleanup(self, run: SequenceRunner) -> None:
        """Called once when the step has ended (disconnect signals)."""


class DeviceStep(Step):
    """One action of a Control device (through its DeviceService, so it is logged)."""

    def __init__(self, label: str, device: str, action: str, estimate: float = 3.0,
                 **kwargs: Any) -> None:
        super().__init__(label)
        self.device = device
        self.action = action
        self.kwargs = kwargs
        self._estimate = estimate
        self.tag = ""

    def estimate_s(self, ctx: ShifterContext) -> float:
        return self._estimate

    def begin(self, run: SequenceRunner) -> None:
        svc = run.ctx.services.get(self.device)
        if svc is None:
            run.step_failed(f"device '{self.device}' is not configured")
            return
        if not svc.connected:
            run.step_failed(f"{_device_label(run.ctx, self.device)} is not connected")
            return
        self.tag = run.new_tag()
        svc.request(self.tag, self.action, **self.kwargs)

    def poll(self, run: SequenceRunner) -> None:
        """Feedthrough moves: how far in (from the device tab's live progress)."""
        panel = run.ctx.panels.get(self.device)
        info = getattr(panel, "progress_info", None) or {}
        axis = self.kwargs.get("axis")
        if axis is None or info.get("axis") != axis or info.get("position") is None:
            return
        pos = (panel.cfg.settings.get("axes", {}).get(str(axis), {}).get("positions") or {})
        ins, ret = pos.get("INSERTED"), pos.get("RETRACTED")
        if ins is not None and ret is not None and ret != ins:
            pct = 100 * (ret - info["position"]) / (ret - ins)
            self.detail = f"{min(max(pct, 0), 100):.0f} % inserted"

    def halt(self, run: SequenceRunner) -> None:
        svc = run.ctx.services.get(self.device)
        if svc is not None:
            svc.request_stop()


def _device_label(ctx: ShifterContext, key: str) -> str:
    panel = ctx.panels.get(key)
    return panel.cfg.settings.get("label", key) if panel is not None else key


class VuvMeasurement:
    """The waveforms of one VUV energy measurement: their average (CSV snapshot) and the
    area ± stderr (F9d). The preview in the tab shows the usual 128-average separately."""

    def __init__(self) -> None:
        self.averager: WaveAverager | None = None
        self.t_s: np.ndarray | None = None
        self.limit = 0
        self.tab: Any = None
        self.signal = ""
        self.signal_label = ""
        self.device = ""
        self.snapshot_dir = ""
        self.result: dict[str, Any] = {}

    @property
    def count(self) -> int:
        return self.averager.count if self.averager is not None else 0

    def attach(self, tab: Any, limit: int) -> None:
        """Start collecting the waveforms of `tab` (VUV PD ScopeTab, config already chosen)."""
        session = tab.session
        name, dcfg = next(iter(session.configs.items()))
        self.device = name
        self.signal = dcfg.get("snapshot_channel", dcfg["channels"][0])
        names = dict(zip(dcfg["channels"], dcfg["channel_name"], strict=True))
        self.signal_label = names.get(self.signal, self.signal)
        self.snapshot_dir = os.path.join(session.data_path(dcfg), "snapshots")
        self.averager = WaveAverager(None, self.signal)  # None = all waveforms
        self.limit = limit
        self.t_s = None
        self.result = {}
        self.tab = tab
        tab.items_received.connect(self.add)

    def detach(self) -> None:
        if self.tab is not None:
            try:
                self.tab.items_received.disconnect(self.add)
            except (RuntimeError, TypeError):
                pass
            self.tab = None

    def add(self, items: list[dict[str, Any]]) -> None:
        if self.averager is None:
            return
        for item in items:
            if self.count >= self.limit:
                return
            t = item.get("t")
            w = item.get(f"Ch{self.signal}")
            if t is None or w is None:
                continue
            self.t_s = np.asarray(t) * 1e-9
            self.averager.add({self.signal: w}, float(item.get("dt") or (t[1] - t[0])))

    def save(self) -> dict[str, Any]:
        """Write the CSV snapshot of the average of all waveforms; returns the result."""
        from .gui.daq.scope_views import write_snapshot_csv

        assert self.averager is not None
        st = self.averager.stats()
        wfm = self.averager.mean_waves().get(self.signal)
        if st is None or wfm is None or self.t_s is None:
            raise RuntimeError("no VUV PD waveform was received")
        path = write_snapshot_csv(self.snapshot_dir, self.device, self.signal,
                                  self.signal_label, self.t_s, wfm * 1e-3, st)
        self.result = {"area_nVs": st.area, "stderr_nVs": st.stderr, "std_nVs": st.std,
                       "n": st.n, "offset_mV": st.offset_mv, "csv": path}
        return self.result


class ScopeAcquireStep(Step):
    """Open the VUV PD snapshot with the chosen config and take exactly N waveforms (the scope
    stops by itself after N, so the ROOT file has N entries)."""

    def __init__(self, label: str, meas: VuvMeasurement) -> None:
        super().__init__(label)
        self.meas = meas
        self.n = 0
        self._started = False

    def estimate_s(self, ctx: ShifterContext) -> float:
        return 10.0 + ctx.settings.pulses / max(ctx.settings.trigger_rate_hz, 0.1)

    def begin(self, run: SequenceRunner) -> None:
        ctx = run.ctx
        tab = ctx.vuv
        self.n = ctx.settings.pulses
        self._started = False
        if tab is None:
            run.step_failed("the VUV PD snapshot is not configured")
            return
        if tab.running:
            run.step_failed("the VUV PD snapshot is already running (DAQ tab): stop it first")
            return
        config = ctx.choice.get("vuv", "")
        if not tab.select_config(config):
            run.step_failed(f"VUV PD config {config} not found")
            return
        self.meas.attach(tab, self.n)
        tab.start(max_triggers=self.n)
        self._started = True
        self.detail = "opening the scope …"

    def poll(self, run: SequenceRunner) -> None:
        if not self._started:
            return
        tab = run.ctx.vuv
        s = tab.session
        got = self.meas.count
        if got:
            self.detail = f"{got} / {self.n} pulses"
        if s.errors:
            msg = "; ".join(f"{k}: {v}" for k, v in s.errors.items())
            self._started = False
            run.step_failed(f"the VUV PD scope stopped with an error: {msg}")
        elif got >= self.n:
            self._started = False
            run.step_done({"pulses": got})
        elif s.state == "stopped":
            self._started = False
            run.step_failed(f"the VUV PD scope stopped after {got} of {self.n} pulses")

    def halt(self, run: SequenceRunner) -> None:
        if run.ctx.vuv is not None:
            run.ctx.vuv.stop()

    def cleanup(self, run: SequenceRunner) -> None:
        if run.records[run.index].state != "done":
            self.meas.detach()  # failed / stopped: no "close" step follows


class ScopeCloseStep(Step):
    """Wait until the VUV PD scope has closed its files, then save the CSV snapshot (average of
    all N waveforms) and report area ± error and the files."""

    def __init__(self, label: str, meas: VuvMeasurement) -> None:
        super().__init__(label)
        self.meas = meas

    def estimate_s(self, ctx: ShifterContext) -> float:
        return 3.0

    CLOSE_TIMEOUT_S = 15.0

    def begin(self, run: SequenceRunner) -> None:
        # the scope stops by itself after N waveforms (its thread may still be closing the
        # files); it is stopped here only if that does not happen
        self._t0 = time.monotonic()
        self.detail = "closing the files …"

    def poll(self, run: SequenceRunner) -> None:
        tab = run.ctx.vuv
        if tab.running:
            if (time.monotonic() - self._t0 > self.CLOSE_TIMEOUT_S
                    and tab.session.state != "stopping"):
                tab.stop()
            return
        self.meas.detach()
        try:
            result = self.meas.save()
        except Exception as e:  # noqa: BLE001 - shown to the user
            run.step_failed(f"could not save the snapshot: {e}")
            return
        files = tab.session.last_result.get("files", [])
        result["root"] = [f for f in files if f.endswith(".root")]
        run.step_done(result)


class ScopeStopStep(Step):
    """Return: stop the VUV PD snapshot if it runs (files closed)."""

    def begin(self, run: SequenceRunner) -> None:
        tab = run.ctx.vuv
        if tab is None or not tab.running:
            run.step_done({"note": "not running"})
            return
        tab.stop()
        self.detail = "closing the files …"

    def poll(self, run: SequenceRunner) -> None:
        if not run.ctx.vuv.running:
            run.step_done(None)


class CameraConfigStep(Step):
    """Load a camera config (exposure, gain, trigger mode) in the open camera. which = "122" /
    "355" (the box's drop-down) or "restore" (the config from before, for Return)."""

    def __init__(self, label: str, which: str) -> None:
        super().__init__(label)
        self.which = which

    def begin(self, run: SequenceRunner) -> None:
        ctx = run.ctx
        cam = ctx.camera
        if self.which == "restore":
            name = ctx.camera_config_before
            if name is None or cam is None or not cam.is_open:
                run.step_done({"note": "nothing to put back"})
                return
        else:
            if cam is None or not cam.is_open:
                run.step_failed("the camera is not open (open it in DAQ › Camera)")
                return
            name = ctx.choice.get(self.which, "")
            if ctx.camera_config_before is None:
                ctx.camera_config_before = cam.current_config()
        try:
            cam.load_config(name)
        except Exception as e:  # noqa: BLE001 - shown to the user
            run.step_failed(f"camera config {name}: {e}")
            return
        if self.which == "restore":
            ctx.camera_config_before = None
        run.step_done({"config": name})


class CameraBurstStep(Step):
    """Record N photos as a normal multi-shot run (new run folder)."""

    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.n = 0
        self._run: SequenceRunner | None = None
        self._halted = False

    def estimate_s(self, ctx: ShifterContext) -> float:
        fps = ctx.settings.trigger_rate_hz
        cam = ctx.camera
        cfg = getattr(getattr(cam, "window", None), "_config", None)
        if cfg is not None and cfg.trigger_mode == "free_run" and cfg.trigger_fps:
            fps = cfg.trigger_fps
        return 3.0 + ctx.settings.photos / max(fps, 0.1)

    def begin(self, run: SequenceRunner) -> None:
        cam = run.ctx.camera
        self.n = run.ctx.settings.photos
        self._halted = False
        if cam is None or not cam.is_open:
            run.step_failed("the camera is not open (open it in DAQ › Camera)")
            return
        self._run = run
        cam.recording_done.connect(self._on_done)
        try:
            cam.start_burst(self.n)
        except Exception as e:  # noqa: BLE001 - shown to the user
            self._disconnect(cam)
            run.step_failed(f"the photos could not start: {e}")
            return
        self.detail = f"0 / {self.n} photos"

    def poll(self, run: SequenceRunner) -> None:
        win = getattr(run.ctx.camera, "window", None)
        if win is not None:
            text = win._run_progress_label.text()  # "Recorded k/n · dropped d"
            if text:
                self.detail = text.replace("Recorded", "").strip() + " photos"

    def _on_done(self, stats: Any) -> None:
        run, self._run = self._run, None
        self._disconnect(run.ctx.camera if run else None)
        if run is None:
            return
        result = {"folder": str(stats.run_dir), "photos": stats.written,
                  "dropped": stats.dropped}
        if stats.written >= self.n and not stats.dropped:
            run.step_done(result)
        elif self._halted:
            run.step_failed(f"stopped after {stats.written} of {self.n} photos")
        else:
            run.step_failed(f"{stats.written} of {self.n} photos saved, {stats.dropped} dropped"
                            f" ({stats.run_dir})")

    def _disconnect(self, cam: Any) -> None:
        if cam is not None:
            try:
                cam.recording_done.disconnect(self._on_done)
            except (RuntimeError, TypeError):
                pass

    def halt(self, run: SequenceRunner) -> None:
        self._halted = True
        if run.ctx.camera is not None:
            run.ctx.camera.stop_burst()

    def cleanup(self, run: SequenceRunner) -> None:
        if self._run is not None:
            self._run = None
            self._disconnect(run.ctx.camera)


# --- sequences --------------------------------------------------------------------------------
@dataclass
class Sequence:
    key: str
    title: str
    steps: list[Step]
    continue_on_failure: bool = False  # Return: try every step
    vuv: VuvMeasurement | None = None

    def estimate_s(self, ctx: ShifterContext) -> float:
        return sum(s.estimate_s(ctx) for s in self.steps)


def _hitmv_times(ctx: ShifterContext) -> tuple[float, float]:
    """(insert, retract) duration estimates from the HIT-MV config."""
    panel = ctx.panels.get(ctx.settings.hitmv)
    s = panel.cfg.settings if panel is not None else {}
    travel = 30_000_000
    for ax in s.get("axes", {}).values():
        pos = ax.get("positions", {})
        if "RETRACTED" in pos and "INSERTED" in pos:
            travel = abs(pos["RETRACTED"] - pos["INSERTED"])
            break
    home = s.get("homing_max_speed") or 1_000_000
    speed = (s.get("speed") or [0, 1_000_000, 0])[1] or 1_000_000
    return travel / home + 5, travel / speed + 5


def vuv_energy(ctx: ShifterContext) -> Sequence:
    s = ctx.settings
    ins, ret = _hitmv_times(ctx)
    meas = VuvMeasurement()
    b355 = ctx.flip_label(s.blocker_355)
    return Sequence("vuv_energy", "VUV energy measurement", [
        DeviceStep(f"{b355}: insert", s.flipmounts, "insert", 2, unit=s.blocker_355),
        DeviceStep("VUV photodiode: insert", s.hitmv, "insert", ins, axis=s.vuv_pd_axis),
        ScopeAcquireStep(f"VUV PD snapshot: take {s.pulses} pulses", meas),
        ScopeCloseStep("VUV PD snapshot: close, save the result", meas),
        DeviceStep("VUV photodiode: retract", s.hitmv, "retract", ret, axis=s.vuv_pd_axis),
        DeviceStep(f"{b355}: retract", s.flipmounts, "retract", 2, unit=s.blocker_355),
    ], vuv=meas)


def profile_122(ctx: ShifterContext) -> Sequence:
    s = ctx.settings
    ins, ret = _hitmv_times(ctx)
    b355 = ctx.flip_label(s.blocker_355)
    return Sequence("profile_122", "122 nm profile measurement", [
        DeviceStep(f"{b355}: insert", s.flipmounts, "insert", 2, unit=s.blocker_355),
        CameraConfigStep("Camera: load the 122 nm config", "122"),
        DeviceStep("Projection mirror: insert", s.hitmv, "insert", ins, axis=s.mirror_axis),
        CameraBurstStep(f"Camera: take {s.photos} photos"),
        DeviceStep("Projection mirror: retract", s.hitmv, "retract", ret, axis=s.mirror_axis),
        DeviceStep(f"{b355}: retract", s.flipmounts, "retract", 2, unit=s.blocker_355),
    ])


def profile_355(ctx: ShifterContext) -> Sequence:
    s = ctx.settings
    ins, ret = _hitmv_times(ctx)
    b820 = ctx.flip_label(s.blocker_820)
    pct = f"{s.energy_percent_355:g}"
    return Sequence("profile_355", "355 nm profile measurement", [
        DeviceStep(f"{b820}: insert", s.flipmounts, "insert", 2, unit=s.blocker_820),
        DeviceStep(f"Rotation mount: {pct} % of max energy", s.ell14, "set_energy", 4,
                   percent=float(s.energy_percent_355)),
        CameraConfigStep("Camera: load the 355 nm config", "355"),
        DeviceStep("Projection mirror: insert", s.hitmv, "insert", ins, axis=s.mirror_axis),
        CameraBurstStep(f"Camera: take {s.photos} photos"),
        DeviceStep("Projection mirror: retract", s.hitmv, "retract", ret, axis=s.mirror_axis),
        DeviceStep("Rotation mount: back to max energy", s.ell14, "go_to_max_energy", 4),
        DeviceStep(f"{b820}: retract", s.flipmounts, "retract", 2, unit=s.blocker_820),
    ])


def return_to_operating(ctx: ShifterContext) -> Sequence:
    """F9f, order from the user: e) scope, a) feedthroughs, b) flip mounts, c) rotation mount,
    d) camera config."""
    s = ctx.settings
    _, ret = _hitmv_times(ctx)
    return Sequence("return", "Return to operating state", [
        ScopeStopStep("VUV PD snapshot: stop"),
        DeviceStep("VUV photodiode: retract", s.hitmv, "retract", ret, axis=s.vuv_pd_axis),
        DeviceStep("Projection mirror: retract", s.hitmv, "retract", ret, axis=s.mirror_axis),
        DeviceStep(f"{ctx.flip_label(s.blocker_355)}: retract", s.flipmounts, "retract", 2,
                   unit=s.blocker_355),
        DeviceStep(f"{ctx.flip_label(s.blocker_820)}: retract", s.flipmounts, "retract", 2,
                   unit=s.blocker_820),
        DeviceStep("Rotation mount: max energy", s.ell14, "go_to_max_energy", 4),
        CameraConfigStep("Camera: previous config", "restore"),
    ], continue_on_failure=True)


MEASUREMENTS = {"vuv_energy": vuv_energy, "profile_122": profile_122,
                "profile_355": profile_355}


# --- runner -----------------------------------------------------------------------------------
@dataclass
class StepRecord:
    state: str = "waiting"  # waiting | running | done | failed | skipped
    message: str = ""
    result: Any = None
    started: float | None = None
    ended: float | None = None


class SequenceRunner(QObject):
    changed = Signal()  # any step started / ended, and every poll while running (elapsed time)
    finished = Signal(str, str)  # outcome (done / stopped / failed), message for the user

    def __init__(self, ctx: ShifterContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.sequence: Sequence | None = None
        self.records: list[StepRecord] = []
        self.index = -1
        self.running = False
        self.stopping = False
        self.outcome = ""
        self.message = ""
        self.started_at = 0.0
        self._tags = itertools.count(1)
        self._current_tag = ""
        self._failures: list[str] = []
        for svc in ctx.services.values():  # queued into this (GUI) thread: Slot methods
            svc.request_done.connect(self._on_request_done)
            svc.request_failed.connect(self._on_request_failed)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

    # --- state for steps ----------------------------------------------------------------------
    def new_tag(self) -> str:
        self._current_tag = f"shifter-{next(self._tags)}"
        return self._current_tag

    @property
    def step(self) -> Step | None:
        if self.sequence is None or not 0 <= self.index < len(self.sequence.steps):
            return None
        return self.sequence.steps[self.index]

    # --- control ------------------------------------------------------------------------------
    def run(self, sequence: Sequence) -> None:
        if self.running:
            raise RuntimeError("a sequence is already running")
        self.sequence = sequence
        self.records = [StepRecord() for _ in sequence.steps]
        self.index = -1
        self.running = True
        self.stopping = False
        self.outcome = self.message = ""
        self._failures = []
        self.started_at = time.monotonic()
        self.ctx.oplog.write(device="shifter", action=sequence.key, event="start",
                             args={"title": sequence.title,
                                   **{k: v for k, v in self.ctx.choice.items()
                                      if sequence.key in _USES.get(k, ())}})
        self._timer.start()
        self._next()

    def stop(self) -> None:
        """Stop the running step (nothing is undone); the sequence ends after it."""
        if not self.running or self.stopping:
            return
        self.stopping = True
        step = self.step
        if step is not None:
            step.halt(self)
        self.changed.emit()

    # --- step results -------------------------------------------------------------------------
    def step_done(self, result: Any = None) -> None:
        self._end_step("done", result=result)

    def step_failed(self, message: str) -> None:
        self._end_step("failed", message=message)

    def _end_step(self, state: str, *, result: Any = None, message: str = "") -> None:
        if not self.running or self.step is None:
            return
        rec = self.records[self.index]
        if rec.state != "running":
            return
        rec.state, rec.result, rec.message, rec.ended = state, result, message, time.monotonic()
        self._current_tag = ""
        step = self.step
        step.cleanup(self)
        if state == "failed":
            self._failures.append(f"{step.label}: {message}")
        self.changed.emit()
        if self.stopping:
            self._finish(STOPPED, f"Stopped during “{step.label}”."
                         + (f" ({message})" if state == "failed" and message else ""))
        elif state == "failed" and not self.sequence.continue_on_failure:
            self._finish(FAILED, f"“{step.label}” failed: {message}")
        else:
            QTimer.singleShot(0, self._next)  # never recurse (a step may end in begin())

    def _next(self) -> None:
        if not self.running:
            return
        self.index += 1
        if self.index >= len(self.sequence.steps):
            if self._failures:
                self._finish(FAILED, "Not everything worked: " + "; ".join(self._failures))
            else:
                self._finish(DONE, "")
            return
        rec = self.records[self.index]
        rec.state, rec.started = "running", time.monotonic()
        step = self.step
        step.detail = ""
        self.changed.emit()
        try:
            step.begin(self)
        except Exception as e:  # noqa: BLE001 - a programming error must not hang the tab
            self.step_failed(f"{type(e).__name__}: {e}")

    def _finish(self, outcome: str, message: str) -> None:
        self._timer.stop()
        for rec in self.records:
            if rec.state == "waiting":
                rec.state = "skipped"
        self.running = False
        self.outcome, self.message = outcome, message
        seq = self.sequence
        result = self.summary()
        duration = time.monotonic() - self.started_at
        if outcome == DONE:
            self.ctx.oplog.write(device="shifter", action=seq.key, result=result,
                                 duration_s=duration)
        else:
            self.ctx.oplog.write(device="shifter", action=seq.key, event="failed",
                                 result=result, duration_s=duration,
                                 error=("stopped by the user: " if outcome == STOPPED else "")
                                 + message)
        self.changed.emit()
        self.finished.emit(outcome, message)

    def summary(self) -> dict[str, Any]:
        """Short result for the operation history (text) + the details."""
        seq = self.sequence
        out: dict[str, Any] = {}
        if seq is not None and seq.vuv is not None and seq.vuv.result:
            r = seq.vuv.result
            out.update(r)
            out["text"] = (f"VUV area {r['area_nVs']:.4g} ± {r['stderr_nVs']:.2g} nV·s "
                           f"(N = {r['n']})")
        for rec in self.records:
            if isinstance(rec.result, dict) and "folder" in rec.result:
                out["photos"] = rec.result
                out.setdefault("text", f"{rec.result['photos']} photos → {rec.result['folder']}")
        if self.outcome != DONE and "text" not in out:
            done = sum(r.state == "done" for r in self.records)
            out["text"] = f"{done} of {len(self.records)} steps done"
        return out

    # --- signals ------------------------------------------------------------------------------
    @Slot(str, object)
    def _on_request_done(self, tag: str, result: Any) -> None:
        if tag and tag == self._current_tag:
            self.step_done(result)

    @Slot(str, str)
    def _on_request_failed(self, tag: str, message: str) -> None:
        if tag and tag == self._current_tag:
            if "stopped on request" in message:
                message = "stopped (Stop pressed)"
            self.step_failed(message)

    @Slot()
    def _poll(self) -> None:
        step = self.step
        if self.running and step is not None and self.records[self.index].state == "running":
            try:
                step.poll(self)
            except Exception as e:  # noqa: BLE001
                self.step_failed(f"{type(e).__name__}: {e}")
        self.changed.emit()


# which drop-down choice belongs to which sequence (logged with its start)
_USES = {"vuv": ("vuv_energy",), "122": ("profile_122",), "355": ("profile_355",)}


# --- operating state (F9a) --------------------------------------------------------------------
@dataclass
class StatusItem:
    name: str
    text: str
    ok: bool  # True = as in the operating state
    blocks: tuple[str, ...] = ()  # sequence keys this item keeps from starting ("*" = all)


ALL = ("*",)


def operating_state(ctx: ShifterContext) -> list[StatusItem]:
    """One line per component, compared with the operating state (F9a)."""
    s = ctx.settings
    items: list[StatusItem] = []

    hit = ctx.panels.get(s.hitmv)
    for axis, name in ((s.vuv_pd_axis, "VUV photodiode"), (s.mirror_axis, "Projection mirror")):
        if hit is None:
            continue
        info = (hit.state.get("axes") or {}).get(ctx.hitmv_axis_name(axis) or "", {})
        if not hit.connected:
            items.append(StatusItem(name, "not connected", False, ALL))
        elif hit.state.get("positions_lost"):
            items.append(StatusItem(name, "position lost (controller restarted)", False, ALL))
        elif hit.busy or info.get("busy"):
            items.append(StatusItem(name, "moving …", False, ALL))
        elif info.get("named") == "RETRACTED":
            items.append(StatusItem(name, "retracted", True))
        elif info.get("named") == "INSERTED":
            items.append(StatusItem(name, "INSERTED (beam blocked)", False, ALL))
        else:
            items.append(StatusItem(name, "partly inserted" if info else "unknown", False, ALL))

    flips = ctx.panels.get(s.flipmounts)
    for unit in (s.blocker_355, s.blocker_820):
        if flips is None:
            continue
        name = ctx.flip_label(unit)
        info = (flips.state.get("units") or {}).get(unit, {})
        if not flips.connected or not info.get("connected"):
            items.append(StatusItem(name, "not connected", False, ALL))
        elif flips.busy or info.get("moving"):
            items.append(StatusItem(name, "moving …", False, ALL))
        elif info.get("position") == "retract":
            items.append(StatusItem(name, "retracted", True))
        elif info.get("position") == "insert":
            items.append(StatusItem(name, "INSERTED (beam blocked)", False, ALL))
        else:
            items.append(StatusItem(name, "unknown position", False, ALL))

    ell = ctx.panels.get(s.ell14)
    if ell is not None:
        st = ell.state
        pos, saved = st.get("position"), st.get("max_energy") or {}
        max_deg = saved.get("max_energy_deg")
        if not ell.connected or pos is None:
            items.append(StatusItem("Rotation mount", "not connected", False, ALL))
        elif ell.busy:
            items.append(StatusItem("Rotation mount", "moving …", False, ALL))
        elif max_deg is None:
            items.append(StatusItem("Rotation mount", "no max-energy angle saved", False, ALL))
        else:
            diff = abs((pos - max_deg + 180) % 360 - 180)
            frac = st.get("energy_fraction")
            pct = f"{100 * frac:.0f} %" if frac is not None else "?"
            text = f"{pos % 360:.2f}° ({pct} of max energy)"
            ok = diff <= s.max_energy_tolerance_deg
            items.append(StatusItem("Rotation mount", text if ok else text + ": not at max",
                                    ok, () if ok else ALL))

    dg = ctx.panels.get(s.dg645)
    if dg is not None:  # shown only; the Shifter tab never changes the delay generator
        off = dg.state.get("offset_s")
        if not dg.connected:
            items.append(StatusItem("Delay generator (C)", "not connected", False))
        elif off is None:
            items.append(StatusItem("Delay generator (C)", "not read yet", False))
        else:
            items.append(StatusItem("Delay generator (C)",
                                    f"{off * 1e6:+.1f} µs from nominal", abs(off) < 0.05e-6))

    cam = ctx.camera
    if cam is not None:
        if not cam.is_open:
            items.append(StatusItem("Camera", "closed (open it in DAQ › Camera)", False,
                                    ("profile_122", "profile_355")))
        elif cam.running:
            items.append(StatusItem("Camera", "recording …", False,
                                    ("profile_122", "profile_355")))
        else:
            cur = cam.current_config()
            items.append(StatusItem("Camera", f"open ({cur})" if cur else "open", True))

    mon = ctx.monitor
    if mon is not None:
        state = mon.session.state if mon.session is not None else "stopped"
        running = state == "running" and not (mon.session and mon.session.errors)
        items.append(StatusItem("NO cell monitor", "running" if running else state, running))

    vuv = ctx.vuv
    if vuv is not None:
        if vuv.running:
            where = "Shifter tab" if vuv.locked else "DAQ tab"
            items.append(StatusItem("VUV PD snapshot", f"running ({where})", False,
                                    ("vuv_energy",)))
        else:
            items.append(StatusItem("VUV PD snapshot", "closed", True))
    return items


def blocking(items: list[StatusItem], key: str) -> list[StatusItem]:
    """Items that keep sequence `key` from starting."""
    return [i for i in items if "*" in i.blocks or key in i.blocks]


def duration_text(seconds: float) -> str:
    if seconds < 90:
        return f"about {max(10, round(seconds / 10) * 10):.0f} s"
    return f"about {round(seconds / 60):.0f} min"
