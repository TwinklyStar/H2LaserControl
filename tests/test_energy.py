import pytest

from h2lasercontrol.drivers import DeviceError, Ell14
from h2lasercontrol.energy import AngleStore, angle_for_fraction, fraction_at
from h2lasercontrol.oplog import OpLog, read_oplog
from h2lasercontrol.sim import Ell14Sim
from h2lasercontrol.transport import FakeTransport


def test_fraction_formula():
    assert fraction_at(31.0, 31.0) == pytest.approx(1)
    assert fraction_at(31.0 + 45, 31.0) == pytest.approx(0, abs=1e-12)
    assert fraction_at(31.0 + 22.5, 31.0) == pytest.approx(0.5)
    assert fraction_at(31.0 + 90, 31.0) == pytest.approx(1)  # period 90 deg


@pytest.mark.parametrize("f", [1.0, 0.75, 0.5, 0.1, 0.0])
def test_angle_for_fraction_roundtrip(f):
    a = angle_for_fraction(f, 31.0)
    assert 31.0 <= a <= 76.0
    assert fraction_at(a, 31.0) == pytest.approx(f, abs=1e-6)


def test_angle_wraps_into_0_360():
    assert angle_for_fraction(0.0, 340.0) == pytest.approx(25.0)
    with pytest.raises(ValueError):
        angle_for_fraction(1.2, 0)


def test_store_roundtrip(tmp_path):
    store = AngleStore(tmp_path / "saved_angles.json")
    assert store.get("ell14") == {}
    store.update("ell14", max_energy_deg=31.03, saved_by="Meng")
    again = AngleStore(tmp_path / "saved_angles.json").get("ell14")
    assert again["max_energy_deg"] == 31.03 and again["saved_by"] == "Meng" and again["saved_at"]


def make(tmp_path, position=0x3043):  # 31.025 deg
    oplog = OpLog(tmp_path / "logs", user="Meng")
    sim = Ell14Sim(position=position)
    drv = Ell14("ell14", FakeTransport(sim), oplog,
                angle_store=AngleStore(tmp_path / "saved_angles.json"))
    drv.execute("connect")
    return drv, sim, oplog


def test_energy_actions_need_saved_max(tmp_path):
    drv, _, _ = make(tmp_path)
    assert drv.snapshot()["max_energy"] is None
    with pytest.raises(DeviceError, match="no max-energy angle"):
        drv.execute("go_to_max_energy")


def test_save_go_and_set_energy(tmp_path):
    drv, sim, oplog = make(tmp_path)
    r = drv.execute("save_max_energy")
    assert r == {"old": None, "new": pytest.approx(31.025, abs=0.002)}
    snap = drv.snapshot()
    assert snap["energy_fraction"] == pytest.approx(1)
    assert snap["max_energy"]["saved_by"] == "Meng"

    drv.execute("go_to_min_energy")
    assert drv.get_position() == pytest.approx(76.025, abs=0.003)
    r = drv.execute("set_energy", percent=50)
    assert r["angle"] == pytest.approx(31.025 + 22.5, abs=0.003)
    assert r["estimated_percent"] == pytest.approx(50, abs=0.2)
    drv.execute("go_to_max_energy")
    assert drv.get_position() == pytest.approx(31.025, abs=0.003)

    sim.pos = 0x3043 + 400  # re-tune: ~1 deg further
    r = drv.execute("save_max_energy")
    assert r["old"] == pytest.approx(31.025, abs=0.002) and r["new"] == pytest.approx(32.03, abs=0.01)
    logged = [(e["action"], e["result"]) for e in read_oplog(oplog.today_path())
              if e["action"] == "save_max_energy"]
    assert len(logged) == 2 and logged[1][1]["old"] == pytest.approx(31.025, abs=0.002)
    with pytest.raises(ValueError):
        drv.execute("set_energy", percent=120)
