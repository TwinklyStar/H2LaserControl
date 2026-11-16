from datetime import datetime, timedelta, timezone

from h2lasercontrol.oplog import OpLog, read_oplog

JST = timezone(timedelta(hours=9))


def fixed_clock(dt):
    return lambda: dt


def test_write_and_read_back(tmp_path):
    t = datetime(2026, 11, 16, 21, 0, 0, tzinfo=JST)
    oplog = OpLog(tmp_path, user="tester", clock=fixed_clock(t))
    oplog.write(
        device="ell14", action="move_abs", args={"deg": 31.025}, result=31.027,
        exchanges=[(b"0ma00003043\x07", b"0PO00003044\r\n")], duration_s=1.2345,
    )
    oplog.write(device="hitmv", action="insert", event="failed", error="DeviceTimeout: x")
    path = tmp_path / "oplog-2026-11-16.jsonl"
    entries = read_oplog(path)
    assert len(entries) == 2
    e = entries[0]
    assert e["time"] == "2026-11-16T21:00:00.000+09:00"
    assert e["user"] == "tester"
    assert e["args"] == {"deg": 31.025}
    assert e["exchanges"] == [["0ma00003043\x07", "0PO00003044\r\n"]]
    assert e["duration_s"] == 1.234 or e["duration_s"] == 1.235
    assert entries[1]["event"] == "failed"


def test_one_file_per_day(tmp_path):
    clock_time = [datetime(2026, 11, 16, 23, 59, tzinfo=JST)]
    oplog = OpLog(tmp_path, user="u", clock=lambda: clock_time[0])
    oplog.write(device="d", action="a")
    clock_time[0] = datetime(2026, 11, 17, 0, 1, tzinfo=JST)
    oplog.write(device="d", action="b")
    assert len(read_oplog(tmp_path / "oplog-2026-11-16.jsonl")) == 1
    assert len(read_oplog(tmp_path / "oplog-2026-11-17.jsonl")) == 1


def test_survives_crash_mid_line(tmp_path):
    t = datetime(2026, 11, 16, 12, 0, tzinfo=JST)
    oplog = OpLog(tmp_path, user="u", clock=fixed_clock(t))
    oplog.write(device="d", action="before")
    path = oplog.path_for(t)
    with open(path, "ab") as f:  # simulate a crash halfway through writing a line
        f.write(b'{"time": "2026-11-16T12:00:00", "dev')
    oplog.write(device="d", action="after")  # a new process keeps logging
    actions = [e["action"] for e in read_oplog(path)]
    assert actions == ["before", "after"]
