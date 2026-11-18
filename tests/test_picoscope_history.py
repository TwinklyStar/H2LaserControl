"""Monitor trend history from the daily CSV files (user 2026-11-18: selectable window)."""

import time
from datetime import datetime

import numpy as np

from h2lasercontrol.daq.picoscope import history
from h2lasercontrol.daq.picoscope.history import WINDOWS, TrendSource, load_history


def write_day(folder, name, rows, header=("timestamp", "212", "820"), partial=False):
    """rows: list of (timestamp, *values); file name from the first row's local date."""
    day = datetime.fromtimestamp(rows[0][0]).strftime("%y%m%d")
    path = folder / f"{name}_{day}.csv"
    lines = [",".join(header)] + [",".join(str(x) for x in r) for r in rows]
    text = "\n".join(lines) + "\n"
    if partial:
        text += f"{rows[-1][0] + 4},1.2"  # half-written last line (no newline)
    path.write_text(text)
    return path


def test_windows_are_the_users_list():
    assert [w for w, _ in WINDOWS] == ["10 min", "30 min", "1 hr", "3 hr", "5 hr", "12 hr",
                                       "1 day", "3 days", "7 days", "14 days"]


def test_load_history_selects_the_window_across_days(tmp_path):
    now = time.time()
    # one row per minute for the last 3 days, in daily files like the digitizer writes
    ts = np.arange(now - 3 * 86400, now, 60.0)
    days: dict[str, list] = {}
    for t in ts:
        days.setdefault(datetime.fromtimestamp(t).strftime("%y%m%d"), []).append(
            (t, t % 7, -(t % 5)))
    files = [write_day(tmp_path, "FreeSpacePD_2026June", rows) for rows in days.values()]
    # the last file also gets a half-written line, which must be skipped
    write_day(tmp_path, "FreeSpacePD_2026June", list(days.values())[-1], partial=True)
    src = [TrendSource(str(tmp_path), "FreeSpacePD_2026June", ("212", "820", "gone"))]

    h = load_history(src, 3600, now=now)
    t, v = h["212"]
    assert 59 <= len(t) <= 61 and t[0] >= now - 3600 and np.all(np.diff(t) > 0)
    assert np.allclose(v, t % 7) and np.allclose(h["820"][1], -(t % 5))
    assert len(h["gone"][0]) == 0  # channel not in the files: empty, no error
    assert len(load_history(src, 86400, now=now)["212"][0]) in range(1439, 1442)
    assert len(load_history(src, 14 * 86400, now=now)["212"][0]) == len(ts)
    assert len(files) >= 3


def test_rows_of_the_next_day_in_the_previous_file(tmp_path):
    # the date switch happens only with a new ROOT file: yesterday's file can hold today's rows
    now = time.time()
    rows = [(now - 120, 1, 1), (now - 60, 2, 2)]
    yesterday = datetime.fromtimestamp(now - 86400).strftime("%y%m%d")
    (tmp_path / f"X_{yesterday}.csv").write_text(
        "timestamp,212,820\n" + "".join(f"{t},{a},{b}\n" for t, a, b in rows))
    h = load_history([TrendSource(str(tmp_path), "X", ("212",))], 600, now=now)
    assert list(h["212"][1]) == [1, 2]


def test_past_days_are_cached_until_the_file_changes(tmp_path):
    now = time.time()
    path = write_day(tmp_path, "N", [(now - 30, 1, 2)], header=("timestamp", "NO_cell", "Trig"))
    h1, a1 = history.read_trend_csv(str(path))
    _, a2 = history.read_trend_csv(str(path))
    assert a1 is a2 and h1 == ["timestamp", "NO_cell", "Trig"]
    with open(path, "a") as f:
        f.write(f"{now - 20},3,4\n")
    _, a3 = history.read_trend_csv(str(path))
    assert a3.shape == (2, 3)
