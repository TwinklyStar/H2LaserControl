"""HIT-MV driver against the simulator; command strings compared with the SGSample captures."""

import threading

import pytest

from h2lasercontrol.drivers import Aborted, Axis, DeviceError, DeviceTimeout, HitMv
from h2lasercontrol.drivers.hitmv import parse_alarms, parse_slots, slots
from h2lasercontrol.oplog import OpLog, read_oplog
from h2lasercontrol.sim import HitMvSim
from h2lasercontrol.transport import FakeTransport

AXES = {0: Axis(0, "vuv_photodiode"), 1: Axis(1, "vuv_mirror")}


def make(sim=None, oplog=None, **kw):
    sim = sim or HitMvSim()
    kw.setdefault("poll_interval", 0.001)
    drv = HitMv("hitmv", FakeTransport(sim, chunk_size=5), oplog, axes=AXES, **kw)
    drv.connect()
    return drv, sim


def motion_commands(sim):
    return [c for c in sim.received if c[0] in "HMADBL"]


def test_slot_format_matches_capture():
    assert "H:" + slots(1, "1") == "H:,1,,,,,,"
    assert "H:" + slots(0, "1") == "H:1,,,,,,,"
    assert "M:" + slots(1, "+30000000") == "M:,+30000000,,,,,,"
    assert parse_slots("30000000,0,,,,,,") == ["30000000", "0", None, None, None, None, None, None]
    assert parse_slots("HIT") == ["HIT"] + [None] * 7


def test_parse_alarms():
    assert parse_alarms("00,00,00,,,,,,") == {}
    assert parse_alarms("00,00,41,,,,,,") == {1: ["-limit switch", "driver alarm"]}
    assert parse_alarms("00,00,04,,,,,,") == {}  # ORG sensor only: not an alarm


def test_identify_and_status():
    drv, _ = make()
    assert drv.identify() == {"name": "HIT-MV", "version": "V1.20-001", "mode": "HIT"}
    st = drv.status()
    assert st["vuv_mirror"] == {"axis": 1, "connected": True, "position": 30000000,
                                "named": "RETRACTED", "busy": False, "alarms": []}


def test_refuses_shot_mode():
    sim = HitMvSim()
    orig = sim.handle
    sim.handle = lambda c: "0" if c == "?:Z" else orig(c)
    with pytest.raises(DeviceError, match="HIT mode"):
        make(sim)


def test_insert_mirror_sends_fast_homing_then_h():
    drv, sim = make()
    r = drv.insert(1)
    assert r == {"position": 0, "homing_speed_cmd": "B:1,50000,1000000,200,250000"}
    # S, R, M kept from ?:B1; only F raised; then exactly SGSample's H: command
    assert motion_commands(sim) == ["B:1,50000,1000000,200,250000", "H:,1,,,,,,"]
    assert sim.pos[:2] == [30000000, 0]


def test_insert_without_fast_homing():
    drv, sim = make(homing_max_speed=None)
    drv.insert(0)
    assert motion_commands(sim) == ["H:1,,,,,,,"]


def test_retract_like_sgsample():
    drv, sim = make(HitMvSim(positions=(30000000, 0)))
    assert drv.retract(1) == {"position": 30000000}
    assert motion_commands(sim) == ["D:1,100000,1000000,200", "M:,+30000000,,,,,,"]


def test_retract_refused_unless_inserted():
    drv, sim = make(HitMvSim(positions=(30000000, 12345)))
    with pytest.raises(DeviceError, match="not at the inserted position"):
        drv.retract(1)
    assert motion_commands(sim) == []


def test_busy_axis_refused_before_sending():
    sim = HitMvSim(busy_polls=10**6)
    drv, _ = make(sim)
    sim.remaining[1] = 5
    with pytest.raises(DeviceError, match="busy"):
        drv.insert(1)
    assert motion_commands(sim) == []


def test_unconfigured_axis():
    drv, _ = make()
    with pytest.raises(ValueError):
        drv.insert(2)


def test_timeout_stops_axis():
    drv, sim = make(HitMvSim(busy_polls=10**6), insert_timeout=0.05)
    with pytest.raises(DeviceTimeout):
        drv.insert(1)
    assert motion_commands(sim)[-1] == "L:,1,,,,,,"


def test_stop_request_from_other_thread():
    drv, sim = make(HitMvSim(busy_polls=10**6), poll_interval=0.01)
    threading.Timer(0.05, drv.request_stop).start()
    with pytest.raises(Aborted):
        drv.insert(0)
    assert motion_commands(sim)[-1] == "L:1,,,,,,,"


def test_move_abs_range_checked():
    drv, sim = make()
    with pytest.raises(ValueError):
        drv.move_abs(1, 30000001)
    assert drv.move_abs(1, 15000000) == {"position": 15000000}
    assert motion_commands(sim)[-1] == "A:,+15000000,,,,,,"


def test_named_positions():
    drv, sim = make()
    drv.move_to(1, "INSERTED")
    drv.move_to(1, "RETRACTED")
    assert sim.pos[1] == 30000000
    with pytest.raises(ValueError):
        drv.move_to(1, "HALF")


def test_oplog_hides_polling(tmp_path):
    oplog = OpLog(tmp_path, user="t")
    drv, _ = make(oplog=oplog)
    drv.execute("insert", axis=1)
    entries = read_oplog(next(tmp_path.iterdir()))
    done = entries[-1]
    assert (done["action"], done["event"], done["args"]) == ("insert", "done", {"axis": 1})
    sent = [tx.strip() for tx, _ in done["exchanges"]]
    assert "B:1,50000,1000000,200,250000" in sent and "H:,1,,,,,," in sent
    assert sent.count("!:") <= 1  # polling during the wait is not logged
