"""Oscilloscope-style averaging for the snapshot display (user 2026-11-18).

The display gets every waveform (25 Hz) and shows the average of the last N (1, 2, 4 … 1024) or
of all since the last Clear (N = None, "∞"). Changing N restarts the average, as on a scope.

Statistics of the signal channel, per waveform i:
  offset_i = mean of the first 5 % of the points (the pre-trigger baseline)
  area_i   = sum(w_i - offset_i) * dt * 1e-3       [mV * ns * 1e-3 = nV*s, as the old program]
and over the waveforms in the average: mean offset, mean area, sample standard deviation of the
areas, N, stderr = std / sqrt(N). (The old program used the raw sum without the offset.)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

N_CHOICES: list[int | None] = [2 ** k for k in range(11)] + [None]  # 1 … 1024, ∞
OFFSET_FRACTION = 0.05
_RESUM_EVERY = 4096  # recompute the running sums now and then (float drift)


def n_label(n: int | None) -> str:
    return "∞" if n is None else str(n)


def default_n(refresh_trigger_cnt: int | None) -> int:
    """Nearest choice to the old config's refresh_trigger_cnt (100 -> 128)."""
    if not refresh_trigger_cnt:
        return 64
    finite = [n for n in N_CHOICES if n is not None]
    return min(finite, key=lambda n: abs(math.log2(n) - math.log2(refresh_trigger_cnt)))


def offset_and_area(w: np.ndarray, dt_ns: float) -> tuple[float, float]:
    k = max(1, int(len(w) * OFFSET_FRACTION))
    off = float(np.mean(w[:k]))
    return off, float(np.sum(w - off) * dt_ns * 1e-3)


@dataclass
class Stats:
    n: int
    offset_mv: float
    area: float  # nV*s, offset subtracted
    std: float
    stderr: float


class WaveAverager:
    def __init__(self, n: int | None, signal: str) -> None:
        self.signal = signal
        self.n: int | None = n
        self.clear()

    def set_n(self, n: int | None) -> None:
        self.n = n
        self.clear()

    def clear(self) -> None:
        self._entries: deque[tuple[dict[str, np.ndarray], float, float]] = deque()
        self._sums: dict[str, np.ndarray] = {}
        self._count = 0
        self._added = 0
        # statistics: sums for the finite window, Welford for ∞
        self._off_sum = self._area_sum = self._area_sq = 0.0
        self._mean = self._m2 = 0.0

    @property
    def count(self) -> int:
        return self._count

    def add(self, waves: dict[str, np.ndarray], dt_ns: float) -> None:
        waves = {ch: np.asarray(w, dtype=float) for ch, w in waves.items()}
        off, area = offset_and_area(waves[self.signal], dt_ns)
        for ch, w in waves.items():
            s = self._sums.get(ch)
            self._sums[ch] = w.copy() if s is None or s.shape != w.shape else s + w
        self._count += 1
        self._added += 1
        self._off_sum += off
        if self.n is None:
            d = area - self._mean
            self._mean += d / self._count
            self._m2 += d * (area - self._mean)
            return
        self._area_sum += area
        self._area_sq += area * area
        self._entries.append((waves, off, area))
        while len(self._entries) > self.n:
            old, o_off, o_area = self._entries.popleft()
            for ch, w in old.items():
                if ch in self._sums:
                    self._sums[ch] -= w
            self._count -= 1
            self._off_sum -= o_off
            self._area_sum -= o_area
            self._area_sq -= o_area * o_area
        if self._added % _RESUM_EVERY == 0:
            self._resum()

    def _resum(self) -> None:
        chans = self._entries[0][0].keys() if self._entries else []
        self._sums = {ch: np.sum([e[0][ch] for e in self._entries], axis=0) for ch in chans}
        self._off_sum = sum(e[1] for e in self._entries)
        self._area_sum = sum(e[2] for e in self._entries)
        self._area_sq = sum(e[2] ** 2 for e in self._entries)

    def mean_waves(self) -> dict[str, np.ndarray]:
        if not self._count:
            return {}
        return {ch: s / self._count for ch, s in self._sums.items()}

    def stats(self) -> Stats | None:
        n = self._count
        if not n:
            return None
        if self.n is None:
            mean = self._mean
            var = self._m2 / (n - 1) if n > 1 else 0.0
        else:
            mean = self._area_sum / n
            var = (self._area_sq - n * mean * mean) / (n - 1) if n > 1 else 0.0
        std = math.sqrt(max(var, 0.0))
        return Stats(n=n, offset_mv=self._off_sum / n, area=mean, std=std,
                     stderr=std / math.sqrt(n))
