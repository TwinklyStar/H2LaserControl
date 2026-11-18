"""IDS camera implementation via ids-peak + ids-peak-ipl SDK."""
from __future__ import annotations

import atexit
import enum
import logging
import time
import weakref
from typing import Iterator, cast

from ids_peak import ids_peak
from ids_peak_ipl import ids_peak_ipl
from numpy.typing import NDArray

from .base import CameraBase

_log = logging.getLogger("laserdaq.ids_camera")


class TriggerMode(enum.Enum):
    FREE_RUN = "free_run"
    SOFTWARE = "software"
    HARDWARE = "hardware"


class IDSCamera(CameraBase):
    """IDS camera via ids-peak / ids-peak-ipl SDK.

    Lifecycle (live view):
        cam = IDSCamera()
        cam.open()
        ctrl = AcquisitionController(cam)
        ctrl.start()          # calls cam.frames() in a daemon thread
        ...
        ctrl.stop()           # calls cam.close()

    Lifecycle (single-shot):
        cam = IDSCamera()
        cam.open()
        frame = cam.trigger_and_grab()   # (H, W, 4) uint8 BGRA
        cam.close()
    """

    def __init__(self, device_index: int = 0, fps: float = 10.0, serial: str | None = None) -> None:
        self._device_index = device_index
        self._serial = serial
        self._device: ids_peak.Device | None = None
        self._nodemap: ids_peak.NodeMap | None = None
        self._datastream: ids_peak.DataStream | None = None
        self._running = False
        self._acquiring = False
        self._lib_initialized = False
        self._frame_interval = 1.0 / max(fps, 0.1)
        self._stream_trigger: TriggerMode = TriggerMode.FREE_RUN
        # Metadata of the most recently yielded frame (read by the controller).
        self.last_frame_id: int | None = None
        self.last_timestamp_ns: int | None = None

    # ---- Static helpers ----

    @staticmethod
    def list_devices() -> list[tuple[str, str]]:
        """Return (serial_number, display_name) for every connected IDS device.

        Initialises and closes the library internally; safe to call before open().
        Returns [] (not raises) when no camera is connected.
        """
        ids_peak.Library.Initialize()
        try:
            ids_peak.DeviceManager.Instance().Update()
            result: list[tuple[str, str]] = []
            for dev in ids_peak.DeviceManager.Instance().Devices():
                try:
                    serial = dev.SerialNumber()
                except Exception:
                    serial = ""
                result.append((serial, dev.DisplayName()))
            return result
        finally:
            ids_peak.Library.Close()

    # ---- CameraBase interface ----

    def open(self) -> None:
        """Initialise library, open device, load defaults, alloc DMA buffers.

        Idempotent: safe to call after signal_stop() — resets the running flag
        without re-initialising the library or reopening the device.
        """
        if self._lib_initialized:
            self._running = True  # re-arm after signal_stop()
            return
        ids_peak.Library.Initialize()
        self._lib_initialized = True
        try:
            self._open_device()
        except Exception:
            # Leave the object in a clean, re-openable state (otherwise the next open()
            # would think the library is initialised and run on a half-open device).
            self._release()
            raise
        self._register_atexit()

    def _open_device(self) -> None:
        dm = ids_peak.DeviceManager.Instance()
        dm.Update()
        devices = dm.Devices()
        if not devices:
            raise RuntimeError("No IDS device found")

        if self._serial:
            dev_desc = None
            for d in devices:
                try:
                    if d.SerialNumber() == self._serial:
                        dev_desc = d
                        break
                except Exception:
                    pass
            if dev_desc is None:
                raise RuntimeError(f"Camera serial {self._serial!r} not found")
        else:
            if self._device_index >= len(devices):
                raise RuntimeError(
                    f"Device index {self._device_index} out of range "
                    f"({len(devices)} device(s) found)"
                )
            dev_desc = devices[self._device_index]
        if not dev_desc.IsOpenable(ids_peak.DeviceAccessType_Control):
            raise RuntimeError(
                "Device is not openable with control access (another program or a "
                "previous session may still hold it)"
            )

        self._device = dev_desc.OpenDevice(ids_peak.DeviceAccessType_Control)
        try:
            self._nodemap = self._device.RemoteDevice().NodeMaps()[0]
        except IndexError:
            raise RuntimeError(
                "Camera is not responding (its GenICam node map is empty). "
                "Unplug and replug the USB cable (or power-cycle the camera)."
            ) from None
        self._datastream = self._device.DataStreams()[0].OpenDataStream()

        self._load_defaults()
        self._running = True

    def _register_atexit(self) -> None:
        """Last-resort cleanup: never let the interpreter exit with the camera streaming."""
        if getattr(self, "_atexit_registered", False):
            return
        self._atexit_registered = True
        ref = weakref.ref(self)

        def _close_at_exit() -> None:
            cam = ref()
            if cam is not None and cam._lib_initialized:
                _log.warning("atexit: camera still open - closing it now")
                try:
                    cam.close()
                except Exception:  # noqa: BLE001
                    pass

        atexit.register(_close_at_exit)

    def signal_stop(self) -> None:
        """Non-blocking stop: unblock any pending WaitForFinishedBuffer.

        The controller calls this before joining the acquisition thread.
        Does NOT close the library — call close() after the thread exits.
        """
        self._running = False
        if self._datastream is not None and self._acquiring:
            try:
                self._datastream.KillWait()
            except Exception:
                pass

    def close(self) -> None:
        """Stop acquisition, revoke buffers, and close library.

        Safe to call after signal_stop() + thread.join() - _stop_acquisition() is a no-op
        if the frame thread already cleaned up via its finally block.  Every step is
        attempted even if an earlier one fails, so the camera is never left streaming.
        """
        _log.debug("close: begin  acquiring=%s", self._acquiring)
        self._running = False
        if self._acquiring:
            self._stop_acquisition()
        self._release()
        _log.debug("close: done")

    def _release(self) -> None:
        """Revoke buffers, drop the SDK wrappers, close the library (each step guarded)."""
        self._revoke_buffers()
        # Null Python wrappers so their destructors run before Library.Close().
        # Without this, the SDK's internal handle table stays "live" through the
        # close, which corrupts handles on any subsequent Library.Initialize().
        self._datastream = None
        self._nodemap = None
        self._device = None
        self._acquiring = False
        if self._lib_initialized:
            try:
                ids_peak.Library.Close()
            except Exception as exc:  # noqa: BLE001
                _log.warning("Library.Close failed: %s", exc)
            self._lib_initialized = False

    def get_exposure_limits(self) -> tuple[float, float]:
        """Return (min_us, max_us) from the device ExposureTime node."""
        if self._nodemap is None:
            raise RuntimeError("Camera not open")
        node = cast(ids_peak.FloatNode, self._nodemap.FindNode("ExposureTime"))
        return (node.Minimum(), node.Maximum())

    def set_exposure(self, us: float) -> None:
        if self._nodemap is None:
            raise RuntimeError("Camera not open")
        node = cast(ids_peak.FloatNode, self._nodemap.FindNode("ExposureTime"))
        if node.IsWriteable():
            lo, hi = node.Minimum(), node.Maximum()
            node.SetValue(float(max(lo, min(hi, us))))

    def set_gain(self, gain: float) -> None:
        self.set_analog_gain(gain)

    def _gain_limits(self, selector: str) -> tuple[float, float]:
        if self._nodemap is None:
            raise RuntimeError("Camera not open")
        sel = cast(ids_peak.EnumerationNode, self._nodemap.FindNode("GainSelector"))
        available = [e.StringValue() for e in sel.AvailableEntries()]
        if selector not in available:
            return (1.0, 1.0)
        sel.SetCurrentEntry(selector)
        node = cast(ids_peak.FloatNode, self._nodemap.FindNode("Gain"))
        return (node.Minimum(), node.Maximum())

    def get_analog_gain_limits(self) -> tuple[float, float]:
        return self._gain_limits("AnalogAll")

    def link_speed_bytes_per_s(self) -> float | None:
        """USB link speed from the camera (60e6 = USB 2.0, 400e6 = USB 3)."""
        if self._nodemap is None:
            return None
        try:
            node = cast(ids_peak.FloatNode | ids_peak.IntegerNode,
                        self._nodemap.FindNode("DeviceLinkSpeed"))
            return float(node.Value())
        except Exception:  # noqa: BLE001 - node missing on some devices
            return None

    def get_digital_gain_limits(self) -> tuple[float, float]:
        return self._gain_limits("DigitalAll")

    def set_analog_gain(self, gain: float) -> None:
        if self._nodemap is None:
            raise RuntimeError("Camera not open")
        sel = cast(ids_peak.EnumerationNode, self._nodemap.FindNode("GainSelector"))
        available = [e.StringValue() for e in sel.AvailableEntries()]
        target = next((s for s in ("AnalogAll", "All") if s in available), None)
        if target is None:
            return
        sel.SetCurrentEntry(target)
        node = cast(ids_peak.FloatNode, self._nodemap.FindNode("Gain"))
        if node.IsWriteable():
            lo, hi = node.Minimum(), node.Maximum()
            node.SetValue(float(max(lo, min(hi, gain))))

    def set_digital_gain(self, gain: float) -> None:
        if self._nodemap is None:
            raise RuntimeError("Camera not open")
        sel = cast(ids_peak.EnumerationNode, self._nodemap.FindNode("GainSelector"))
        available = [e.StringValue() for e in sel.AvailableEntries()]
        if "DigitalAll" not in available:
            return
        sel.SetCurrentEntry("DigitalAll")
        node = cast(ids_peak.FloatNode, self._nodemap.FindNode("Gain"))
        if node.IsWriteable():
            lo, hi = node.Minimum(), node.Maximum()
            node.SetValue(float(max(lo, min(hi, gain))))

    def frames(self) -> Iterator[NDArray]:
        """Yield (H, W, 3) uint8 RGB frames via continuous free-run acquisition.

        Runs until close() is called or the generator is garbage-collected.
        Automatically stops acquisition on exit.
        """
        if self._datastream is None:
            raise RuntimeError("Camera not open")
        if self._acquiring:
            _log.debug("frames: already acquiring — stopping first")
            self._stop_acquisition()
        _log.debug("frames: configuring trigger mode=%s", self._stream_trigger)
        self._configure_trigger(self._stream_trigger)
        _log.debug("frames: starting acquisition")
        self._start_acquisition()
        _log.debug("frames: acquisition started, entering loop  _running=%s", self._running)
        try:
            while self._running:
                t0 = time.monotonic()
                try:
                    buffer = self._datastream.WaitForFinishedBuffer(ids_peak.Timeout(100))
                    image_view = buffer.ToImageView()
                    ipl_img = ids_peak_ipl.Image.from_image_view(image_view)
                    rgb_img = ipl_img.ConvertTo(ids_peak_ipl.PixelFormatName_RGB8)
                    try:
                        self.last_frame_id = int(buffer.FrameID())
                        self.last_timestamp_ns = int(buffer.Timestamp_ns())
                    except Exception:  # noqa: BLE001 - metadata is best-effort
                        self.last_frame_id = self.last_timestamp_ns = None
                    self._datastream.QueueBuffer(buffer)
                    arr = rgb_img.get_numpy_3D().copy()  # copy: rgb_img released after yield
                    yield arr
                    if self._stream_trigger is TriggerMode.FREE_RUN:
                        remaining = self._frame_interval - (time.monotonic() - t0)
                        # Sleep in short slices so stop requests are honoured promptly
                        # (a 2 s sleep at 0.5 fps used to outlast the controller's join).
                        while remaining > 0 and self._running:
                            time.sleep(min(0.05, remaining))
                            remaining -= 0.05
                except ids_peak.TimeoutException:
                    continue
                except ids_peak.AbortedException:
                    if self._running:
                        # KillWait() was called between buffer-wait calls (e.g. while the
                        # thread was sleeping or processing a frame).  The SDK stores a
                        # pending-abort flag that is consumed by the *next* call to
                        # WaitForFinishedBuffer — which happens to land in the NEW thread
                        # after resume().  Detect it here: if _running is still True the
                        # abort is stale (not a real stop request) so just continue.
                        _log.debug("frames: stale AbortedException (_running=True), continuing")
                        continue
                    _log.debug("frames: AbortedException with _running=False — exiting loop")
                    break
        finally:
            _log.debug("frames: loop exited  acq=%s run=%s", self._acquiring, self._running)
            if self._acquiring:
                self._stop_acquisition()

    # ---- Single-shot capture (software trigger) ----

    def trigger_and_grab(self) -> NDArray:
        """Software-triggered single capture → (H, W, 4) uint8 BGRA.

        Acquisition is started automatically if not already running.
        Calling this method multiple times reuses the same acquisition session
        (buffers are requeued between calls).
        """
        if self._datastream is None:
            raise RuntimeError("Camera not open")
        if not self._acquiring:
            self._configure_trigger(TriggerMode.SOFTWARE)
            self._start_acquisition()
        self._fire_software_trigger()
        buffer = self._datastream.WaitForFinishedBuffer(ids_peak.Timeout(5000))
        image_view = buffer.ToImageView()
        ipl_img = ids_peak_ipl.Image.from_image_view(image_view)
        bgra_img = ipl_img.ConvertTo(ids_peak_ipl.PixelFormatName_BGRa8)
        self._datastream.QueueBuffer(buffer)
        return bgra_img.get_numpy_3D().copy()

    # ---- Trigger-mode control ----

    def set_trigger_mode(self, mode: TriggerMode) -> None:
        """Configure the camera trigger mode nodes without affecting running acquisition."""
        self._configure_trigger(mode)

    def set_fps(self, fps: float) -> None:
        self._frame_interval = 1.0 / max(fps, 0.1)

    def set_trigger_for_streaming(self, mode: str) -> None:
        self._stream_trigger = (
            TriggerMode.HARDWARE if mode == "hardware" else TriggerMode.FREE_RUN
        )

    # ---- Private helpers ----

    def _load_defaults(self) -> None:
        if self._nodemap is None:
            return
        try:
            cast(ids_peak.EnumerationNode,
                 self._nodemap.FindNode("UserSetSelector")).SetCurrentEntry("Default")
            cmd = cast(ids_peak.CommandNode, self._nodemap.FindNode("UserSetLoad"))
            cmd.Execute()
            cmd.WaitUntilDone()
        except ids_peak.Exception:
            pass  # UserSet not available on all devices

    def _alloc_buffers(self) -> None:
        if self._nodemap is None or self._datastream is None:
            return
        payload_size = cast(
            ids_peak.IntegerNode, self._nodemap.FindNode("PayloadSize")
        ).Value()
        count = self._datastream.NumBuffersAnnouncedMinRequired()
        for _ in range(count):
            buf = self._datastream.AllocAndAnnounceBuffer(payload_size)
            self._datastream.QueueBuffer(buf)

    def _revoke_buffers(self) -> None:
        if self._datastream is None:
            return
        try:
            self._datastream.Flush(ids_peak.DataStreamFlushMode_DiscardAll)
            for buf in self._datastream.AnnouncedBuffers():
                self._datastream.RevokeBuffer(buf)
        except Exception:
            pass

    def _start_acquisition(self) -> None:
        if self._nodemap is None or self._datastream is None or self._acquiring:
            _log.debug("_start_acquisition: skipped  nodemap=%s ds=%s acquiring=%s",
                       self._nodemap is not None, self._datastream is not None, self._acquiring)
            return
        target_fps = 1.0 / self._frame_interval
        try:
            fr_node = cast(ids_peak.FloatNode,
                           self._nodemap.FindNode("AcquisitionFrameRate"))
            hw_max = fr_node.Maximum()
            capped = min(hw_max, target_fps)
            fr_node.SetValue(capped)
            _log.debug("_start_acquisition: FrameRate=%.2f target=%.2f max=%.2f",
                       capped, target_fps, hw_max)
        except ids_peak.Exception as exc:
            _log.debug("_start_acquisition: AcquisitionFrameRate node unavailable: %s", exc)
        # Revoke any existing buffers and re-allocate fresh ones.
        # This avoids ambiguous states left by KillWait (buffers may be in Output,
        # Input, or In-Progress queues); a clean re-alloc is always correct.
        _log.debug("_start_acquisition: revoking and reallocating buffers")
        self._revoke_buffers()
        self._alloc_buffers()
        _log.debug("_start_acquisition: locking TLParams and starting datastream")
        cast(ids_peak.IntegerNode,
             self._nodemap.FindNode("TLParamsLocked")).SetValue(1)
        self._datastream.StartAcquisition()
        _log.debug("_start_acquisition: executing AcquisitionStart")
        cmd = cast(ids_peak.CommandNode, self._nodemap.FindNode("AcquisitionStart"))
        cmd.Execute()
        cmd.WaitUntilDone()
        self._acquiring = True
        _log.debug("_start_acquisition: done  acquiring=%s", self._acquiring)

    def _stop_acquisition(self) -> None:
        if self._nodemap is None or self._datastream is None or not self._acquiring:
            return
        _log.debug("_stop_acquisition: begin")
        # Each step in its own try so a failure in one doesn't skip the rest.
        try:
            cmd = cast(ids_peak.CommandNode, self._nodemap.FindNode("AcquisitionStop"))
            cmd.Execute()
            cmd.WaitUntilDone()  # wait for camera to fully exit acquiring state
            _log.debug("_stop_acquisition: AcquisitionStop done")
        except Exception as exc:
            _log.debug("_stop_acquisition: AcquisitionStop failed: %s", exc)
        try:
            grabbing = self._datastream.IsGrabbing()
            if grabbing:
                self._datastream.StopAcquisition(ids_peak.AcquisitionStopMode_Kill)
            self._datastream.Flush(ids_peak.DataStreamFlushMode_DiscardAll)
            _log.debug("_stop_acquisition: stopped (was_grabbing=%s) and flushed", grabbing)
        except Exception as exc:
            _log.debug("_stop_acquisition: StopAcquisition/Flush failed: %s", exc)
        try:
            cast(ids_peak.IntegerNode,
                 self._nodemap.FindNode("TLParamsLocked")).SetValue(0)
            _log.debug("_stop_acquisition: TLParamsLocked=0")
        except Exception as exc:
            _log.debug("_stop_acquisition: TLParamsLocked reset failed: %s", exc)
        self._acquiring = False
        _log.debug("_stop_acquisition: done")

    def _configure_trigger(self, mode: TriggerMode) -> None:
        if self._nodemap is None:
            return
        if mode is TriggerMode.FREE_RUN:
            cast(ids_peak.EnumerationNode,
                 self._nodemap.FindNode("TriggerMode")).SetCurrentEntry("Off")
            return

        sel = cast(ids_peak.EnumerationNode,
                   self._nodemap.FindNode("TriggerSelector"))
        available = [
            e.SymbolicValue()
            for e in sel.Entries()
            if e.AccessStatus() not in (
                ids_peak.NodeAccessStatus_NotAvailable,
                ids_peak.NodeAccessStatus_NotImplemented,
            )
        ]
        for preferred in ("ExposureStart", "FrameStart", "ReadOutStart"):
            if preferred in available:
                sel.SetCurrentEntry(preferred)
                break
        else:
            raise RuntimeError(
                "No supported trigger selector found "
                f"(tried ExposureStart/FrameStart/ReadOutStart; available: {available})"
            )

        cast(ids_peak.EnumerationNode,
             self._nodemap.FindNode("TriggerMode")).SetCurrentEntry("On")
        source = "Software" if mode is TriggerMode.SOFTWARE else "Line0"
        cast(ids_peak.EnumerationNode,
             self._nodemap.FindNode("TriggerSource")).SetCurrentEntry(source)

    def _fire_software_trigger(self) -> None:
        if self._nodemap is None:
            raise RuntimeError("Camera not open")
        cmd = cast(ids_peak.CommandNode, self._nodemap.FindNode("TriggerSoftware"))
        cmd.Execute()
        cmd.WaitUntilDone()
