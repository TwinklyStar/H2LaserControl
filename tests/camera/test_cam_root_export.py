"""Tests for storage/root_export.py — ROOT TH2D export (Step 2.2)."""
from __future__ import annotations

import pathlib

import numpy as np
import pytest
import uproot

from h2lasercontrol.laserdaq.analysis.image import load_image
from h2lasercontrol.laserdaq.storage.root_export import export_root

REF_DIR = pathlib.Path(__file__).resolve().parents[2] / "ref" / "camera"  # not in git
LASER_BMP = REF_DIR / "VUV_blue1_1.bmp"
BG_BMP = REF_DIR / "background.bmp"
_HAS_REF = LASER_BMP.exists() and BG_BMP.exists()


def _make_arrays(H=8, W=10):
    rng = np.random.default_rng(42)
    hR = rng.uniform(0, 255, (H, W))
    hG = rng.uniform(0, 255, (H, W))
    hB = rng.uniform(0, 255, (H, W))
    hB_sub = hB - rng.uniform(0, 50, (H, W))
    return hR, hG, hB, hB_sub


def test_export_creates_file(tmp_path):
    hR, hG, hB, hB_sub = _make_arrays()
    out = tmp_path / "test.root"
    export_root(hR, hG, hB, hB_sub, out)
    assert out.exists()


def test_export_four_keys(tmp_path):
    hR, hG, hB, hB_sub = _make_arrays()
    out = tmp_path / "test.root"
    export_root(hR, hG, hB, hB_sub, out)
    with uproot.open(str(out)) as f:
        keys = {k.split(";")[0] for k in f.keys()}
        assert {"hR", "hG", "hB", "hB_sub"} <= keys


def test_export_shapes(tmp_path):
    H, W = 12, 15
    hR, hG, hB, hB_sub = _make_arrays(H, W)
    out = tmp_path / "shapes.root"
    export_root(hR, hG, hB, hB_sub, out)
    with uproot.open(str(out)) as f:
        for name in ("hR", "hG", "hB", "hB_sub"):
            vals = f[name].values()
            assert vals.shape == (W, H), f"{name}: expected ({W},{H}), got {vals.shape}"


def test_export_bin_values_roundtrip(tmp_path):
    H, W = 6, 8
    hR, hG, hB, hB_sub = _make_arrays(H, W)
    out = tmp_path / "vals.root"
    export_root(hR, hG, hB, hB_sub, out)
    with uproot.open(str(out)) as f:
        # After flipud: values()[col, row] == arr[H-1-row, col]
        # ROOT y=0 is the physical bottom; image row 0 is the top.
        assert f["hR"].values()[0, 0] == pytest.approx(hR[H - 1, 0], rel=1e-6)
        assert f["hR"].values()[3, 2] == pytest.approx(hR[H - 1 - 2, 3], rel=1e-6)
        assert f["hB_sub"].values()[1, 4] == pytest.approx(hB_sub[H - 1 - 4, 1], rel=1e-6)


def test_export_creates_parent(tmp_path):
    hR, hG, hB, hB_sub = _make_arrays()
    out = tmp_path / "subdir" / "out.root"
    export_root(hR, hG, hB, hB_sub, out)
    assert out.exists()


@pytest.mark.skipif(not _HAS_REF, reason="Ref BMP files not found")
def test_export_from_ref_data(tmp_path):
    sig = load_image(LASER_BMP)
    bg = load_image(BG_BMP)
    hR, hG, hB = sig[:, :, 0], sig[:, :, 1], sig[:, :, 2]
    hB_sub = hB - bg[:, :, 2]
    H, W = hR.shape

    out = tmp_path / "ref.root"
    export_root(hR, hG, hB, hB_sub, out)

    with uproot.open(str(out)) as f:
        keys = {k.split(";")[0] for k in f.keys()}
        assert {"hR", "hG", "hB", "hB_sub"} <= keys
        for name in ("hR", "hG", "hB"):
            assert f[name].values().shape == (W, H)
        # hB_sub peak should be positive (beam above background)
        assert f["hB_sub"].values().max() > 0
