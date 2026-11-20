"""Device tab classes by device type. A new device type = a new panel class registered here;
another device of a known type needs only a config entry (it gets its own tab automatically)."""

from .base import DevicePanel
from .dg645_panel import Dg645Panel
from .ell14_panel import Ell14Panel
from .hitmv_panel import HitMvPanel
from .mff_panel import MffPanel

PANELS: dict[str, type[DevicePanel]] = {
    "hitmv": HitMvPanel,
    "ell14": Ell14Panel,
    "mff": MffPanel,
    "dg645": Dg645Panel,
}

__all__ = ["PANELS", "DevicePanel"]
