"""One PicoScope = one worker thread. Port of H2LaserDAQ `src/H2LaserDigitizer.py`.

Acquisition maths and all output files are unchanged (F8c):
- ROOT `<data_path>/root/<output_name>_<YYMMDD>_<NNNN>.root`, tree `rawWave`, a new file every
  10000 triggers;
- continuous mode: `<data_path>/csv/<output_name>_<YYMMDD>.csv` (timestamp + summed area per
  channel in nV*s, one row per 100 triggers);
- the queue items for the GUI have the old keys.

Changes for the merged program:
- the hardware is opened and closed *inside* the thread (opening a scope takes 3-4 s and must
  not block the GUI; the SDK is then used from one thread per scope);
- Pause: no new trigger is armed and nothing is written; scope and files stay open;
- each digitizer has its own stop flag: one failing scope does not stop the others;
- a wait interrupted by Stop / Pause is aborted and NOT written (the old code wrote it);
- the 3405D is opened by its serial number (the old code opened the first 3000-series unit);
- every SDK call holds a per-DLL lock (thread safety of the drivers is not documented);
- status / warning / error / rate items for the tab header are put on the same queue;
- a failed readout (e.g. PICO_TIMEOUT: the 3405D once stalled 5 s on its USB link, M7) skips
  that one waveform and re-arms; after MAX_READOUT_FAILS in a row the scope is closed and
  reopened (PICO_NOT_RESPONDING; a fresh open works, M7) and the run goes on in the same files;
  only MAX_RECONNECTS reconnects without a good waveform end it (the old code ended the run at
  the first failure, and stopped all scopes with it). The M7 failures came from the USB
  cabling (3405D sharing a hub with the 2204As) and stopped after re-cabling.
"""

from __future__ import annotations

import csv
import ctypes
import glob
import logging
import os
import threading
import time
import traceback
from pathlib import Path
from queue import Queue
from typing import Any

import numpy as np

from . import assistant

_log = logging.getLogger(__name__)

TRIGGERS_PER_FILE = 10000  # ~400 s at 25 Hz
NO_TRIGGER_WARN_S = 10
MAX_READOUT_FAILS = 3  # failed readouts in a row -> close and reopen the scope
MAX_RECONNECTS = 3  # reconnects in a row without one good waveform -> error
RECONNECT_WAIT_S = 2.0  # between closing and reopening
_LOCKS = {"3405D": threading.RLock(), "2204A": threading.RLock()}


class DigitizerInitError(Exception):
    pass


class ReadoutError(Exception):
    """One block could not be armed or read out. The block is skipped and re-armed."""


def _status_name(status: int) -> str:
    try:
        from picosdk.constants import PICO_STATUS_LOOKUP

        return PICO_STATUS_LOOKUP.get(status, str(status))
    except ImportError:
        return str(status)


