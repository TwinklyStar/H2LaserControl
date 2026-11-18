"""Read-only probe of the DAQ hardware (merge step M1).

PicoScopes: open each unit, read its unit info, close. No acquisition, nothing configured.
IDS camera: open, read a few nodes, stream N frames (default 3), close.
The old notes report the camera link dying after a few open/close cycles: run this sparingly.

    python tools/daq_probe.py [--no-camera] [--no-scopes] [--frames 3]
"""

from __future__ import annotations

import argparse
import ctypes
import time

INFO = {0: "driver", 1: "usb", 2: "hardware", 3: "variant", 4: "serial", 5: "cal_date"}


def _info(fn, handle, idx: int, ps3000a: bool = False) -> str:
    buf = ctypes.create_string_buffer(64)
    req = ctypes.c_int16()
    if ps3000a:
        fn(handle, buf, ctypes.c_int16(len(buf)), ctypes.byref(req), ctypes.c_uint32(idx))
    else:
        fn(handle, buf, ctypes.c_int16(len(buf)), ctypes.c_int16(idx))
    return buf.value.decode(errors="ignore")


def probe_ps2000() -> None:
    from picosdk.ps2000 import ps2000

    handles = []
    while True:
        t0 = time.perf_counter()
        h = ps2000.ps2000_open_unit()
        dt = (time.perf_counter() - t0) * 1000
        if h <= 0:
            print(f"ps2000: open_unit -> {h} (no more units) after {dt:.0f} ms")
            break
        handles.append(h)
        info = {name: _info(ps2000.ps2000_get_unit_info, ctypes.c_int16(h), i)
                for i, name in INFO.items()}
        print(f"ps2000: handle {h} opened in {dt:.0f} ms: {info}")
    for h in handles:
        ps2000.ps2000_close_unit(ctypes.c_int16(h))
    print(f"ps2000: {len(handles)} unit(s) closed")


def probe_ps3000a() -> None:
    from picosdk.ps3000a import ps3000a

    handle = ctypes.c_int16()
    t0 = time.perf_counter()
    status = ps3000a.ps3000aOpenUnit(ctypes.byref(handle), None)
    dt = (time.perf_counter() - t0) * 1000
    print(f"ps3000a: OpenUnit status {status} handle {handle.value} in {dt:.0f} ms")
    if status in (282, 286):  # PICO_POWER_SUPPLY_NOT_CONNECTED / USB3_0_DEVICE_NON_USB3_0_PORT
        status = ps3000a.ps3000aChangePowerSource(handle, status)
        print(f"ps3000a: ChangePowerSource -> {status}")
    if handle.value <= 0:
        return
    try:
        info = {name: _info(ps3000a.ps3000aGetUnitInfo, handle, i, ps3000a=True)
                for i, name in INFO.items()}
        print(f"ps3000a: {info}")
    finally:
        print(f"ps3000a: CloseUnit -> {ps3000a.ps3000aCloseUnit(handle)}")


def probe_camera(n_frames: int) -> None:
    from ids_peak import ids_peak
    from ids_peak_ipl import ids_peak_ipl

    ids_peak.Library.Initialize()
    try:
        dm = ids_peak.DeviceManager.Instance()
        dm.Update()
        devs = dm.Devices()
        print(f"camera: {[(d.SerialNumber(), d.ModelName()) for d in devs]}")
        if not devs:
            return
        dev = devs[0].OpenDevice(ids_peak.DeviceAccessType_Control)
        nm = dev.RemoteDevice().NodeMaps()[0]
        for name in ("DeviceModelName", "DeviceSerialNumber", "DeviceFirmwareVersion",
                     "DeviceLinkSpeed", "Width", "Height", "PixelFormat", "ExposureTime",
                     "AcquisitionFrameRate", "TriggerMode"):
            try:
                node = nm.FindNode(name)
                val = (node.CurrentEntry().SymbolicValue() if hasattr(node, "CurrentEntry")
                       else node.Value())
                print(f"camera: {name} = {val}")
            except Exception as exc:  # noqa: BLE001
                print(f"camera: {name} unavailable ({exc})")
        # 5 fps: a full frame is 3.1 MB, more than a USB 2.0 link (60 MB/s) carries at 20 fps
        nm.FindNode("AcquisitionFrameRate").SetValue(5.0)
        ds = dev.DataStreams()[0].OpenDataStream()
        payload = nm.FindNode("PayloadSize").Value()
        for _ in range(ds.NumBuffersAnnouncedMinRequired()):
            ds.QueueBuffer(ds.AllocAndAnnounceBuffer(payload))
        nm.FindNode("TLParamsLocked").SetValue(1)
        ds.StartAcquisition()
        nm.FindNode("AcquisitionStart").Execute()
        try:
            t0 = time.perf_counter()
            for i in range(n_frames):
                buf = ds.WaitForFinishedBuffer(ids_peak.Timeout(5000))
                if buf.IsIncomplete():
                    print(f"camera: frame {i} id {buf.FrameID()} INCOMPLETE")
                    ds.QueueBuffer(buf)
                    continue
                img = ids_peak_ipl.Image.from_image_view(buf.ToImageView())
                rgb = img.ConvertTo(ids_peak_ipl.PixelFormatName_RGB8)  # keep: numpy is a view
                arr = rgb.get_numpy_3D().copy()
                print(f"camera: frame {i} id {buf.FrameID()} shape {arr.shape} "
                      f"max {arr.max()} t={time.perf_counter() - t0:.2f} s")
                ds.QueueBuffer(buf)
        finally:
            nm.FindNode("AcquisitionStop").Execute()
            nm.FindNode("AcquisitionStop").WaitUntilDone()
            ds.StopAcquisition(ids_peak.AcquisitionStopMode_Kill)
            ds.Flush(ids_peak.DataStreamFlushMode_DiscardAll)
            for b in ds.AnnouncedBuffers():
                ds.RevokeBuffer(b)
            nm.FindNode("TLParamsLocked").SetValue(0)
            del ds, nm, dev
            print("camera: stopped and closed")
    finally:
        ids_peak.Library.Close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--no-scopes", action="store_true")
    ap.add_argument("--frames", type=int, default=3)
    a = ap.parse_args()
    if not a.no_scopes:
        probe_ps3000a()
        probe_ps2000()
    if not a.no_camera:
        probe_camera(a.frames)


if __name__ == "__main__":
    main()
