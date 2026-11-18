"""Image loading."""
from __future__ import annotations

from pathlib import Path

import imageio.v3 as iio
import numpy as np
from numpy.typing import NDArray


def load_image(path: str | Path) -> NDArray[np.uint8]:
    """Load an image file and return a (H, W, 3) uint8 RGB array.

    Row 0 is the top of the image (imageio handles BMP vertical-flip).
    Supports 32-bit BGRA BMPs (the IDS camera output format): the alpha channel
    is discarded and BGR is reordered to RGB.
    """
    raw: NDArray = iio.imread(path)  # uint8, shape (H,W,C)

    if raw.ndim == 2:
        # Grayscale — replicate to 3 channels
        raw = np.stack([raw, raw, raw], axis=-1)

    if raw.shape[2] == 4:
        # RGBA / BGRA with alpha — drop alpha
        raw = raw[:, :, :3]

    # imageio/Pillow returns BMP data as RGB (handles BGR→RGB internally)
    return np.ascontiguousarray(raw, dtype=np.uint8)
