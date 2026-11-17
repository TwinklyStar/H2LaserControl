"""Read-only probe of an MFF101 via FTDI D2XX (ftd2xx.dll). Sends only query messages."""
import ctypes as C
import struct
import sys
import time

SERIAL = sys.argv[1].encode()
d = C.WinDLL("ftd2xx.dll")
h = C.c_void_p()


def ok(st, what):
    if st != 0:
        raise SystemExit(f"{what} failed: FT_STATUS={st}")


ok(d.FT_OpenEx(C.c_char_p(SERIAL), 1, C.byref(h)), "FT_OpenEx")  # 1 = by serial number
try:
    ok(d.FT_SetBaudRate(h, 115200), "baud")
    ok(d.FT_SetDataCharacteristics(h, 8, 0, 0), "8N1")
    time.sleep(0.05)
    ok(d.FT_Purge(h, 3), "purge")
    time.sleep(0.05)
    ok(d.FT_ResetDevice(h), "reset")
    ok(d.FT_SetFlowControl(h, 0x0100, 0, 0), "rtscts")
    ok(d.FT_SetRts(h), "rts")
    ok(d.FT_SetTimeouts(h, 300, 300), "timeouts")

    def read(n, timeout=1.0):
        buf = b""
        end = time.monotonic() + timeout
        while len(buf) < n and time.monotonic() < end:
            q = C.c_uint32()
            d.FT_GetQueueStatus(h, C.byref(q))
            if q.value:
                b = C.create_string_buffer(min(q.value, n - len(buf)))
                got = C.c_uint32()
                d.FT_Read(h, b, len(b), C.byref(got))
                buf += b.raw[: got.value]
            else:
                time.sleep(0.01)
        return buf

    def xfer(tx, label):
        w = C.c_uint32()
        d.FT_Write(h, tx, len(tx), C.byref(w))
        hdr = read(6)
        print(f"{label}: TX {tx.hex(' ')}")
        if len(hdr) < 6:
            print(f"  RX (incomplete/none) {hdr.hex(' ')}")
            return None, b""
        mid = struct.unpack_from("<H", hdr)[0]
        data = b""
        if hdr[4] & 0x80:
            data = read(struct.unpack_from("<H", hdr, 2)[0])
        print(f"  RX id=0x{mid:04X} hdr {hdr.hex(' ')} data({len(data)}) {data.hex(' ')}")
        extra = read(512, 0.3)
        if extra:
            print(f"  extra bytes: {extra.hex(' ')}")
        return mid, data

    mid, data = xfer(bytes([0x05, 0x00, 0x00, 0x00, 0x50, 0x01]), "HW_REQ_INFO 0x0005")
    if mid == 0x0006 and len(data) >= 84:
        sn, = struct.unpack_from("<I", data, 0)
        model = data[4:12].split(b"\0")[0].decode(errors="replace")
        typ, = struct.unpack_from("<H", data, 12)
        fw = data[14:18]
        notes = data[18:66].split(b"\0")[0].decode(errors="replace")
        hwv, modst, nch = struct.unpack_from("<HHH", data, 78)
        print(f"  serial={sn} model={model!r} type={typ} firmware={fw[2]}.{fw[1]}.{fw[0]} "
              f"notes={notes!r} hw={hwv} modstate={modst} channels={nch}")
    mid, data = xfer(bytes([0x29, 0x04, 0x01, 0x00, 0x50, 0x01]), "MOT_REQ_STATUSBITS 0x0429")
    if mid == 0x042A and len(data) >= 6:
        ch, bits = struct.unpack_from("<HI", data)
        print(f"  chan={ch} status=0x{bits:08X} bits set={[i for i in range(32) if bits >> i & 1]}")
finally:
    d.FT_Close(h)
