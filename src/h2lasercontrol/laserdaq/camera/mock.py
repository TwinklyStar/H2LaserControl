"""Mock camera for headless testing — cycles through paths or pre-loaded arrays."""
from __future__ import annotations

import time
from itertools import cycle
from pathlib import Path
from typing import Iterator

import numpy as np
from numpy.typing import NDArray

from ..analysis.image import load_image
from .base import CameraBase

# H2LaserControl merge: the 12 MB reference BMP is not in git; without it the mock shows the
# synthetic spot instead.
_REF_DIR = Path(__file__).resolve().parents[4] / "ref" / "camera"
_DEFAULT_ITEMS: list[Path] = [_REF_DIR / "VUV_blue1_1.bmp"]


class MockCamera(CameraBase):
    """Cycles through *items* (file paths or pre-loaded ndarray frames); yields uint8 RGB."""

    def __init__(
        self,
        items: list[NDArray | Path] | None = None,
        exposure_limits: tuple[float, float] = (100.0, 100_000.0),
        fps: float = 10.0,
        simulate_spot: bool = False,
        spot_k: float = 2.0e-5,
    ) -> None:
        self._items: list[NDArray | Path] = list(items) if items is not None else _DEFAULT_ITEMS
        if items is None and not _DEFAULT_ITEMS[0].exists():
            simulate_spot = True
        self._exposure_us: float = 10_000.0
        self._analog_gain: float = 1.0
        self._digital_gain: float = 1.0
        self._exposure_limits = exposure_limits
        self._frame_interval = 1.0 / max(fps, 0.1)
        self._running = False
        # Optional synthetic laser spot whose brightness follows exposure x gains, so
        # exposure/gain controls (and auto gain) can be tried without a camera.
        self._simulate_spot = simulate_spot
        self._spot_k = spot_k
        self._spot_profile: NDArray | None = None
        self._cache: dict[Path, NDArray] = {}
        # Metadata of the most recently yielded frame (read by the controller).
        self.last_frame_id: int | None = None
        self.last_timestamp_ns: int | None = None
        self._counter = 0

    # ---- CameraBase interface ----

    def open(self) -> None:
        self._running = True

    def close(self) -> None:
        self._running = False

    def set_exposure(self, us: float) -> None:
        lo, hi = self._exposure_limits
        self._exposure_us = max(lo, min(hi, float(us)))

    def set_gain(self, gain: float) -> None:
        self.set_analog_gain(gain)

    def get_exposure_limits(self) -> tuple[float, float]:
        return self._exposure_limits

    def get_analog_gain_limits(self) -> tuple[float, float]:
        return (1.0, 12.5)

    def get_digital_gain_limits(self) -> tuple[float, float]:
        return (1.0, 16.0)

    def set_analog_gain(self, gain: float) -> None:
        self._analog_gain = float(gain)

    def set_digital_gain(self, gain: float) -> None:
        self._digital_gain = float(gain)

    def set_fps(self, fps: float) -> None:
        self._frame_interval = 1.0 / max(fps, 0.1)

    def _spot_frame(self, h: int = 1536, w: int = 2048) -> NDArray:
        """Gaussian spot centred in the frame; channel peaks = k x exp x gains (R<G<B)."""
        if self._spot_profile is None or self._spot_profile.shape != (h, w):
            yy, xx = np.mgrid[0:h, 0:w]
            self._spot_profile = np.exp(
                -(((xx - w / 2) / 120.0) ** 2 + ((yy - h / 2) / 120.0) ** 2) / 2
            ).astype(np.float32)
        g = self._spot_profile
        level = self._spot_k * self._exposure_us * self._analog_gain * self._digital_gain * 255.0
        gains = np.array([0.6, 0.85, 1.0])
        img = g[:, :, None] * level * gains[None, None, :]
        img += 4.0  # dark offset
        return np.clip(img, 0, 255).astype(np.uint8)

    def frames(self) -> Iterator[NDArray]:
        for item in cycle(self._items):
            if not self._running:
                return
            t0 = time.monotonic()
            if self._simulate_spot:
                frame = self._spot_frame()
            elif isinstance(item, Path):
                if item not in self._cache:
                    self._cache[item] = load_image(item)
                frame = self._cache[item]
            else:
                frame = np.asarray(item, dtype=np.uint8)
            self._counter += 1
            self.last_frame_id = self._counter
            self.last_timestamp_ns = time.monotonic_ns()
            yield frame
            remaining = self._frame_interval - (time.monotonic() - t0)
            while remaining > 0 and self._running:
                time.sleep(min(0.05, remaining))
                remaining -= 0.05

    # ---- Readable state for tests ----

    @property
    def exposure_us(self) -> float:
        return self._exposure_us

    @property
    def gain(self) -> float:
        return self._analog_gain

    @property
    def analog_gain(self) -> float:
        return self._analog_gain

    @property
    def digital_gain(self) -> float:
        return self._digital_gain
