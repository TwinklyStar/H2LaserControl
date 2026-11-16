import pytest

from h2lasercontrol.transport import (
    FakeTransport,
    ScriptedResponder,
    SerialTransport,
    TransportError,
    TransportTimeout,
)


def test_read_until_split_reply():
    # ELL14 replies sometimes arrive split across reads ("0" then "PO...\r\n")
    t = FakeTransport(lambda tx: b"0POFFFFFFFB\r\n", chunk_size=1)
    with t:
        t.write(b"0bw\x07")
        assert t.read_until(b"\r\n", timeout=1) == b"0POFFFFFFFB\r\n"
    assert t.written == [b"0bw\x07"]


def test_read_until_keeps_bytes_after_terminator():
    t = FakeTransport()
    t.open()
    t.feed(b"OK\r\nNG\r\n")
    assert t.read_until(b"\r\n", 1) == b"OK\r\n"
    assert t.read_until(b"\r\n", 1) == b"NG\r\n"


def test_timeout_carries_partial():
    t = FakeTransport()
    t.open()
    t.feed(b"0PO000")
    with pytest.raises(TransportTimeout) as ei:
        t.read_until(b"\r\n", timeout=0.05)
    assert ei.value.partial == b"0PO000"
    # buffer is empty afterwards
    t.feed(b"OK\r\n")
    assert t.read_until(b"\r\n", 1) == b"OK\r\n"


def test_reset_input_drops_stale_reply():
    t = FakeTransport()
    t.open()
    t.feed(b"stale\r\n")
    t.reset_input()
    t.feed(b"fresh\r\n")
    assert t.read_until(b"\r\n", 1) == b"fresh\r\n"


def test_read_exact():
    t = FakeTransport(chunk_size=2)
    t.open()
    t.feed(b"\x01\x02\x03\x04\x05")
    assert t.read_exact(4, 1) == b"\x01\x02\x03\x04"
    assert t.read_exact(1, 1) == b"\x05"


def test_not_open_raises():
    t = FakeTransport()
    with pytest.raises(TransportError):
        t.write(b"x")


def test_scripted_responder_checks_order():
    r = ScriptedResponder([(b"?:N\r\n", b"HIT-MV    \r\n")])
    t = FakeTransport(r)
    t.open()
    t.write(b"?:N\r\n")
    assert t.read_until(b"\r\n", 1) == b"HIT-MV    \r\n"
    assert r.done
    with pytest.raises(AssertionError):
        t.write(b"Q:\r\n")


def test_serial_open_bad_port_is_transport_error():
    t = SerialTransport("COM_DOES_NOT_EXIST", 9600)
    with pytest.raises(TransportError):
        t.open()