class Digitizer(threading.Thread):
    """`config` = one entry of the old DIGITIZER_CONFIGS (same keys); `data_path` resolved."""

    def __init__(self, name: str, config: dict[str, Any], update_queue: Queue,
                 data_path: str | os.PathLike[str]) -> None:
        super().__init__(name=f"pico-{name}", daemon=True)
        self.device = name
        self.config = config
        self.update_queue = update_queue
        self.trigger_per_file = TRIGGERS_PER_FILE

        self.run_mode = config.get("run_mode")
        self.serial = config.get("serial")
        self.model = config.get("model")
        self.data_path = str(data_path)
        self.output_name = config.get("output_name")
        self.channels = list(config.get("channels"))
        self.channel_name = {self.channels[i]: config.get("channel_name")[i]
                             for i in range(len(self.channels))}

        self._stop_evt = threading.Event()
        self._paused = threading.Event()
        self.state = "starting"
        self.error: Exception | None = None
        self.csv_pointer = None
        self.root_pointer = None
        self.files: list[str] = []  # output files opened so far (for the op log)
        self.skipped = 0  # waveforms lost to failed readouts (for the op log)
        self.reconnects = 0  # scope closed and reopened after repeated failures (op log)
        self._lock = _LOCKS.get(self.model, threading.RLock())
        self._hw_open = False

    # --- control (any thread) -----------------------------------------------------------------
    def stop(self) -> None:
        self._stop_evt.set()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def _interrupted(self) -> bool:
        return self._stop_evt.is_set() or self._paused.is_set()

    # --- queue messages -----------------------------------------------------------------------
    def _post(self, kind: str, **data: Any) -> None:
        self.update_queue.put({"type": kind, "source": self.device, **data})

    def _set_state(self, state: str, message: str = "") -> None:
        self.state = state
        self._post("status", state=state, message=message)

    # --- hardware hooks (overridden by the simulator) -----------------------------------------
    def _init_hardware(self, config: dict[str, Any]) -> None:
        """Must set: sample_number, t, delta_t, bufferMax, maxADC, ch_range, ch_offset."""
        if self.model == "3405D":
            self.initPico3000(config)
        elif self.model == "2204A":
            self.initPico2000(config)
        else:
            raise DigitizerInitError(f"Unknown PicoScope model {self.model!r}")

    def _capture_block(self) -> bool:
        """Wait for one trigger and fill self.bufferMax. False = interrupted (stop/pause)."""
        if self.model == "3405D":
            return self.pico3000BlockCapture()
        return self.pico2000BlockCapture()

    def _close_hardware(self) -> None:
        if self.model == "3405D":
            from picosdk.ps3000a import ps3000a
            with self._lock:
                ps3000a.ps3000aStop(self.chandle)
                ps3000a.ps3000aCloseUnit(self.chandle)
        elif self.model == "2204A":
            from picosdk.ps2000 import ps2000
            with self._lock:
                ps2000.ps2000_stop(self.chandle)
                ps2000.ps2000_close_unit(self.chandle)

    # --- thread -------------------------------------------------------------------------------
    def run(self) -> None:
        try:
            self._set_state("starting", f"opening {self.model} {self.serial}")
            self._init_hardware(self.config)
            self._hw_open = True
            os.makedirs(os.path.join(self.data_path, "root"), exist_ok=True)
            if self.run_mode == "continuous":
                os.makedirs(os.path.join(self.data_path, "csv"), exist_ok=True)
            self._run_loop()
        except Exception as e:  # noqa: BLE001 - reported to the GUI, never silent
            self.error = e
            _log.error("Digitizer %s crashed: %s\n%s", self.device, e, traceback.format_exc())
        finally:
            self._cleanup()
            if self.error is not None:
                self._set_state("error", f"{type(self.error).__name__}: {self.error}")
            else:
                self._set_state("stopped")

    def _cleanup(self) -> None:
        for what, fn in (("ROOT file", self._close_root), ("CSV file", self._close_csv),
                         ("scope", self._close_scope)):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                _log.exception("Digitizer %s: closing the %s failed", self.device, what)
                if self.error is None:
                    self.error = e

    def _close_root(self) -> None:
        if self.root_pointer is not None:
            rp, self.root_pointer = self.root_pointer, None
            rp.close()
            _log.info("[I/O] Data saved to ROOT file %s. File closed", rp.getName())

    def _close_csv(self) -> None:
        if self.csv_pointer is not None:
            cp, self.csv_pointer = self.csv_pointer, None
            cp.close()
            _log.info("[I/O] Data saved to CSV file %s. File closed", cp.name)

    def _close_scope(self) -> None:
        if self._hw_open:
            self._hw_open = False
            self._close_hardware()

    def _wait_while_paused(self) -> None:
        self._set_state("paused")
        while self._paused.is_set() and not self._stop_evt.is_set():
            time.sleep(0.05)
        if not self._stop_evt.is_set():
            self._set_state("running")

    def _run_loop(self) -> None:
        date_past = ""
        self._set_state("running")
        while not self._stop_evt.is_set():
            date = time.strftime("%y%m%d")  # local date, as the old datetime.today()

            # -- open ROOT file -----------------------------------------------------------------
            today_root_number = len(glob.glob(os.path.join(
                self.data_path, "root", f"{self.output_name}_{date}*.root")))
            root_name = os.path.join(self.data_path, "root",
                                     f"{self.output_name}_{date}_{today_root_number:04d}.root")
            self.root_pointer = assistant.RootManager(
                filename=root_name, runN=0, chunk_size=1000,
                sample_num=self.sample_number, add_channels=self.channels,
            )
            self.root_pointer.start_thread()
            self.files.append(root_name)
            self._post("file", path=root_name)
            _log.info("[I/O] Opening ROOT file %s", root_name)

            # -- open CSV file (continuous mode, daily rotation) ---------------------------------
            if self.run_mode == "continuous" and date_past != date:
                csv_fullpath = os.path.join(self.data_path, "csv", f"{self.output_name}_{date}.csv")
                file_exists = os.path.exists(csv_fullpath)
                self._close_csv()
                self.csv_pointer = open(csv_fullpath, "a", newline="")  # noqa: SIM115
                self.files.append(csv_fullpath)
                self._post("file", path=csv_fullpath)
                _log.info("[I/O] Opening CSV file %s", csv_fullpath)
                self.csv_writer = csv.DictWriter(
                    self.csv_pointer,
                    fieldnames=["timestamp", *self.channel_name.values()],
                )
                if not file_exists:
                    self.csv_writer.writeheader()
                date_past = date

            # -- inner trigger loop -------------------------------------------------------------
            trigger_cnt = 0
            time_start = time.time()
            rate_cnt = 0
            fails = 0  # failed readouts in a row
            reconnects = 0  # reconnects since the last good waveform
            while trigger_cnt < self.trigger_per_file and not self._stop_evt.is_set():
                if self._paused.is_set():
                    self._wait_while_paused()
                    time_start, rate_cnt = time.time(), 0
                    continue
                try:
                    captured = self._capture_block()
                except ReadoutError as e:
                    fails += 1
                    self.skipped += 1
                    _log.warning("%s %s %s: %s (%d in a row, %d skipped in this run)",
                                 self.device, self.model, self.serial, e, fails, self.skipped)
                    if fails < MAX_READOUT_FAILS:
                        self._post("warning", message=(
                            f"{time.strftime('%H:%M:%S')} readout failed ({e}): waveform"
                            f" skipped, {self.skipped} skipped so far"))
                        continue
                    reconnects += 1
                    if reconnects > MAX_RECONNECTS:
                        raise ReadoutError(
                            f"{e}; still failing after {MAX_RECONNECTS} reconnects") from e
                    self._reconnect(str(e), reconnects)
                    fails = 0
                    time_start, rate_cnt = time.time(), 0
                    continue
                fails = reconnects = 0
                if not captured:  # interrupted: nothing captured, nothing written
                    continue
                trigger_cnt += 1
                rate_cnt += 1

                wave = {"Time": self.t}
                for ch_idx in self.channels:
                    wave[f"Ch{ch_idx}"] = assistant.fastAdc2mV(
                        self.bufferMax[ch_idx], self.ch_range[ch_idx], self.maxADC,
                        self.ch_offset[ch_idx],
                    )
                self.root_pointer.fill(**wave)

                if self.run_mode == "continuous":
                    for ch_idx in self.channels:
                        self.peak_area_buffer[ch_idx] += (
                            np.sum(wave[f"Ch{ch_idx}"]) * self.delta_t / 100 * 1e-3
                        )  # mV*ns -> nV*s
                        self.avg_wave_buffer[ch_idx] += wave[f"Ch{ch_idx}"] / 100
                    if trigger_cnt % 100 == 0:
                        csv_row = {"timestamp": time.time()}
                        for ch_idx in self.channels:
                            csv_row[self.channel_name[ch_idx]] = self.peak_area_buffer[ch_idx]
                            self.update_queue.put({
                                "channel_name": self.channel_name[ch_idx],
                                "timestamp": csv_row["timestamp"],
                                "value": csv_row[self.channel_name[ch_idx]],
                                "wfm_t": self.t,
                                "wfm": self.avg_wave_buffer[ch_idx].copy(),
                            })
                        for ch_idx in self.channels:
                            self.avg_wave_buffer[ch_idx].fill(0)
                            self.peak_area_buffer[ch_idx] = 0
                        self.csv_writer.writerow(csv_row)
                        self.csv_pointer.flush()

                elif self.run_mode == "snapshot":
                    self.peak_area_buffer.append(
                        np.sum(wave[f"Ch{self.snapshot_channel}"]) * self.delta_t * 1e-3
                    )  # mV*ns -> nV*s
                    for ch_idx in self.channels:
                        self.avg_wave_buffer[ch_idx] += (
                            wave[f"Ch{ch_idx}"] / self.refresh_trigger_cnt
                        )
                    if trigger_cnt % self.refresh_trigger_cnt == 0:
                        queue_dic = {
                            "device": self.device,
                            "t": self.t,
                            "area_avg": np.mean(self.peak_area_buffer),
                            "area_std": np.std(self.peak_area_buffer),
                            "trigger_cnt": self.refresh_trigger_cnt,
                        }
                        for ch_idx in self.channels:
                            queue_dic[f"Ch{ch_idx}"] = self.avg_wave_buffer[ch_idx].copy()
                        self.update_queue.put(queue_dic)
                        for ch_idx in self.channels:
                            self.avg_wave_buffer[ch_idx].fill(0)
                        self.peak_area_buffer.clear()

                # -- trigger rate (the old program printed it every 1000 triggers) --------------
                elapsed = time.time() - time_start
                if elapsed >= 5.0:
                    self._post("rate", hz=rate_cnt / elapsed, triggers=trigger_cnt)
                    time_start, rate_cnt = time.time(), 0

            self._close_root()

    def _reconnect(self, reason: str, attempt: int) -> None:
        """Close and reopen the scope; files and the running sums (CSV row) are kept.
        An error while reopening (scope gone) ends the run."""
        now = time.strftime("%H:%M:%S")
        _log.warning("%s %s %s: not responding (%s): reconnecting, try %d/%d", self.device,
                     self.model, self.serial, reason, attempt, MAX_RECONNECTS)
        self._post("warning", message=(
            f"{now} scope not responding ({reason}): reconnecting"
            f" (try {attempt}/{MAX_RECONNECTS})"))
        keep = (self.peak_area_buffer, self.avg_wave_buffer)
        try:
            self._close_scope()
        except Exception:  # noqa: BLE001 - the scope is reopened anyway
            _log.exception("%s: closing the scope before reconnecting failed", self.device)
        if self._stop_evt.wait(RECONNECT_WAIT_S):
            return
        self._init_hardware(self.config)
        self._hw_open = True
        self.peak_area_buffer, self.avg_wave_buffer = keep
        self.reconnects += 1
        _log.info("%s: reconnected (%d reconnects in this run)", self.device, self.reconnects)
        self._post("warning", message=(
            f"{now} scope reconnected after: {reason}; {self.skipped} waveforms skipped so far"))

    def _init_buffers(self) -> None:
        if self.run_mode == "continuous":
            self.peak_area_buffer = {ch: 0 for ch in self.channels}
            self.avg_wave_buffer = {ch: np.zeros(self.sample_number) for ch in self.channels}
        elif self.run_mode == "snapshot":
            self.snapshot_channel = self.config.get("snapshot_channel")
            self.refresh_trigger_cnt = self.config.get("refresh_trigger_cnt")
            self.peak_area_buffer = []
            self.avg_wave_buffer = {ch: np.zeros(self.sample_number) for ch in self.channels}
        else:
            raise DigitizerInitError(f"{self.device}: unknown run_mode {self.run_mode!r}")

    def _wait_for_trigger(self, is_ready) -> bool:
        """Poll `is_ready()` every 10 ms. False if stop/pause came first."""
        warn_after = NO_TRIGGER_WARN_S
        start = time.time()
        warned = False
        while not is_ready():
            if self._interrupted():
                return False
            if time.time() - start > warn_after:
                msg = f"No trigger for {warn_after} s"
                _log.warning("%s %s %s: %s", self.device, self.model, self.serial, msg)
                self._post("warning", message=msg)
                warned = True
                warn_after += NO_TRIGGER_WARN_S
            time.sleep(0.01)
        if warned:
            self._post("warning", message="")
        return True

    # ------------------------------------------------------------------------------------------
    # PicoScope 3405D (PS3000A)
    # ------------------------------------------------------------------------------------------
    def initPico3000(self, config: dict[str, Any]) -> None:
        from picosdk.functions import mV2adc
        from picosdk.ps3000a import ps3000a

        lock = self._lock
        self.status = {}
        self.chandle = ctypes.c_int16()
        with lock:
            self.status["openunit"] = ps3000a.ps3000aOpenUnit(
                ctypes.byref(self.chandle), ctypes.c_char_p(str(self.serial).encode()))
        st = self.status["openunit"]
        if st in (282, 286):  # power supply not connected / USB 3 device on a USB 2 port
            with lock:
                st = ps3000a.ps3000aChangePowerSource(self.chandle, st)
        if st != 0 or self.chandle.value <= 0:
            raise DigitizerInitError(
                f"PicoScope {self.model} {self.serial} not found (status {self.status['openunit']})."
                " Is it plugged in, and closed in PicoScope 7?")
        self._hw_open = True
        _log.info("[INIT] Specified digitizer %s %s found", self.model, self.serial)

        def ok(name: str, status: int, what: str) -> None:
            self.status[name] = status
            if status != 0:
                raise DigitizerInitError(f"{self.device}: {what} (PicoStatus {status})")

        self.ch_range = {}
        self.ch_offset = {}
        with lock:
            for ch_idx in self.channels:
                self.ch_range[ch_idx] = ps3000a.PS3000A_RANGE[
                    "PS3000A_" + config.get("voltage_range")[ch_idx]]
                self.ch_offset[ch_idx] = config.get("offset")[ch_idx]
                ok("setCh" + ch_idx, ps3000a.ps3000aSetChannel(
                    self.chandle, ps3000a.PS3000A_CHANNEL["PS3000A_CHANNEL_" + ch_idx], 1,
                    ps3000a.PS3000A_COUPLING["PS3000A_DC"], self.ch_range[ch_idx],
                    self.ch_offset[ch_idx]), f"Fail to initialize channel {ch_idx}")
            for ch_idx in sorted({"A", "B", "C", "D"} - set(self.channels)):
                ok("setCh" + ch_idx, ps3000a.ps3000aSetChannel(
                    self.chandle, ps3000a.PS3000A_CHANNEL["PS3000A_CHANNEL_" + ch_idx], 0,
                    ps3000a.PS3000A_COUPLING["PS3000A_DC"], ps3000a.PS3000A_RANGE["PS3000A_2V"],
                    0), f"Fail to disable channel {ch_idx}")

            trigger_channel = config.get("trigger_channel")
            trigger_level_mV = config.get("trigger_level")
            self.maxADC = ctypes.c_int16()
            ok("maximumValue", ps3000a.ps3000aMaximumValue(
                self.chandle, ctypes.byref(self.maxADC)), "MaximumValue failed")
            if trigger_channel == "Ext":
                trig_ch_handle = ps3000a.PS3000A_CHANNEL["PS3000A_EXTERNAL"]
                trigger_level_ADC = assistant.extTrigmV2Adc(trigger_level_mV)
            else:
                trig_ch_handle = ps3000a.PS3000A_CHANNEL["PS3000A_CHANNEL_" + trigger_channel]
                trigger_level_ADC = mV2adc(trigger_level_mV, self.ch_range[trigger_channel],
                                           self.maxADC)
            ok("trigger", ps3000a.ps3000aSetSimpleTrigger(
                self.chandle, 1, trig_ch_handle, trigger_level_ADC,
                ps3000a.PS3000A_THRESHOLD_DIRECTION["PS3000A_" + config.get("trigger_edge")],
                config.get("trigger_delay"), config.get("auto_trigger")), "Fail to set trigger")

            self.sample_number = config.get("sample_number")
            self.preTriggerSamples = int(config.get("pre_trigger") / 100.0 * self.sample_number)
            self.postTriggerSamples = self.sample_number - self.preTriggerSamples
            maxsamples = self.sample_number
            self.timebase = config.get("timebase")
            timeIntervalns = ctypes.c_float()
            returnedMaxSamples = ctypes.c_int16()
            ok("GetTimebase", ps3000a.ps3000aGetTimebase2(
                self.chandle, self.timebase, maxsamples, ctypes.byref(timeIntervalns), 1,
                ctypes.byref(returnedMaxSamples), 0), f"Incorrect timebase {self.timebase}")

            self.cmaxSamples = ctypes.c_int32(maxsamples)
            self.bufferMax = {}
            self.bufferMin = {}
            for ch_idx in self.channels:
                self.bufferMax[ch_idx] = np.zeros(maxsamples, dtype=np.int16)
                self.bufferMin[ch_idx] = np.zeros(maxsamples, dtype=np.int16)
                ok("SetDataBuffers", ps3000a.ps3000aSetDataBuffers(
                    self.chandle, ps3000a.PS3000A_CHANNEL["PS3000A_CHANNEL_" + ch_idx],
                    self.bufferMax[ch_idx].ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                    self.bufferMin[ch_idx].ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                    maxsamples, 0, 0), "Fail to set data buffer")

        self.overflow = (ctypes.c_int16 * 10)()
        self.t = np.linspace(0, (self.cmaxSamples.value - 1) * timeIntervalns.value,
                             self.cmaxSamples.value)
        self.delta_t = timeIntervalns.value
        self._init_buffers()
        _log.info("[INIT] %s: %d samples at %s ns", self.device, maxsamples, self.delta_t)

    def pico3000BlockCapture(self) -> bool:
        from picosdk.ps3000a import ps3000a

        def failed(what: str, status: int) -> ReadoutError:
            with self._lock:
                ps3000a.ps3000aStop(self.chandle)  # drop the block, ready to re-arm
            return ReadoutError(f"{what} returned {_status_name(status)}")

        with self._lock:
            self.status["runblock"] = ps3000a.ps3000aRunBlock(
                self.chandle, self.preTriggerSamples, self.postTriggerSamples, self.timebase,
                1, None, 0, None, None)
        if self.status["runblock"] != 0:
            raise failed("RunBlock", self.status["runblock"])
        ready = ctypes.c_int16(0)

        def is_ready() -> bool:
            with self._lock:
                ps3000a.ps3000aIsReady(self.chandle, ctypes.byref(ready))
            return ready.value != 0

        if not self._wait_for_trigger(is_ready):
            with self._lock:
                ps3000a.ps3000aStop(self.chandle)  # abort the armed block
            return False
        with self._lock:
            self.status["GetValues"] = ps3000a.ps3000aGetValues(
                self.chandle, 0, ctypes.byref(self.cmaxSamples), 0, 0, 0,
                ctypes.byref(self.overflow))
        if self.status["GetValues"] != 0:
            raise failed("GetValues", self.status["GetValues"])
        return True

    # ------------------------------------------------------------------------------------------
    # PicoScope 2204A (PS2000)
    # ------------------------------------------------------------------------------------------
    def initPico2000(self, config: dict[str, Any]) -> None:
        from picosdk.functions import mV2adc
        from picosdk.ps2000 import ps2000

        lock = self._lock
        self.status = {}
        # ps2000_open_unit opens the next *free* unit (no serial argument): open all free
        # units, keep ours, close the rest (as the old code). Under the lock, so two tabs
        # starting at once cannot grab each other's unit.
        with lock:
            handles = {}
            while True:
                h = ps2000.ps2000_open_unit()
                if h <= 0:
                    break
                handles[self.getPico2000Serial(h)] = h
            self.chandle = None
            for serial, handle in handles.items():
                if serial == self.serial:
                    self.chandle = ctypes.c_int16(handle)
                else:
                    ps2000.ps2000_close_unit(ctypes.c_int16(handle))
        _log.info("%d free PicoScope 2000 unit(s) found: %s", len(handles), list(handles))
        if self.chandle is None:
            raise DigitizerInitError(
                f"PicoScope {self.model} {self.serial} not found (free units: "
                f"{', '.join(handles) or 'none'}). Is it plugged in, and closed in PicoScope 7?")
        self._hw_open = True

        def ok(name: str, status: int, what: str) -> None:
            self.status[name] = status
            if status == 0:  # ps2000 functions return 0 on failure
                raise DigitizerInitError(f"{self.device}: {what}")

        self.ch_range = {}
        self.ch_offset = {"A": 0, "B": 0}
        with lock:
            for ch_idx in self.channels:
                self.ch_range[ch_idx] = ps2000.PS2000_VOLTAGE_RANGE[
                    "PS2000_" + config.get("voltage_range")[ch_idx]]
                ok("setCh" + ch_idx, ps2000.ps2000_set_channel(
                    self.chandle, ps2000.PS2000_CHANNEL["PS2000_CHANNEL_" + ch_idx], 1,
                    ps2000.PICO_COUPLING["DC"], self.ch_range[ch_idx]),
                    f"Fail to initialize channel {ch_idx}")
            for ch_idx in sorted({"A", "B"} - set(self.channels)):
                ok("setCh" + ch_idx, ps2000.ps2000_set_channel(
                    self.chandle, ps2000.PS2000_CHANNEL["PS2000_CHANNEL_" + ch_idx], 0,
                    ps2000.PICO_COUPLING["DC"], ps2000.PS2000_VOLTAGE_RANGE["PS2000_2V"]),
                    f"Fail to disable channel {ch_idx}")

            trigger_channel = config.get("trigger_channel")
            self.maxADC = ctypes.c_int16(32767)
            trigger_level_ADC = mV2adc(config.get("trigger_level"),
                                       self.ch_range[trigger_channel], self.maxADC)
            trigger_type = 0 if config.get("trigger_edge") == "RISING" else 1
            ok("trigger", ps2000.ps2000_set_trigger(
                self.chandle, ps2000.PS2000_CHANNEL["PS2000_CHANNEL_" + trigger_channel],
                trigger_level_ADC, trigger_type, config.get("pre_trigger") * -1,
                config.get("auto_trigger")), "Fail to set trigger")

            self.sample_number = config.get("sample_number")
            maxsamples = self.sample_number
            self.timebase = config.get("timebase")
            timeInterval = ctypes.c_int32()
            timeUnits = ctypes.c_int32()
            maxSamplesReturn = ctypes.c_int32()
            ok("getTimebase", ps2000.ps2000_get_timebase(
                self.chandle, self.timebase, maxsamples, ctypes.byref(timeInterval),
                ctypes.byref(timeUnits), ctypes.c_int16(1), ctypes.byref(maxSamplesReturn)),
                f"Incorrect timebase {self.timebase}")

        self.cmaxSamples = ctypes.c_int32(maxsamples)
        self.pico2000_timeIndisposedms = ctypes.c_int32()
        self.bufferMax = {"A": np.zeros(maxsamples, dtype=np.int16),
                          "B": np.zeros(maxsamples, dtype=np.int16)}
        self.t = np.linspace(0, (self.cmaxSamples.value - 1) * timeInterval.value,
                             self.cmaxSamples.value)
        self.delta_t = timeInterval.value
        self._init_buffers()
        _log.info("[INIT] %s: %d samples at %s ns", self.device, maxsamples, self.delta_t)

    def getPico2000Serial(self, handle: int) -> str:
        from picosdk.ps2000 import ps2000

        buf = ctypes.create_string_buffer(64)
        ps2000.ps2000_get_unit_info(ctypes.c_int16(handle), buf, ctypes.c_int16(len(buf)),
                                    ctypes.c_int16(4))
        return buf.value.decode(errors="ignore")

    def pico2000BlockCapture(self) -> bool:
        from picosdk.ps2000 import ps2000

        # ps2000 returns <= 0 for failure (no status codes)
        def failed(what: str) -> ReadoutError:
            with self._lock:
                ps2000.ps2000_stop(self.chandle)
            return ReadoutError(f"{what} failed")

        oversample = ctypes.c_int16(1)
        with self._lock:
            self.status["runBlock"] = ps2000.ps2000_run_block(
                self.chandle, self.sample_number, self.timebase, oversample,
                ctypes.byref(self.pico2000_timeIndisposedms))
        if self.status["runBlock"] <= 0:  # as picosdk's assert_pico2000_ok
            raise failed("run_block")

        def is_ready() -> bool:
            with self._lock:
                return ps2000.ps2000_ready(self.chandle) != 0

        if not self._wait_for_trigger(is_ready):
            with self._lock:
                ps2000.ps2000_stop(self.chandle)  # abort the armed block
            return False
        with self._lock:
            self.status["getValues"] = ps2000.ps2000_get_values(
                self.chandle,
                self.bufferMax["A"].ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                self.bufferMax["B"].ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                None, None, ctypes.byref(oversample), self.cmaxSamples)
        if self.status["getValues"] <= 0:
            raise failed("get_values")
        return True


def resolve_data_path(data_path: str, base: str | os.PathLike[str]) -> Path:
    p = Path(data_path)
    return p if p.is_absolute() else Path(base) / p
