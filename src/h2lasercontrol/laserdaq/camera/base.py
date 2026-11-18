"""Abstract camera interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from numpy.typing import NDArray


class CameraBase(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def signal_stop(self) -> None:
        """Non-blocking: signal frames() to stop without releasing library resources.

        The controller calls this before joining the acquisition thread, then calls
        close() afterwards.  Default implementation calls close() directly (safe for
        cameras that have no thread-unsafe teardown, e.g. MockCamera).
        """
        self.close()

    @abstractmethod
    def set_exposure(self, us: float) -> None: ...

    @abstractmethod
    def set_gain(self, gain: float) -> None: ...

    @abstractmethod
    def get_exposure_limits(self) -> tuple[float, float]: ...

    @abstractmethod
    def get_analog_gain_limits(self) -> tuple[float, float]: ...

    @abstractmethod
    def get_digital_gain_limits(self) -> tuple[float, float]: ...

    @abstractmethod
    def set_analog_gain(self, gain: float) -> None: ...

    @abstractmethod
    def set_digital_gain(self, gain: float) -> None: ...

    @abstractmethod
    def frames(self) -> Iterator[NDArray]: ...

    def set_fps(self, fps: float) -> None:
        """Update frame rate. Override in concrete cameras."""

    def link_speed_bytes_per_s(self) -> float | None:
        """Maximum data rate of the camera connection (None if unknown)."""
        return None

    def set_trigger_for_streaming(self, mode: str) -> None:
        """Set trigger mode for live streaming ('free_run' or 'hardware'). Default: no-op."""
