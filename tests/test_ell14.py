"""ELL14 driver against the simulator and against exact bytes from the ELLO capture
(docs/captures/2026-11-16_ell14_ello_all_functions.txt)."""

import pytest

from h2lasercontrol.drivers import Aborted, DeviceError, Ell14
from h2lasercontrol.drivers.ell14 import Ell14Error, decode, encode, round_half_away
from h2lasercontrol.oplog import OpLog, read_oplog
from h2lasercontrol.sim import Ell14Sim
from h2lasercontrol.transport import FakeTransport, ScriptedResponder


def make(sim=None, **kw):
    sim = sim or Ell14Sim()
    drv = Ell14("ell14", FakeTransport(sim, chunk_size=3), **kw)
    drv.connect()
    return drv, sim


def test_hex_encoding_matches_capture():
    assert encode(-5) == "FFFFFFFB" and decode("FFFFFFFB") == -5
    assert encode(-40) == "FFFFFFD8"
    assert decode("00003043") == 12355
    with pytest.raises(ValueError):
        encode(2**31)


@pytest.mark.parametrize(
    ("deg", "hex8"),
    [(31.025, "00003043"), (0.1, "00000028"), (-0.1, "FFFFFFD8"), (3.214, "00000500"),
     (5.0, "000007C7")],
)
def test_degree_conversion_matches_ello(deg, hex8):
    drv, _ = make()
    assert encode(drv._pulses(deg)) == hex8


def test_round_half_away_from_zero():
    assert round_half_away(2.5) == 3 and round_half_away(-2.5) == -3
    assert round_half_away(0.49) == 0


def test_identify_parses_our_unit():
    drv, _ = make()
    assert drv.info == {
        "type": 14, "serial": "11401124", "year": 2025, "firmware": "18", "hardware": "01",
        "travel": 360, "pulses_per_travel": 143360,
    }
    assert drv.pulses_per_deg == pytest.approx(398.2222, abs=1e-4)


def test_exact_bytes_like_ello():
    """Same TX bytes as ELLO sent in the capture, replies from the capture."""
    script = ScriptedResponder([
        (b"0in\x07", b"0IN0E1140112420251801016800023000\r\n"),
        (b"0gp\x07", b"0PO00003043\r\n"),
        (b"0go\x07", b"0HO00000500\r\n"),
        (b"0gj\x07", b"0GJ000007C7\r\n"),
        (b"0ho1\x07", b"0PO00000000\r\n"),
        (b"0gj\x07", b"0GJ000007C7\r\n"),  # our driver checks jog step != 0 before jogging
        (b"0fw\x07", b"0PO000007C4\r\n"),
        (b"0ma00003043\x07", b"0PO00003044\r\n"),
        (b"0mr00000028\x07", b"0PO0000306A\r\n"),
        (b"0mrFFFFFFD8\x07", b"0PO00003045\r\n"),
        (b"0so00000500\x07", b"0GS00\r\n"),
        (b"0sj000007C7\x07", b"0GS00\r\n"),
    ])
    drv = Ell14("ell14", FakeTransport(script, chunk_size=1))
    drv.connect()
    assert drv.get_position() == pytest.approx(31.025, abs=0.002)
    assert drv.get_home_offset() == pytest.approx(3.214, abs=0.002)
    assert drv.get_jog_step() == pytest.approx(5.0, abs=0.002)
    assert drv.home("ccw") == 0
    assert drv.jog_forward() == pytest.approx(4.992, abs=0.002)
    assert drv.move_abs(31.025) == pytest.approx(31.027, abs=0.002)
    drv.move_rel(0.1)
    drv.move_rel(-0.1)
    drv.set_home_offset(3.214)
    drv.set_jog_step(5.0)
    assert script.done


def test_no_terminator_option():
    sim = Ell14Sim()
    drv, _ = make(sim, terminator=b"")
    drv.get_position()
    assert sim.received[-1] == "0gp"
    assert drv.transport.written[-1] == b"0gp"


def test_home_cw_is_ho0():
    drv, sim = make()
    drv.home("cw")
    assert sim.received[-1] == "0ho0"
    with pytest.raises(ValueError):
        drv.home("left")


def test_guards():
    drv, sim = make()
    with pytest.raises(ValueError):
        drv.move_abs(360)
    with pytest.raises(ValueError):
        drv.set_home_offset(0.5)  # manual: must be > 0.7 deg
    with pytest.raises(ValueError):
        drv.set_jog_step(0)  # 0 = continuous jog (overheating risk) not allowed
    sim.jog = 0
    with pytest.raises(DeviceError, match="continuous"):
        drv.jog_forward()
    assert "0fw" not in sim.received


def test_error_status_raises():
    drv, sim = make()
    sim.handle = lambda c, d: "GS02" if c == "ma" else Ell14Sim.handle(sim, c, d)
    with pytest.raises(Ell14Error, match="mechanical time out"):
        drv.move_abs(10)


def test_clean_polls_until_done():
    drv, sim = make(Ell14Sim(clean_polls=3), clean_poll=0.001)
    result = drv.clean()
    assert "duration_s" in result
    # cm -> GS09; gs -> GS09 x3 -> GS00
    assert sim.received[-5:] == ["0cm", "0gs", "0gs", "0gs", "0gs"]


def test_clean_stop_request():
    drv, sim = make(Ell14Sim(clean_polls=1000), clean_poll=0.001)
    drv.request_stop()  # set before -> first wait returns immediately
    with pytest.raises(Aborted):
        drv._long_run("cm")
    assert "0st" in sim.received


def test_stop_without_st_reply_falls_back_to_gs():
    drv, sim = make(Ell14Sim(st_replies=False), stop_reply_timeout=0.05)
    r = drv.stop()
    assert r == {"st_replies": [], "gs": 0}
    assert sim.received[-2:] == ["0st", "0gs"]


def test_oplog_records_exchanges(tmp_path):
    oplog = OpLog(tmp_path, user="t")
    drv = Ell14("ell14", FakeTransport(Ell14Sim()), oplog)
    drv.execute("connect")
    drv.execute("move_abs", deg=31.025)
    with pytest.raises(ValueError):
        drv.execute("move_abs", deg=400)
    entries = read_oplog(next(tmp_path.iterdir()))
    assert [(e["action"], e["event"]) for e in entries] == [
        ("connect", "done"),
        ("move_abs", "start"), ("move_abs", "done"),
        ("move_abs", "start"), ("move_abs", "failed"),
    ]
    assert entries[2]["exchanges"] == [["0ma00003043\x07", "0PO00003043\r\n"]]
    assert entries[2]["result"] == pytest.approx(31.025, abs=0.002)
    assert "ValueError" in entries[4]["error"]


def test_unknown_action():
    drv, _ = make()
    with pytest.raises(ValueError):
        drv.execute("_send", cmd="xx")
