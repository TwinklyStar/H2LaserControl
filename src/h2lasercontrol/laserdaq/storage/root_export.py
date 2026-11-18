"""ROOT TH2D export via uproot (ports ConvertBMP_RGB.cpp histogram writing)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import uproot
from numpy.typing import NDArray


def export_root(
    hR: NDArray,
    hG: NDArray,
    hB: NDArray,
    hB_sub: NDArray,
    path: str | Path,
) -> None:
    """Write four TH2D histograms to a ROOT file.

    Each array is (H, W) float64.  The ROOT convention from ConvertBMP_RGB.cpp
    is TH2D(name, title, W, 0, W, H, 0, H), i.e. W x-bins (columns) and H
    y-bins (rows).  uproot expects (values, x_edges, y_edges) with values shape
    (nx, ny) = (W, H) = arr.T.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    H, W = hR.shape
    x_edges = np.arange(W + 1, dtype=np.float64)
    y_edges = np.arange(H + 1, dtype=np.float64)

    with uproot.recreate(str(path)) as f:
        for name, arr in (("hR", hR), ("hG", hG), ("hB", hB), ("hB_sub", hB_sub)):
            # flipud maps image row 0 (top) → ROOT y-bin H-1 (top of histogram),
            # so ROOT y=0 is the physical bottom of the image (matching ROOT convention).
            f[name] = (np.flipud(arr).T.astype(np.float64), x_edges, y_edges)
