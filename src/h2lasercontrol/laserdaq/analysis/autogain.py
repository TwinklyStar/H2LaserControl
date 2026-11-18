"""Auto-gain tuning logic — pure Python, no Qt, no camera.

Brightness is modelled as proportional to ``total = exposure_us x analog_gain x digital_gain``.
The tuner measures the peak inside a region of interest (averaged over a few frames),
rescales ``total`` towards a target (half scale) and re-allocates it: exposure first,
then analog gain, then digital gain.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..config import ROIConfig

TARGET = 127.5  # half of 255
_EPS = 1e-6


@dataclass(frozen=True)
class AutoGainLimits:
    exp_min_us: float
    exp_max_us: float
    ag_min: float = 1.0
    ag_max: float = 1.0
    dg_min: float = 1.0
    dg_max: float = 1.0
    # Free run with a pulsed laser: an exposure that is not a whole number of pulse periods
    # catches 1 or 2 pulses at random.  When set, exposure snaps DOWN to a multiple of this
    # step (the gains make up the rest).
    exp_step_us: float | None = None


@dataclass(frozen=True)
class Apply:
    exp_us: float
    ag: float
    dg: float


@dataclass(frozen=True)
class Done:
    peak: float
    channel_peaks: dict[str, float]
    exp_us: float
    ag: float
    dg: float


@dataclass(frozen=True)
class Fail:
    reason: str


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def clamp_roi(roi: ROIConfig, height: int, width: int) -> tuple[int, int, int, int]:
    """Return (x0, x1, y0, y1) clipped to the frame; x1/y1 exclusive. May be empty."""
    x0 = int(_clamp(roi.xmin, 0, width))
    x1 = int(_clamp(roi.xmax, 0, width))
    y0 = int(_clamp(roi.ymin, 0, height))
    y1 = int(_clamp(roi.ymax, 0, height))
    return x0, x1, y0, y1


def roi_area(roi: ROIConfig, height: int, width: int) -> int:
    x0, x1, y0, y1 = clamp_roi(roi, height, width)
    return max(0, x1 - x0) * max(0, y1 - y0)


def crop(frame: NDArray, roi: ROIConfig) -> NDArray:
    """Copy of the ROI region of a (H, W, 3) frame (row 0 = top)."""
    h, w = frame.shape[:2]
    x0, x1, y0, y1 = clamp_roi(roi, h, w)
    return np.array(frame[y0:y1, x0:x1, :3])


def peaks_of(crops: list[NDArray]) -> tuple[float, dict[str, float], bool]:
    """(peak, per-channel peak, saturated) from already-cropped (h, w, 3) frames.

    The peak comes from the pixel-wise average of the frames; ``saturated`` is True if
    ANY single frame has a pixel at 255 in any channel (the average can hide that).
    """
    stack = np.stack(crops).astype(np.float32)
    mean = stack.mean(axis=0)
    ch = {c: float(mean[:, :, i].max()) for i, c in enumerate("RGB")}
    saturated = any(bool((c >= 255).any()) for c in crops)
    return max(ch.values()), ch, saturated


def roi_peak(
    frames: list[NDArray], roi: ROIConfig
) -> tuple[float, dict[str, float], bool]:
    """Crop each (H, W, 3) frame to *roi* and return (peak, channel peaks, saturated)."""
    return peaks_of([crop(f, roi) for f in frames])


def allocate(total: float, lim: AutoGainLimits) -> tuple[float, float, float]:
    """Split ``total`` into (exposure_us, analog gain, digital gain): exposure first."""
    exp = _clamp(total, lim.exp_min_us, lim.exp_max_us)
    if lim.exp_step_us and exp >= lim.exp_step_us:
        snapped = int(exp // lim.exp_step_us) * lim.exp_step_us
        exp = _clamp(snapped, lim.exp_min_us, lim.exp_max_us)
    ag = _clamp(total / exp, lim.ag_min, lim.ag_max)
    dg = _clamp(total / (exp * ag), lim.dg_min, lim.dg_max)
    return exp, ag, dg


def next_total(
    current_total: float, peak: float, saturated: bool, target: float = TARGET
) -> float:
    """New exposure x gain product that should bring the peak to *target*."""
    if saturated:
        return current_total * 0.5  # a clipped peak says nothing about the true level
    factor = target / max(peak, 1.0)
    return current_total * _clamp(factor, 0.25, 4.0)


class AutoGainTuner:
    """Frame-driven one-shot tuner.  Call ``feed(frame, roi)`` for every new frame.

    Returns ``None`` while collecting, then an ``Apply`` (set these camera values and keep
    feeding), ``Done`` or ``Fail``.  Frames exposed with the old settings are skipped
    (``settle`` frames after every Apply).
    """

    def __init__(
        self,
        limits: AutoGainLimits,
        start: tuple[float, float, float],
        *,
        n_avg: int = 5,
        settle: int = 2,
        tol: float = 0.10,
        max_iter: int = 10,
        target: float = TARGET,
        skip_initial: int = 0,
    ) -> None:
        self.limits = limits
        self.exp, self.ag, self.dg = (
            _clamp(start[0], limits.exp_min_us, limits.exp_max_us),
            _clamp(start[1], limits.ag_min, limits.ag_max),
            _clamp(start[2], limits.dg_min, limits.dg_max),
        )
        self.n_avg = max(1, n_avg)
        self.settle = max(0, settle)
        self.tol = tol
        self.max_iter = max_iter
        self.target = target
        self.iterations = 0
        self._skip = max(0, skip_initial)
        self._crops: list[NDArray] = []

    def skip(self, n: int) -> None:
        """Ignore the next n frames (they were exposed with the previous settings)."""
        self._skip = max(0, n)

    @property
    def settings(self) -> tuple[float, float, float]:
        return self.exp, self.ag, self.dg

    def feed(self, frame: NDArray, roi: ROIConfig) -> Apply | Done | Fail | None:
        h, w = frame.shape[:2]
        if roi_area(roi, h, w) == 0:
            return Fail("ROI is empty or outside the image")
        if self._skip > 0:
            self._skip -= 1
            return None
        self._crops.append(crop(frame, roi))
        if len(self._crops) < self.n_avg:
            return None
        crops, self._crops = self._crops, []
        return self._evaluate(crops)

    def _evaluate(self, crops: list[NDArray]) -> Apply | Done | Fail:
        peak, ch, sat = peaks_of(crops)
        self.iterations += 1
        lim = self.limits
        if not sat and abs(peak - self.target) <= self.tol * self.target:
            return Done(peak, ch, self.exp, self.ag, self.dg)

        total = self.exp * self.ag * self.dg
        new = allocate(next_total(total, peak, sat, self.target), lim)
        unchanged = (
            abs(new[0] - self.exp) <= _EPS * self.exp
            and abs(new[1] - self.ag) <= _EPS
            and abs(new[2] - self.dg) <= _EPS
        )
        if unchanged:
            if sat:
                return Fail(
                    "Too bright at minimum settings - attenuate the laser / add an ND filter"
                )
            if peak < self.target:
                return Fail("Too dim at maximum exposure and gain")
            return Done(peak, ch, self.exp, self.ag, self.dg)  # unsaturated, cannot go lower
        if self.iterations >= self.max_iter:
            return Fail(f"Did not converge in {self.max_iter} steps (peak {peak:.0f})")
        self.exp, self.ag, self.dg = new
        self._skip = self.settle
        return Apply(*new)
