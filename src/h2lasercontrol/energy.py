"""Half-wave plate + PBS energy control (355 nm).

Transmitted fraction through the PBS port in use, relative to the saved maximum:
    T(θ) = cos²(2·(θ − θ_max))
so T = 1 at θ_max, T = 0 at θ_max + 45°, period 90°. Because θ_max is found by maximizing the
energy at the port actually used, this holds for either PBS port. A real PBS has finite
extinction, so the true minimum is slightly above 0 %.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


def fraction_at(angle_deg: float, max_deg: float) -> float:
    """Estimated transmitted fraction (0..1) at `angle_deg`."""
    return math.cos(math.radians(2 * (angle_deg - max_deg))) ** 2


def angle_for_fraction(fraction: float, max_deg: float) -> float:
    """Angle in [0, 360) giving `fraction` of the max energy, on the θ_max → θ_max + 45° side."""
    if not 0 <= fraction <= 1:
        raise ValueError(f"energy fraction must be 0..1, not {fraction}")
    delta = math.degrees(math.acos(math.sqrt(fraction))) / 2  # 0..45 deg
    return round((max_deg + delta) % 360, 4)


class AngleStore:
    """Saved angles written by the program (JSON), e.g. {"ell14": {"max_energy_deg": 31.03,
    "saved_at": "...", "saved_by": "..."}}. Written atomically (temp file + replace)."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def get(self, device: str) -> dict[str, Any]:
        return dict(self.load().get(device, {}))

    def update(self, device: str, **values: Any) -> dict[str, Any]:
        with self._lock:
            data = self.load()
            entry = data.setdefault(device, {})
            entry.update(values)
            entry["saved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            return dict(entry)
