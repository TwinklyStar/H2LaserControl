from types import SimpleNamespace

import pytest

from h2lasercontrol.config import DEFAULT_CONFIG, PortNotFound, load_config, resolve_port
from h2lasercontrol.drivers import Ell14, HitMv, Mff, create_driver
from h2lasercontrol.transport import D2xxTransport, FakeTransport


def test_real_config_loads():
    cfg = load_config(DEFAULT_CONFIG)
    assert set(cfg) == {"hitmv", "ell14", "flipmounts", "dg645", "scope_monitor", "vuv_pd",
                        "camera"}
    # DG645 (2026-11-20): PL2303 adapter, 9600 + RTS/CTS; only channel C, D linked
    dg = cfg["dg645"]
    assert (dg.usb_serial, dg.baudrate, dg.rtscts) == ("CGBHB2A4517", 9600, True)
    assert (dg.settings["channel"], dg.settings["width_channel"]) == ("C", "D")
    assert dg.settings["nominal_s"] == 0.036580467
    assert (dg.settings["min_offset_us"], dg.settings["max_offset_us"]) == (-1.5, 3.0)
    assert {k: c.type for k, c in cfg.items() if k in ("scope_monitor", "vuv_pd", "camera")} == {
        "scope_monitor": "picoscope", "vuv_pd": "picoscope", "camera": "ids_camera"}
    assert cfg["hitmv"].baudrate == 38400 and cfg["hitmv"].rtscts
    assert cfg["ell14"].baudrate == 9600 and not cfg["ell14"].rtscts
    # flip mounts: one D2XX connection per unit, APT settings 115200 + RTS/CTS by default
    assert cfg["flipmounts"].baudrate == 115200 and cfg["flipmounts"].rtscts
    units = cfg["flipmounts"].settings["units"]
    assert units["flip1"]["usb_serial"] == "37011815" and units["flip1"]["insert_position"] == 2
    assert units["flip2"]["usb_serial"] == "37006391" and units["flip2"]["insert_position"] == 2


def test_resolve_port_by_serial_number():
    cfg = load_config(DEFAULT_CONFIG)
    ports = [SimpleNamespace(device="COM7", serial_number="DU0DFFMCA"),
             SimpleNamespace(device="COM9", serial_number="DP06TVEFA")]
    assert resolve_port(cfg["hitmv"], ports) == "COM7"  # COM number changed: still found
    assert resolve_port(cfg["ell14"], ports) == "COM9"


def test_missing_serial_does_not_fall_back_to_com_number():
    cfg = load_config(DEFAULT_CONFIG)
    with pytest.raises(PortNotFound, match="DU0DFFMCA"):
        resolve_port(cfg["hitmv"], [SimpleNamespace(device="COM4", serial_number="OTHER")])


def test_create_drivers_from_real_config():
    cfg = load_config(DEFAULT_CONFIG)
    hit = create_driver(cfg["hitmv"], transport=FakeTransport())
    assert isinstance(hit, HitMv)
    assert {n: (a.name, a.inserted, a.retracted) for n, a in hit.axes.items()} == {
        0: ("vuv_photodiode", 0, 30000000),
        1: ("vuv_mirror", 0, 30000000),
    }
    assert hit.homing_max_speed == 1000000
    assert hit.speed == (100000, 1000000, 200)
    ell = create_driver(cfg["ell14"], transport=FakeTransport())
    assert isinstance(ell, Ell14)
    assert ell.terminator == b"\x07" and ell.address == "0"
    mff = create_driver(cfg["flipmounts"],
                        transport={"flip1": FakeTransport(), "flip2": FakeTransport()})
    assert isinstance(mff, Mff)
    u = mff.units["flip1"]
    assert (u.usb_serial, u.insert_position, u.position_number("retract")) == ("37011815", 2, 1)
    u2 = mff.units["flip2"]
    assert (u2.label, u2.usb_serial, u2.position_number("retract")) == ("820 nm blocker",
                                                                         "37006391", 1)
    # without a transport: a D2XX connection by serial number (not opened here)
    real = create_driver(cfg["flipmounts"])
    assert isinstance(real.units["flip1"].transport, D2xxTransport)
    assert not real.is_connected
