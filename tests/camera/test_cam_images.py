"""Tests for storage/images.py — PNG save helpers (Step 2.1)."""
from __future__ import annotations

import pathlib

import imageio.v3 as iio
import numpy as np
import pytest

from h2lasercontrol.laserdaq.analysis.image import load_image
from h2lasercontrol.laserdaq.storage.images import save_channel_png, save_rgb_png

REF_DIR = pathlib.Path(__file__).resolve().parents[2] / "ref" / "camera"  # not in git
LASER_BMP = REF_DIR / "VUV_blue1_1.bmp"
_HAS_REF = LASER_BMP.exists()


def test_save_rgb_png_roundtrip(tmp_path):
    img = np.zeros((4, 6, 3), dtype=np.float64)
    img[1, 2, 0] = 200.0  # R channel
    img[3, 5, 2] = 128.0  # B channel
    out = tmp_path / "test.png"
    save_rgb_png(img, out)
    assert out.exists()
    reloaded = iio.imread(out)
    assert reloaded.shape == (4, 6, 3)
    assert reloaded[1, 2, 0] == 200
    assert reloaded[3, 5, 2] == 128


def test_save_rgb_png_clips(tmp_path):
    img = np.full((2, 2, 3), 300.0)
    out = tmp_path / "clipped.png"
    save_rgb_png(img, out)
    reloaded = iio.imread(out)
    assert reloaded.max() == 255


def test_save_channel_png_roundtrip(tmp_path):
    chan = np.zeros((4, 6), dtype=np.float64)
    chan[2, 3] = 150.0
    out = tmp_path / "chan.png"
    save_channel_png(chan, out)
    assert out.exists()
    reloaded = iio.imread(out)
    assert reloaded.shape == (4, 6)
    assert reloaded[2, 3] == 150


def test_save_channel_png_clips(tmp_path):
    chan = np.full((3, 3), 500.0)
    out = tmp_path / "clip.png"
    save_channel_png(chan, out)
    reloaded = iio.imread(out)
    assert reloaded.max() == 255


def test_save_rgb_png_creates_parent(tmp_path):
    img = np.zeros((2, 2, 3), dtype=np.float64)
    out = tmp_path / "subdir" / "nested" / "out.png"
    save_rgb_png(img, out)
    assert out.exists()


@pytest.mark.skipif(not _HAS_REF, reason="Ref BMP not found")
def test_save_rgb_png_from_ref(tmp_path):
    img = load_image(LASER_BMP)
    H, W = img.shape[:2]
    out = tmp_path / "ref_rgb.png"
    save_rgb_png(img, out)
    reloaded = iio.imread(out)
    assert reloaded.shape == (H, W, 3)


@pytest.mark.skipif(not _HAS_REF, reason="Ref BMP not found")
def test_save_channel_png_from_ref(tmp_path):
    img = load_image(LASER_BMP)
    H, W = img.shape[:2]
    blue = img[:, :, 2]
    out = tmp_path / "ref_blue.png"
    save_channel_png(blue, out)
    reloaded = iio.imread(out)
    assert reloaded.shape == (H, W)
