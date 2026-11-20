"""DG645 driver against the simulator (values of our unit, read-only probe 2026-11-20)."""

import pytest

from h2lasercontrol.drivers import DeviceError, Dg645
from h2lasercontrol.drivers.dg645 import OUTSIDE, absolute_times, ms_text, parse_delay, us_text
from h2lasercontrol.energy import AngleStore
from h2lasercontrol.oplog import OpLog, read_oplog
from h2lasercontrol.sim import Dg645Sim
from h2lasercontrol.transport import FakeTransport

NOMINAL = 0.036580467


def make(tmp_path, sim=None, oplog=None):
    sim = sim or Dg645Sim()
    t = FakeTransport(sim, chunk_size=7)
    drv = Dg645("dg645", t, oplog, channel="C", width_channel="D", nominal_s=NOMINAL,
                min_offset_s=-1.5e-6, max_offset_s=3e-6,
                store=AngleStore(tmp_path / "dg645_state.json"))
    return drv, sim, t


def sets(t):
    """The set commands sent (everything that is not a query)."""
    return [w.decode().strip() for w in t.written if b"?" not in w]


def test_parse_and_format():
    assert parse_delay("4,+0.000000500000") == ("C", 5e-7)
    assert parse_delay("0,+0.037026600000")[0] == "T0"
    assert ms_text(0.036580467) == "36.580 467 ms"
    assert ms_text(0.0370266) == "37.026 600 ms"
    assert ms_text(0.0365804675) == "36.580 467 500 ms"  # down to 1 ps
    assert us_text(1e-7) == "+0.100 µs" and us_text(-1.5e-6) == "-1.500 µs"
    a = absolute_times({"A": ("T0", 0.0370266), "B": ("A", -1e-7)})
    assert a["B"] == pytest.approx(0.0370265)


def test_connect_reads_every_channel(tmp_path):
    drv, _sim, t = make(tmp_path)
    info = drv.execute("connect")
    assert info["serial"] == "s/n004497" and info["firmware"] == "ver1.17.116"
    assert set(info["channels"]) == set("ABCDEFGH")
    st = drv.snapshot()
    assert st["offset_s"] == pytest.approx(0, abs=1e-12)
    assert st["width_s"] == pytest.approx(5e-7)
    assert st["channels"]["D"]["abs_s"] == pytest.approx(NOMINAL + 5e-7)
    assert st["problems"] == [] and not st["changed_outside"]
    assert sets(t) == []  # reading only


def test_set_offset_writes_only_channel_c(tmp_path):
    oplog = OpLog(tmp_path / "logs", user="tester")
    drv, sim, t = make(tmp_path, oplog=oplog)
    drv.execute("connect")
    before = dict(sim.delays)
    r = drv.execute("set_offset", offset_us=0.5)
    assert sets(t) == ["DLAY 4,0,0.036580967000"]  # the one and only set command
    assert r["old_us"] == 0 and r["new_us"] == pytest.approx(0.5)
    assert sim.delays[4] == (0, pytest.approx(NOMINAL + 5e-7))
    assert {k: v for k, v in sim.delays.items() if k != 4} == {k: v for k, v in before.items()
                                                               if k != 4}
    st = drv.snapshot()
    assert st["channels"]["D"]["abs_s"] == pytest.approx(NOMINAL + 1e-6)  # D moved along
    assert not st["changed_outside"]
    assert st["last_change"]["by"] == "tester" and not st["last_change"]["outside"]
    done = [e for e in read_oplog(oplog.today_path()) if e["action"] == "set_offset"]
    assert done[-1]["event"] == "done" and done[-1]["user"] == "tester"
    assert not [e for e in read_oplog(oplog.today_path()) if e["action"] == "changed_outside"]


def test_step(tmp_path):
    drv, _sim, _t = make(tmp_path)
    drv.execute("connect")
    drv.execute("step", delta_us=0.1)
    r = drv.execute("step", delta_us=0.1)
    assert r["new_us"] == pytest.approx(0.2)
    drv.execute("step", delta_us=-0.1)
    assert drv.snapshot()["offset_s"] == pytest.approx(1e-7, abs=1e-12)


@pytest.mark.parametrize("offset", [-1.6, 3.1, float("nan")])
def test_outside_hard_limits_is_refused_without_sending(tmp_path, offset):
    drv, _sim, t = make(tmp_path)
    drv.execute("connect")
    with pytest.raises(DeviceError, match="allowed range"):
        drv.execute("set_offset", offset_us=offset)
    assert sets(t) == []


def test_limits_themselves_are_allowed(tmp_path):
    drv, _sim, _t = make(tmp_path)
    drv.execute("connect")
    assert drv.execute("set_offset", offset_us=-1.5)["new_us"] == pytest.approx(-1.5)
    assert drv.execute("set_offset", offset_us=3.0)["new_us"] == pytest.approx(3.0)
    with pytest.raises(DeviceError):
        drv.execute("step", delta_us=0.1)  # would go past +3 µs


