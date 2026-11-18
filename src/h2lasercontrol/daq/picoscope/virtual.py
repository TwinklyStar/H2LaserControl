"""Simulated PicoScope (no hardware), from H2LaserDAQ `test/VirtualDigitizer.py`.

Only the three hardware hooks are replaced; the acquisition loop, the ROOT/CSV writing and the
queue items are the real code. The time axis follows the config's timebase (3405D / 2204A
formulas from the old README), so the simulated plots look like the real ones.
Pulse: square, amplitude and width drawn from N(nominal, (5 % nominal)^2) every trigger;
channels named "Trig..." get a positive trigger pulse, the others a negative signal.
"""

from __future__ import annotations

import ctypes
import time
from typing import Any

import numpy as np

from .digitizer import Digitizer

_CHANNEL_INPUT_RANGES = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000,
                         100000, 200000]  # mV, same table as assistant.fastAdc2mV


def range_mv(text: str) -> int:
    """'200MV' / '200mV' -> 200, '2V' -> 2000."""
    t = text.strip().upper()
    return int(float(t[:-2])) if t.endswith("MV") else int(float(t[:-1]) * 1000)


def sample_interval_ns(model: str, timebase: int) -> float:
    if model == "3405D":
        return float(2 ** timebase) if timebase <= 2 else float((timebase - 2) * 8)
    return 10.0 * 2 ** timebase  # 2204A


class VirtualDigitizer(Digitizer):
    TRIGGER_RATE_HZ = 25.0

    def _init_hardware(self, config: dict[str, Any]) -> None:
        self.sample_number = int(config["sample_number"])
        self.delta_t = sample_interval_ns(self.model, int(config.get("timebase", 1)))
        self.t = np.linspace(0, (self.sample_number - 1) * self.delta_t, self.sample_number)
        self.maxADC = ctypes.c_int16(32767)
        self.ch_range = {}
        self.ch_offset = {}
        for ch in self.channels:
            self.ch_range[ch] = _CHANNEL_INPUT_RANGES.index(range_mv(config["voltage_range"][ch]))
            self.ch_offset[ch] = 0
        self.bufferMax = {ch: np.zeros(self.sample_number, dtype=np.int16)
                          for ch in self.channels}
        self._pre = int(config.get("pre_trigger", 10) / 100.0 * self.sample_number)
        self._width_ns = 0.05 * self.sample_number * self.delta_t
        self._next = time.monotonic()
        self._init_buffers()

    def _capture_block(self) -> bool:
        self._next += 1.0 / self.TRIGGER_RATE_HZ
        while time.monotonic() < self._next:
            if self._interrupted():
                self._next = time.monotonic()
                return False
            time.sleep(min(0.005, max(0.0, self._next - time.monotonic())))
        for ch in self.channels:
            vrange = _CHANNEL_INPUT_RANGES[self.ch_range[ch]]
            trig = self.channel_name[ch].lower().startswith("trig")
            nominal = min(1500.0, 0.8 * vrange) if trig else -0.5 * vrange
            amp = np.random.normal(nominal, 0.05 * abs(nominal))
            width = max(self.delta_t, np.random.normal(self._width_ns, 0.05 * self._width_ns))
            buf = np.zeros(self.sample_number, dtype=np.int32)
            end = min(self._pre + max(1, int(width / self.delta_t)), self.sample_number)
            buf[self._pre:end] = int(amp * self.maxADC.value / vrange)
            buf += np.random.randint(-200, 201, size=self.sample_number, dtype=np.int32)
            self.bufferMax[ch] = np.clip(buf, -32768, 32767).astype(np.int16)
        return True

    def _close_hardware(self) -> None:
        pass
