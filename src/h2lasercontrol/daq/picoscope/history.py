"""Read the continuous-mode trend history from the daily CSV files (for the monitor plots).

The digitizer writes `<data_path>/csv/<output_name>_<YYMMDD>.csv` with columns `timestamp`
(Unix time, s) + one column per channel name (summed area, nV*s), one row per 100 triggers.
A file holds the rows written while that day's file was open; the date switch happens only when
a new ROOT file starts, so a file can contain a few minutes of the next day. Rows are therefore
selected by timestamp, and one extra day before the window is read.

Files of past days do not change any more: they are parsed once and cached (by size and
modification time), so changing the window repeatedly stays fast.
"""

from __future__ import annotations

import csv
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np

_log = logging.getLogger(__name__)

# window choices for the monitor (label, seconds); user 2026-11-18
WINDOWS: list[tuple[str, int]] = [
    ("10 min", 600), ("30 min", 1800), ("1 hr", 3600), ("3 hr", 3 * 3600),
    ("5 hr", 5 * 3600), ("12 hr", 12 * 3600), ("1 day", 86400), ("3 days", 3 * 86400),
    ("7 days", 7 * 86400), ("14 days", 14 * 86400),
]
DEFAULT_WINDOW = "5 hr"  # the old monitor kept 4000 points = ~4.4 h


@dataclass(frozen=True)
class TrendSource:
    """One digitizer's CSV files: folder, file prefix, and the channel columns wanted."""
    csv_dir: str
    output_name: str
    channels: tuple[str, ...]


_cache: dict[str, tuple[float, int, list[str], np.ndarray]] = {}  # path -> (mtime, size, ...)


def read_trend_csv(path: str) -> tuple[list[str], np.ndarray]:
    """(header, rows as float array [n, ncol]). Bad / half-written lines are skipped."""
    st = os.stat(path)
    hit = _cache.get(path)
    if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2], hit[3]
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        n = len(header)
        for r in reader:
            if len(r) != n:
                continue
            try:
                rows.append([float(x) for x in r])
            except ValueError:
                continue
    arr = np.array(rows, dtype=float).reshape(-1, max(n, 1))
    _cache[path] = (st.st_mtime, st.st_size, header, arr)
    return header, arr


def _days(t0: float, t1: float) -> list[date]:
    d, last = datetime.fromtimestamp(t0).date() - timedelta(days=1), datetime.fromtimestamp(t1).date()
    out = []
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


def load_history(sources: list[TrendSource], window_s: float,
                 now: float | None = None) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{channel: (timestamps, values)} for the last `window_s` seconds, sorted by time.
    Channels missing from the files (e.g. renamed in the config) come back empty."""
    now = time.time() if now is None else now
    t0 = now - window_s
    out: dict[str, tuple[list[np.ndarray], list[np.ndarray]]] = {
        ch: ([], []) for s in sources for ch in s.channels}
    for src in sources:
        for d in _days(t0, now):
            path = os.path.join(src.csv_dir, f"{src.output_name}_{d.strftime('%y%m%d')}.csv")
            if not os.path.exists(path):
                continue
            try:
                header, arr = read_trend_csv(path)
            except OSError as e:
                _log.warning("cannot read %s: %s", path, e)
                continue
            if not len(arr) or "timestamp" not in header:
                continue
            ts = arr[:, header.index("timestamp")]
            sel = (ts >= t0) & (ts <= now + 60)
            for ch in src.channels:
                if ch in header:
                    out[ch][0].append(ts[sel])
                    out[ch][1].append(arr[sel, header.index(ch)])
    result = {}
    for ch, (tl, vl) in out.items():
        t = np.concatenate(tl) if tl else np.empty(0)
        v = np.concatenate(vl) if vl else np.empty(0)
        order = np.argsort(t, kind="stable")
        result[ch] = (t[order], v[order])
    return result
