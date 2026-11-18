"""Acquisition controller — camera frame loop runs in a daemon thread."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from PySide6.QtCore import QObject, Signal

from .base import CameraBase

_log = logging.getLogger("laserdaq.controller")


class AcquisitionController(QObject):
    """Emits frame_ready(ndarray) from a background thread.

    Cross-thread signal delivery uses Qt's queued-connection mechanism
    (the default when sender and receiver are in different threads).
    Use Qt.DirectConnection in tests to receive signals without an event loop.

    display_fps caps how many frames per second are forwarded to the GUI.
    Back-pressure: if the GUI is still rendering the previous frame, the next
    frame is dropped on the camera side before it enters the Qt queue. This
    guarantees the queue never holds more than one frame at a time, preventing
    unbounded memory growth when setImage is slower than the frame interval.
    """

    frame_ready: Signal = Signal(object)
    fps_updated: Signal = Signal(float)         # display fps (after back-pressure)
    camera_fps_updated: Signal = Signal(float)  # camera/operation fps (all received frames)
    error_occurred: Signal = Signal(str)
    recording_progress: Signal = Signal(int, int, int)  # submitted, written, dropped
    recording_finished: Signal = Signal(object)         # RecordStats

    def __init__(
        self,
        camera: CameraBase,
        parent: QObject | None = None,
        display_fps: float = 15.0,
    ) -> None:
        super().__init__(parent)
        self._camera = camera
        self._thread: threading.Thread | None = None
        self._running = False
        self._min_interval = 1.0 / max(display_fps, 1.0)
        # Back-pressure flag: set = GUI ready for next frame, clear = GUI busy.
        self._display_ready = threading.Event()
        self._display_ready.set()
        # Camera settings requested from other threads; written by the acquisition thread
        # between frames so the SDK is never used from two threads at once.
        self._settings_lock = threading.Lock()
        self._pending_settings: dict[str, float] = {}
        self._last_recv = time.monotonic()
        # Recording: set by the GUI/CLI thread, read by the acquisition thread.
        self._rec_lock = threading.Lock()
        self._recorder = None
        self._rec_remaining: int | None = None

    # ---- Camera settings (always applied on the acquisition thread) ----

    def apply_settings(
        self,
        *,
        exposure_us: float | None = None,
        analog_gain: float | None = None,
        digital_gain: float | None = None,
    ) -> None:
        """Change exposure / gains without touching the SDK from the caller's thread.

        While the acquisition thread runs, the values are queued (latest wins) and written
        by that thread right after the next frame; otherwise they are written directly.
        """
        updates = {
            k: float(v)
            for k, v in (
                ("exposure_us", exposure_us),
                ("analog_gain", analog_gain),
                ("digital_gain", digital_gain),
            )
            if v is not None
        }
        if not updates:
            return
        thread = self._thread
        if thread is not None and thread.is_alive():
            with self._settings_lock:
                self._pending_settings.update(updates)
        else:
            self._write_settings(updates)

    def _write_settings(self, updates: dict[str, float]) -> None:
        cam = self._camera
        try:
            if "exposure_us" in updates:
                cam.set_exposure(updates["exposure_us"])
            if "analog_gain" in updates:
                cam.set_analog_gain(updates["analog_gain"])
            if "digital_gain" in updates:
                cam.set_digital_gain(updates["digital_gain"])
        except Exception as exc:  # noqa: BLE001
            _log.exception("applying camera settings failed")
            self.error_occurred.emit(f"Could not set camera parameters: {exc}")

    def _drain_settings(self) -> None:
        with self._settings_lock:
            updates, self._pending_settings = self._pending_settings, {}
        if updates:
            t0 = time.monotonic()
            self._write_settings(updates)
            _log.debug("settings %s written in %.0f ms", updates, (time.monotonic() - t0) * 1000)

    @property
    def idle_seconds(self) -> float:
        """Seconds since the camera last delivered a frame (large => camera stalled)."""
        return time.monotonic() - self._last_recv

    # ---- Recording (every camera frame, independent of display throttling) ----

    def start_recording(self, recorder, n_frames: int | None = None) -> None:
        """Hand the next ``n_frames`` camera frames to *recorder* (None = until stopped).

        The recorder is started here.  When the quota is reached, or on
        stop_recording(), it is stopped on a helper thread (never the acquisition
        thread) and ``recording_finished(RecordStats)`` is emitted exactly once.
        """
        with self._rec_lock:
            if self._recorder is not None:
                raise RuntimeError("A recording is already in progress")
            recorder.start()
            self._recorder = recorder
            self._rec_remaining = n_frames

    def stop_recording(self) -> None:
        """End the current recording early (no-op if none is active)."""
        self._finish_recording()

    @property
    def recording(self) -> bool:
        return self._recorder is not None

    def _finish_recording(self) -> None:
        with self._rec_lock:
            rec, self._recorder = self._recorder, None
            self._rec_remaining = None
        if rec is None:
            return

        def _work() -> None:
            stats = rec.stop()
            self.recording_finished.emit(stats)

        threading.Thread(target=_work, daemon=True, name="daq-rec-stop").start()

    def set_display_fps(self, fps: float) -> None:
        """Change the cap on frames forwarded to the GUI (recording is unaffected)."""
        self._min_interval = 1.0 / max(fps, 1.0)

    def notify_frame_displayed(self) -> None:
        """Call from the GUI thread after each frame has been rendered."""
        self._display_ready.set()

    def start(self) -> None:
        if self._running:
            return
        self._camera.open()
        self._running = True
        self._last_recv = time.monotonic()
        self._display_ready.set()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="daq-acq")
        self._thread.start()

    def pause(self) -> None:
        """Stop the frame thread without closing the camera device or library.

        Use this for mid-session reconfiguration (e.g. changing trigger mode or fps)
        where Library.Close() + Initialize() would corrupt SDK handles.
        Call resume() afterwards to restart with the new settings.
        """
        _log.info("pause: stopping thread")
        self._running = False
        self._camera.signal_stop()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            alive = self._thread.is_alive()
            self._thread = None
            _log.info("pause: thread joined  still_alive=%s", alive)
        self._drain_settings()  # settings queued while running are written now

    def resume(self) -> None:
        """Restart the frame thread. The camera must already be open."""
        if self._thread is not None:
            _log.warning("resume: thread already running — skipping")
            return  # already running
        _log.info("resume: re-arming camera and starting thread")
        self._camera.open()  # re-arms camera._running (no-op for library init)
        self._running = True
        self._last_recv = time.monotonic()
        self._display_ready.set()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="daq-acq")
        self._thread.start()
        _log.info("resume: thread started")

    def stop(self) -> None:
        """Stop acquisition and close the camera.  Safe to call more than once."""
        _log.info("stop: begin")
        self._running = False
        self._camera.signal_stop()  # unblock frames() without closing library
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                _log.error("stop: acquisition thread did not exit within 5 s")
            self._thread = None
        # A recording still open at shutdown: flush its queue to disk synchronously.
        with self._rec_lock:
            rec, self._recorder = self._recorder, None
            self._rec_remaining = None
        if rec is not None:
            try:
                stats = rec.stop()
                _log.info("stop: recording flushed (%d written, %d dropped)",
                          stats.written, stats.dropped)
            except Exception:  # noqa: BLE001
                _log.exception("stop: could not finalise the recording")
        try:
            self._camera.close()  # safe now - frame thread has exited
        finally:
            _log.info("stop: done")

    def _loop(self) -> None:
        last_emit = 0.0
        frames_received = 0
        frames_emitted = 0
        frames_skipped = 0
        t_start = time.monotonic()
        recv_times: deque[float] = deque()   # all received frames → camera/operation fps
        emit_times: deque[float] = deque()   # emitted frames only → display fps
        last_fps_report = 0.0
        last_rec_report = 0.0
        try:
            for frame in self._camera.frames():
                if not self._running:
                    break
                frames_received += 1
                now = time.monotonic()
                self._last_recv = now
                self._drain_settings()  # generator is suspended here: safe to use the SDK

                # Recording comes first: it must see every camera frame, before
                # display rate-limiting and GUI back-pressure can drop any.
                rec = self._recorder
                if rec is not None:
                    rec.submit(
                        frame,
                        getattr(self._camera, "last_frame_id", None),
                        getattr(self._camera, "last_timestamp_ns", None),
                    )
                    with self._rec_lock:
                        if self._rec_remaining is not None and self._recorder is rec:
                            self._rec_remaining -= 1
                            done = self._rec_remaining <= 0
                        else:
                            done = False
                    if done:
                        self._finish_recording()
                    if now - last_rec_report >= 0.5:
                        self.recording_progress.emit(rec.submitted, rec.written, rec.dropped)
                        last_rec_report = now

                # Track every received frame for camera fps (before any dropping).
                recv_times.append(now)
                while recv_times and now - recv_times[0] > 2.0:
                    recv_times.popleft()

                if now - last_emit < self._min_interval:
                    frames_skipped += 1
                    _log.debug("rate-drop  recv=%d emit=%d", frames_received, frames_emitted)
                    continue
                if not self._display_ready.is_set():
                    frames_skipped += 1
                    _log.debug("busy-drop  recv=%d emit=%d", frames_received, frames_emitted)
                    continue
                gap = (now - last_emit) * 1000 if last_emit else 0.0
                last_emit = now
                frames_emitted += 1
                self._display_ready.clear()  # block until GUI signals back
                _log.debug(
                    "emit #%d  gap=%.0f ms  shape=%s  skipped=%d",
                    frames_emitted, gap, frame.shape, frames_skipped,
                )
                self.frame_ready.emit(frame)
                emit_times.append(now)
                while emit_times and now - emit_times[0] > 2.0:
                    emit_times.popleft()
                if now - last_fps_report >= 0.5:
                    if len(emit_times) >= 2:
                        span = emit_times[-1] - emit_times[0]
                        if span > 0.0:
                            self.fps_updated.emit((len(emit_times) - 1) / span)
                    if len(recv_times) >= 2:
                        span = recv_times[-1] - recv_times[0]
                        if span > 0.0:
                            self.camera_fps_updated.emit((len(recv_times) - 1) / span)
                    last_fps_report = now
        except Exception as exc:
            _log.exception("loop error: %s", exc)
            self.error_occurred.emit(str(exc))
        finally:
            self._finish_recording()  # never leave a recorder open if the loop ends
            elapsed = time.monotonic() - t_start
            _log.info(
                "loop ended: received=%d emitted=%d skipped=%d elapsed=%.1fs",
                frames_received, frames_emitted, frames_skipped, elapsed,
            )
