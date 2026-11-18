"""Tabs for the streaming DAQ devices (F8). Unlike the device panels they have no
DeviceService: each tab owns its acquisition (Start / Pause / Stop) and its threads."""

from .camera_tab import CameraTab
from .scope_tab import ScopeTab

DAQ_TABS = {
    "picoscope": ScopeTab,
    "ids_camera": CameraTab,
}

__all__ = ["DAQ_TABS", "CameraTab", "ScopeTab"]
