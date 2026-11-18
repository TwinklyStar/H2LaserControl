"""Tests for analysis/image.py — load_image."""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

from h2lasercontrol.laserdaq.analysis.image import load_image

REF_DIR = pathlib.Path(__file__).resolve().parents[2] / "ref" / "camera"  # not in git
LASER_BMP = REF_DIR / "VUV_blue1_1.bmp"
BG_BMP = REF_DIR / "background.bmp"

_HAS_REF = LASER_BMP.exists() and BG_BMP.exists()


# ---------------------------------------------------------------------------
# Tests against real Ref BMP files
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_REF, reason="Ref BMP files not found")
def test_load_shape_is_3channel_uint8():
    img = load_image(LASER_BMP)
    assert img.ndim == 3
    assert img.shape[2] == 3
    assert img.dtype == np.uint8
    H, W, _ = img.shape
    assert H > 0 and W > 0


@pytest.mark.skipif(not _HAS_REF, reason="Ref BMP files not found")
def test_background_and_laser_same_shape():
    laser = load_image(LASER_BMP)
    bg = load_image(BG_BMP)
    assert laser.shape == bg.shape, "signal and background must have the same dimensions"
