import serial

import h2lasercontrol


def test_imports():
    assert h2lasercontrol.__version__
    assert serial.VERSION
