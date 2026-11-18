"""FrameRecorder — writes camera frames to disk as BMP on a background thread.

The producer (the acquisition thread) calls ``submit()``, which never blocks:
if the writer cannot keep up and the bounded queue is full the frame is counted
as dropped and a gap is left in the frame index, so loss is always visible.
"""
from __future__ import annotations

import dataclasses
import datetime
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from ..config import AppConfig, save_config

_CSV_HEADER = "index,filename,host_time_iso,host_monotonic_s,cam_frame_id,cam_timestamp_ns\n"
_SENTINEL = object()


@dataclass
class RecordStats:
    submitted: int
    written: int
    dropped: int
    elapsed_s: float
    mean_write_ms: float
    max_write_ms: float
    run_dir: Path


_NUM_RE = re.compile(r"^(\d+)_\d{6}")


def _next_number(day: Path) -> int:
    """Next ``NNN`` for the day: one counter shared by burst folders and single captures."""
    n = 0
    if day.is_dir():
        for entry in day.iterdir():
            m = _NUM_RE.match(entry.name)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1


def make_run_dir(output_dir: str | Path, now: datetime.datetime | None = None) -> Path:
    """Burst folder ``<output_dir>/YYYY-MM-DD/NNN_HHMMSS`` (not yet created)."""
    now = now or datetime.datetime.now()
    day = Path(output_dir) / now.strftime("%Y-%m-%d")
    return day / f"{_next_number(day):03d}_{now.strftime('%H%M%S')}"


def make_single_path(output_dir: str | Path, now: datetime.datetime | None = None) -> Path:
    """Single-capture stem ``<output_dir>/YYYY-MM-DD/NNN_HHMMSS`` (no extension).

    The photo is ``<stem>.bmp`` and its settings ``<stem>_config.toml``, side by side with
    the burst folders of that day.
    """
    return make_run_dir(output_dir, now)


class FrameRecorder:
    """Bounded-queue frame writer.  Thread-safe for one producer + the UI reading counters."""

    def __init__(
        self,
        run_dir: str | Path,
        *,
        config: AppConfig | None = None,
        max_queue: int = 40,
        single: bool = False,
    ) -> None:
        """Burst mode (default): *run_dir* is a folder of ``NNNNNN.bmp`` + frames.csv.

        Single mode: *run_dir* is a path stem; writes ``<stem>.bmp`` + ``<stem>_config.toml``
        only (no frames.csv) and keeps just the first frame.
        """
        self.run_dir = Path(run_dir)
        self._single = single
        self._config = config
        self._q: queue.Queue = queue.Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self._csv = None
        self._submitted = 0
        self._written = 0
        self._dropped = 0
        self._write_ms_total = 0.0
        self._write_ms_max = 0.0
        self._t0 = 0.0
        self._t_end = 0.0
        self._stats: RecordStats | None = None
        self._error: Exception | None = None

    # ---- counters (safe to read from any thread) ----

    @property
    def submitted(self) -> int:
        return self._submitted

    @property
    def written(self) -> int:
        return self._written

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def queued(self) -> int:
        return self._q.qsize()

    @property
    def error(self) -> Exception | None:
        return self._error

    # ---- lifecycle ----

    def start(self) -> None:
        folder = self.run_dir.parent if self._single else self.run_dir
        folder.mkdir(parents=True, exist_ok=True)
        if self._config is not None:
            cfg = dataclasses.replace(
                self._config, timestamp=datetime.datetime.now().isoformat(timespec="seconds")
            )
            cfg_path = (
                self.run_dir.parent / f"{self.run_dir.name}_config.toml"
                if self._single else self.run_dir / "run_config.toml"
            )
            save_config(cfg, cfg_path)
        if not self._single:
            self._csv = open(self.run_dir / "frames.csv", "w", buffering=1, encoding="utf-8")
            self._csv.write(_CSV_HEADER)
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True, name="daq-writer")
        self._thread.start()

    def submit(self, frame: NDArray, cam_frame_id: int | None = None,
               cam_timestamp_ns: int | None = None) -> bool:
        """Queue a frame for writing.  Never blocks.  Returns False if it was dropped."""
        self._submitted += 1
        idx = self._submitted
        if self._single and idx > 1:
            self._dropped += 1
            return False
        meta = (idx, time.time(), time.monotonic(), cam_frame_id, cam_timestamp_ns)
        try:
            self._q.put_nowait((frame, meta))
        except queue.Full:
            self._dropped += 1
            return False
        return True

    def stop(self) -> RecordStats:
        """Flush the queue, join the writer, close the CSV.  Idempotent."""
        if self._stats is not None:
            return self._stats
        if self._thread is not None:
            self._q.put(_SENTINEL)  # blocking put is fine: we are not the acquisition thread
            self._thread.join()
        if self._csv is not None:
            self._csv.close()
        self._t_end = time.monotonic()
        n = max(self._written, 1)
        self._stats = RecordStats(
            submitted=self._submitted,
            written=self._written,
            dropped=self._dropped,
            elapsed_s=self._t_end - self._t0,
            mean_write_ms=self._write_ms_total / n,
            max_write_ms=self._write_ms_max,
            run_dir=self.run_dir.with_name(self.run_dir.name + ".bmp") if self._single
            else self.run_dir,
        )
        return self._stats

    # ---- writer thread ----

    def _writer_loop(self) -> None:
        while True:
            item = self._q.get()
            if item is _SENTINEL:
                return
            frame, (idx, host_t, mono, fid, ts) = item
            name = f"{self.run_dir.name}.bmp" if self._single else f"{idx:06d}.bmp"
            target = (self.run_dir.parent if self._single else self.run_dir) / name
            t0 = time.perf_counter()
            try:
                ok = cv2.imwrite(str(target), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                if not ok:
                    raise OSError(f"cv2.imwrite failed for {name}")
            except Exception as exc:  # noqa: BLE001 - keep draining, report via stats/error
                self._error = exc
                self._dropped += 1
                continue
            ms = (time.perf_counter() - t0) * 1000.0
            self._write_ms_total += ms
            self._write_ms_max = max(self._write_ms_max, ms)
            if self._csv is not None:
                iso = datetime.datetime.fromtimestamp(host_t).isoformat(timespec="milliseconds")
                self._csv.write(
                    f"{idx},{name},{iso},{mono:.6f},"
                    f"{'' if fid is None else fid},{'' if ts is None else ts}\n"
                )
            self._written += 1


def read_bmp_rgb(path: str | Path) -> NDArray[np.uint8]:
    """Read a recorded BMP back as (H, W, 3) uint8 RGB."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise OSError(f"Cannot read {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
