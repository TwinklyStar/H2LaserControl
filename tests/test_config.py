from types import SimpleNamespace

import pytest

from h2lasercontrol.config import DEFAULT_CONFIG, PortNotFound, load_config, resolve_port
from h2lasercontrol.drivers import Ell14, HitMv, Mff, create_driver
from h2lasercontrol.transport import D2xxTransport, FakeTransport


def test_real_config_loads():
    cfg = load_config(DEFAULT_CONFIG)
    assert set(cfg) == {"hitmv", "ell14", "flipmounts"}
    assert cfg["hitmv"].baudrate == 38400 and cfg["hitmv"].rtscts
    assert cfg["ell14"].baudrate == 9600 and not cfg["ell14"].rtscts
    # flip mounts: one D2XX connection per unit, APT settings 115200 + RTS/CTS by default
    assert cfg["flipmounts"].baudrate == 115200 and cfg["flipmounts"].rtscts
    assert cfg["flipmounts"].settings["units"]["flip1"]["usb_serial"] == "37011815"


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
    mff = create_driver(cfg["flipmounts"], transport={"flip1": FakeTransport()})
    assert isinstance(mff, Mff)
    u = mff.units["flip1"]
    assert (u.usb_serial, u.insert_position, u.position_number("retract")) == ("37011815", 2, 1)
    # without a transport: a D2XX connection by serial number (not opened here)
    real = create_driver(cfg["flipmounts"])
    assert isinstance(real.units["flip1"].transport, D2xxTransport)
    assert not real.is_connected
