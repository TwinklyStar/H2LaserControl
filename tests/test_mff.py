"""MFF101 flip mount driver, against the simulator and the bytes seen on our unit (2026-11-17)."""

import pytest

from h2lasercontrol.drivers import DeviceError, DeviceTimeout
from h2lasercontrol.drivers.mff import FlipUnit, Mff, decode_position, header, parse_info
from h2lasercontrol.oplog import OpLog, read_oplog
from h2lasercontrol.sim import MffSim
from h2lasercontrol.transport import FakeTransport, TransportError

# real reply of unit 37011815 to HW_REQ_INFO (tools/probe_mff_readonly.py, 2026-11-17)
REAL_INFO = bytes.fromhex(
    "67 c1 34 02 4d 46 46 30 30 32 00 00 10 00 03 00 01 00 41 50 54 20 46 69 6c 74 65 72 20 46 "
    "6c 69 70 70 65 72 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
    "00 00 00 00 00 00 31 34 31 32 30 31 44 65 63 00 08 00 02 00 00 00 01 00"
)


def make(*sims, oplog=None, **kw):
    units = []
    for i, sim in enumerate(sims, 1):
        t = FakeTransport(sim, chunk_size=5, name=f"flip{i}")
        units.append(FlipUnit(f"flip{i}", f"Flip mount {i}", str(sim.serial), t))
    kw.setdefault("poll_interval", 0.001)
    return Mff("flipmounts", units, oplog, **kw)


def test_parse_real_info():
    info = parse_info(REAL_INFO)
    assert info["serial"] == "37011815" and info["model"] == "MFF002"
    assert info["firmware"] == "1.0.3" and info["notes"] == "APT Filter Flipper"
    assert (info["hw_version"], info["channels"]) == (2, 1)


def test_header_bytes_match_manual_and_capture():
    assert header(0x0005) == bytes.fromhex("050000005001")  # HW_REQ_INFO
    assert header(0x0429, 1) == bytes.fromhex("290401005001")  # REQ_STATUSBITS
    assert header(0x046A, 1, 1) == bytes.fromhex("6a0401015001")  # jog dir 1 (captured)
    assert header(0x046A, 1, 2) == bytes.fromhex("6a0401025001")  # jog dir 2 (captured)


def test_decode_position_from_captured_bits():
    assert decode_position(0x90000002) == (2, False)
    assert decode_position(0x90000001) == (1, False)
    assert decode_position(0x90000012) == (None, True)  # start of a flip: limit + moving
    assert decode_position(0x90000010) == (None, True)
    assert decode_position(0x90000000) == (None, False)  # between, not moving


def test_connect_identify_and_state():
    drv = make(MffSim())
    info = drv.execute("connect")
    assert info["flip1"]["model"] == "MFF002"
    st = drv.snapshot()["units"]["flip1"]
    assert st["connected"] and st["position"] == "insert" and not st["moving"]


def test_retract_and_insert_send_the_right_jog(tmp_path):
    sim = MffSim(position=2)
    oplog = OpLog(tmp_path, user="tester")
    drv = make(sim, oplog=oplog)
    drv.execute("connect")
    res = drv.execute("retract", unit="flip1")
    assert res["position"] == "retract" and sim.pos == 1
    assert bytes.fromhex("6a0401015001") in sim.received  # position 1 = retract
    drv.execute("insert", unit="flip1")
    assert sim.pos == 2 and sim.received.count(bytes.fromhex("6a0401025001")) == 1
    entries = read_oplog(oplog.today_path())
    assert [(e["action"], e["event"]) for e in entries if e["action"] in ("insert", "retract")] == [
        ("retract", "start"), ("retract", "done"), ("insert", "start"), ("insert", "done")]


def test_already_there_sends_no_jog():
    sim = MffSim(position=2)
    drv = make(sim)
    drv.execute("connect")
    assert drv.execute("insert", unit="flip1")["note"] == "already there"
    assert not any(tx[:2] == b"\x6a\x04" for tx in sim.received)


def test_flip_timeout_when_it_never_arrives():
    drv = make(MffSim(flip_polls=10**6), move_timeout=0.05)
    drv.execute("connect")
    with pytest.raises(DeviceTimeout, match="did not reach 'retract'"):
        drv.execute("retract", unit="flip1")


def test_wrong_device_refused():
    drv = make(MffSim(model=b"KDC101"))
    with pytest.raises(DeviceError, match="not a flip mount"):
        drv.execute("connect")
    assert not drv.is_connected


def test_wrong_serial_refused():
    sim = MffSim(serial=37000001)
    t = FakeTransport(sim)
    drv = Mff("f", [FlipUnit("flip1", "Flip mount 1", "37011815", t)])
    with pytest.raises(DeviceError, match="37011815 configured"):
        drv.execute("connect")


class Unplugged(FakeTransport):
    def _open(self):
        raise TransportError("USB device 37000002 not found. Is it plugged in?")


def test_missing_unit_does_not_block_the_other():
    sim = MffSim()
    units = [FlipUnit("flip1", "Flip mount 1", "37011815", FakeTransport(sim)),
             FlipUnit("flip2", "Flip mount 2", "37000002", Unplugged())]
    drv = Mff("f", units, poll_interval=0.001, retry_interval=3600)
    result = drv.execute("connect")
    assert "not found" in result["flip2"]["error"]
    st = drv.snapshot()["units"]
    assert st["flip1"]["connected"] and not st["flip2"]["connected"]
    assert "not found" in st["flip2"]["error"]
    drv.execute("retract", unit="flip1")  # the connected one still works
    with pytest.raises(DeviceError, match="Flip mount 2 is not connected"):
        drv.execute("retract", unit="flip2")
    assert drv.connection_text().startswith("1 of 2 units")


def test_offline_unit_is_retried():
    sim2 = MffSim(serial=37000002)
    plug = {"in": False}

    class Later(FakeTransport):
        def _open(self):
            if not plug["in"]:
                raise TransportError("not found")

    units = [FlipUnit("flip1", "Flip mount 1", "37011815", FakeTransport(MffSim())),
             FlipUnit("flip2", "Flip mount 2", "37000002", Later(sim2))]
    drv = Mff("f", units, retry_interval=0)
    drv.execute("connect")
    assert not drv.snapshot()["units"]["flip2"]["connected"]
    plug["in"] = True  # plugged in later: picked up by the next poll
    assert drv.snapshot()["units"]["flip2"]["connected"]


def test_all_units_missing_fails_connect():
    drv = Mff("f", [FlipUnit("flip1", "Flip mount 1", "37011815", Unplugged())])
    with pytest.raises(DeviceError, match="not found"):
        drv.execute("connect")


def test_transit_time_and_led():
    sim = MffSim()
    drv = make(sim)
    drv.execute("connect")
    assert drv.execute("get_transit_time", unit="flip1") == 500
    drv.execute("flash_led", unit="flip1")
    assert sim.received[-1] == bytes.fromhex("230200005001")
