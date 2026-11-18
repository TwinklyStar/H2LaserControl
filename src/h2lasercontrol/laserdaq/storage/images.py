"""PNG save helpers — RGB frame and single-channel images."""
from __future__ import annotations

from pathlib import Path

import imageio.v3 as iio
import numpy as np
from numpy.typing import NDArray


def _as_u8(arr: NDArray) -> NDArray:
    if arr.dtype == np.uint8:
        return arr
    return np.clip(np.round(arr), 0, 255).astype(np.uint8)


def save_rgb_png(img: NDArray, path: str | Path) -> None:
    """Save a (H, W, 3) RGB array (uint8, or float clipped to 0-255) as an 8-bit PNG."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(path, _as_u8(img))


def save_channel_png(chan: NDArray, path: str | Path) -> None:
    """Save a (H, W) channel array as an 8-bit grayscale PNG."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(path, _as_u8(chan))