def test_refuses_when_width_channel_unlinked(tmp_path):
    drv, sim, t = make(tmp_path)
    drv.execute("connect")
    sim.delays[5] = (0, NOMINAL + 5e-7)  # someone set D relative to T0 by hand
    assert drv.snapshot()["problems"]
    with pytest.raises(DeviceError, match="pulse width"):
        drv.execute("set_offset", offset_us=0.1)
    assert sets(t) == []


def test_refuses_when_c_not_relative_to_t0(tmp_path):
    drv, sim, t = make(tmp_path)
    drv.execute("connect")
    sim.delays[4] = (2, -0.000446133)  # C = A - x
    with pytest.raises(DeviceError, match="not T0"):
        drv.execute("set_offset", offset_us=0.1)
    assert sets(t) == []


def test_never_sends_anything_else(tmp_path):
    drv, _sim, t = make(tmp_path)
    drv.execute("connect")
    for cmd in ("DLAY 6,0,0.037", "DLAY 5,4,0.000001", "*RST", "REMT", "*SAV 1",
                "DLAY 4,0,0.0365,1", "LINK 5,0"):
        with pytest.raises(DeviceError, match="refused"):
            drv._write(cmd)
    assert sets(t) == []


def test_device_error_is_reported(tmp_path):
    drv, sim, _t = make(tmp_path)
    drv.execute("connect")
    real = sim.handle

    def refuse(cmd):
        if cmd.startswith("DLAY 4,0,"):
            sim.errors.append(12)
            return None
        return real(cmd)

    sim.handle = refuse
    with pytest.raises(DeviceError, match="error 12"):
        drv.execute("set_offset", offset_us=0.1)


def test_front_panel_change_is_logged(tmp_path):
    oplog = OpLog(tmp_path / "logs", user="tester")
    drv, sim, _t = make(tmp_path, oplog=oplog)
    drv.execute("connect")
    sim.delays[6] = (0, 0.0369992)  # another group turns E by 100 ns
    drv.snapshot()
    drv.snapshot()  # noticed once, not again
    entries = [e for e in read_oplog(oplog.today_path()) if e["action"] == "changed_outside"]
    assert len(entries) == 1
    assert entries[0]["user"] == OUTSIDE and entries[0]["result"]["channel"] == "E"
    assert "36.999 100 ms → T0 + 36.999 200 ms" in entries[0]["result"]["text"]


def test_change_of_c_outside_the_program_is_flagged(tmp_path):
    drv, sim, t = make(tmp_path)
    drv.execute("connect")
    drv.execute("set_offset", offset_us=0.3)
    sim.delays[4] = (0, NOMINAL)  # power cycle: back to the front-panel value
    st = drv.snapshot()
    assert st["changed_outside"] and st["last_change"]["outside"]
    assert sets(t) == ["DLAY 4,0,0.036580767000"]  # nothing re-applied by itself


def test_nominal_value_can_be_changed_without_touching_the_dg645(tmp_path):
    """Maintenance (user 2026-11-20): the nominal value moves, the limits move with it."""
    drv, sim, t = make(tmp_path)
    drv.execute("connect")
    drv.execute("set_offset", offset_us=2.0)
    r = drv.execute("use_current_as_nominal")
    assert r["new_s"] == pytest.approx(NOMINAL + 2e-6) and "→" in r["text"]
    assert sets(t) == ["DLAY 4,0,0.036582467000"]  # only the set_offset above
    st = drv.snapshot()
    assert st["offset_s"] == pytest.approx(0, abs=1e-12) and st["problems"] == []
    assert st["nominal"]["nominal_s"] == pytest.approx(NOMINAL + 2e-6)
    drv.execute("set_offset", offset_us=3.0)  # = old nominal + 5 µs: allowed now
    with pytest.raises(DeviceError, match="allowed range"):
        drv.execute("set_offset", offset_us=-1.6)
    # a typed value; kept after a restart (overrides devices.toml)
    drv.execute("set_nominal", nominal_ms=36.5805)
    drv2, _, _ = make(tmp_path, sim=sim)
    assert drv2.nominal_s == pytest.approx(0.0365805)
    assert drv2.config_nominal_s == NOMINAL
    with pytest.raises(ValueError):
        drv.execute("set_nominal", nominal_ms=-1)


def test_change_while_program_closed_is_logged_at_connect(tmp_path):
    oplog = OpLog(tmp_path / "logs", user="tester")
    drv, sim, _t = make(tmp_path, oplog=oplog)
    drv.execute("connect")
    drv.execute("disconnect")
    sim.delays[8] = (0, 0.0370310)  # G changed while we were not looking
    drv2, _, _ = make(tmp_path, sim=sim, oplog=oplog)
    info = drv2.execute("connect")
    assert info["changed_while_closed"] == ["G"]
