"""PicoScope acquisition (F8) on simulated scopes: output formats unchanged (F8c), Start /
Pause / Stop (F8a), one failing scope does not stop the others, op-log entries."""

import csv
import ctypes
import time

import numpy as np
import pytest
import uproot

from h2lasercontrol.config import DEFAULT_CONFIG, PROGRAM_DIR, load_config
from h2lasercontrol.daq.picoscope import assistant
from h2lasercontrol.daq.picoscope import digitizer as digitizer_mod
from h2lasercontrol.daq.picoscope import session as session_mod
from h2lasercontrol.daq.picoscope.configs import (
    ScopeConfigError,
    list_scope_configs,
    load_scope_config,
)
from h2lasercontrol.daq.picoscope.session import PAUSED, RUNNING, STOPPED, PicoSession
from h2lasercontrol.daq.picoscope.virtual import VirtualDigitizer, range_mv, sample_interval_ns
from h2lasercontrol.oplog import OpLog, read_oplog


@pytest.fixture(autouse=True)
def fast_triggers(monkeypatch):
    monkeypatch.setattr(VirtualDigitizer, "TRIGGER_RATE_HZ", 2000.0)


SCOPE_DIR = PROGRAM_DIR / "config" / "picoscope"
FILES = {"scope_monitor": "monitor_2026A.toml", "vuv_pd": "H2PD_261103.toml"}


@pytest.fixture
def cfg():
    return load_config(DEFAULT_CONFIG)


def wait(cond, timeout=10.0, session=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if session is not None:
            session.poll()
        if cond():
            return True
        time.sleep(0.01)
    raise AssertionError("timeout")


def make(cfg, key, tmp_path):
    oplog = OpLog(tmp_path / "logs", user="tester")
    settings = load_scope_config(SCOPE_DIR / FILES[key]).settings()
    return PicoSession(key, settings, oplog, sim=True, base_dir=tmp_path), oplog


def test_config_matches_old_programs(cfg):
    assert cfg["scope_monitor"].settings["default_config"] == FILES["scope_monitor"]
    assert cfg["vuv_pd"].settings["default_config"] == FILES["vuv_pd"]
    mon = load_scope_config(SCOPE_DIR / FILES["scope_monitor"])
    assert mon.mode == "continuous"
    assert {n: (d["model"], d["serial"]) for n, d in mon.digitizers.items()} == {
        "DET10A2": ("3405D", "JY926/0005"), "NOCell": ("2204A", "12017/0359")}
    snap = load_scope_config(SCOPE_DIR / FILES["vuv_pd"])
    assert snap.mode == "snapshot"
    h2pd = snap.digitizers["H2PD"]
    assert (h2pd["serial"], h2pd["output_name"], h2pd["refresh_trigger_cnt"]) == (
        "12017/0366", "H2PD_2026B", 100)
    assert cfg["camera"].usb_serial == "4110039161"


def test_old_helpers_unchanged():
    # ADC -> mV exactly as the old picoDAQAssistant (2 V range = index 7, maxADC 32767)
    buf = np.array([32767, 0, -16384], dtype=np.int16)
    mv = assistant.fastAdc2mV(buf, 7, ctypes.c_int16(32767), 0)
    assert mv == pytest.approx([2000.0, 0.0, -16384 * 2000 / 32767])
    assert assistant.extTrigmV2Adc(1000) == int(1 / 5 * 32767)
    assert range_mv("200MV") == 200 and range_mv("2V") == 2000
    assert sample_interval_ns("3405D", 1) == 2 and sample_interval_ns("3405D", 52) == 400
    assert sample_interval_ns("2204A", 9) == 5120


def test_continuous_output_format(cfg, tmp_path):
    s, oplog = make(cfg, "scope_monitor", tmp_path)
    s.start()
    wait(lambda: s.state == RUNNING, session=s)
    det = s.digitizers["DET10A2"]
    wait(lambda: det.csv_pointer is not None and det.csv_pointer.tell() > 300, session=s)
    items = s.poll()
    s.stop()
    wait(lambda: s.state == STOPPED, session=s)

    date = time.strftime("%y%m%d")
    base = tmp_path / "data" / "picoscope"
    # CSV: same name and columns as the old program, one row per 100 triggers
    with open(base / "csv" / f"FreeSpacePD_2026June_{date}.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["timestamp", "212", "820"]
    assert len(rows) >= 3 and float(rows[1][1]) < 0  # negative simulated pulse
    # ROOT: tree rawWave with the old branches and types
    path = base / "root" / f"FreeSpacePD_2026June_{date}_0000.root"
    tree = uproot.open(path)["rawWave"]
    types = {k: v.interpretation for k, v in tree.items()}
    assert list(types) == ["Run", "WaveN", "Year", "Month", "Day", "Hour", "Min", "Sec", "ms",
                           "nTime", "Time", "ChB", "ChC"]
    expected = {"Run": "i4", "WaveN": "i4", "Year": "i2", "Month": "i1", "Day": "i1",
                "Hour": "i1", "Min": "i1", "Sec": "i1", "ms": "i2", "nTime": "i4",
                "Time": "f4", "ChB": "f4", "ChC": "f4"}
    for k, code in expected.items():
        assert types[k].from_dtype.base.str[1:] == code, k  # big-endian in the file
    arr = tree.arrays(["WaveN", "nTime", "Time", "ChB"], library="np")
    n = len(arr["WaveN"])
    assert n >= 200 and list(arr["WaveN"][:3]) == [0, 1, 2]
    assert arr["nTime"][0] == 1000 and arr["Time"].shape == (n, 1000)
    assert arr["Time"][0][1] == pytest.approx(2.0)  # timebase 1 on the 3405D = 2 ns
    assert (tmp_path / "data" / "picoscope" / "csv" / f"NOCell_2026June_{date}.csv").exists()
    # data items for the plots: old keys
    s2 = [i for i in items if "channel_name" in i]
    assert not s2 or set(s2[0]) == {"channel_name", "timestamp", "value", "wfm_t", "wfm"}
    # op log: start + stop with the files
    acts = [(e["action"], e["event"]) for e in read_oplog(oplog.today_path())]
    assert acts == [("start", "done"), ("stop", "start"), ("stop", "done")]
    stop = read_oplog(oplog.today_path())[-1]
    assert str(path) in stop["result"]["files"]


def test_pause_takes_no_data_and_resume_continues(cfg, tmp_path):
    s, oplog = make(cfg, "vuv_pd", tmp_path)
    s.start()
    wait(lambda: s.state == RUNNING, session=s)
    d = s.digitizers["H2PD"]
    wait(lambda: d.root_pointer is not None and d.root_pointer._wave_n > 50, session=s)
    s.pause()
    wait(lambda: d.state == PAUSED, session=s)
    assert s.state == PAUSED
    n = d.root_pointer._wave_n
    time.sleep(0.3)  # would be ~600 triggers at the test rate
    s.poll()
    assert d.root_pointer._wave_n == n
    root_file = d.root_pointer.getName()
    s.resume()
    wait(lambda: d.root_pointer._wave_n > n + 20, session=s)
    assert d.root_pointer.getName() == root_file  # same file after resume
    s.stop()
    wait(lambda: s.state == STOPPED, session=s)
    acts = [e["action"] for e in read_oplog(oplog.today_path())]
    assert acts == ["start", "pause", "resume", "stop", "stop"]


def test_snapshot_items(cfg, tmp_path):
    s, _ = make(cfg, "vuv_pd", tmp_path)
    s.start()
    got = []
    wait(lambda: got.extend(s.poll()) or got, timeout=10)
    s.stop()
    wait(lambda: s.state == STOPPED, session=s)
    item = got[0]
    assert set(item) == {"device", "t", "area_avg", "area_std", "trigger_cnt", "ChA", "ChB"}
    assert item["device"] == "H2PD" and item["trigger_cnt"] == 100
    assert item["area_avg"] < 0 < item["area_std"]


def test_one_failing_scope_does_not_stop_the_other(cfg, tmp_path, monkeypatch):
    real_init = VirtualDigitizer._init_hardware

    def init(self, config):
        if self.device == "NOCell":
            raise RuntimeError("unplugged")
        real_init(self, config)

    monkeypatch.setattr(VirtualDigitizer, "_init_hardware", init)
    s, oplog = make(cfg, "scope_monitor", tmp_path)
    s.start()
    wait(lambda: s.states.get("NOCell") == "error" and s.states.get("DET10A2") == RUNNING,
         session=s)
    assert "unplugged" in s.errors["NOCell"]
    assert s.state == RUNNING
    failed = [e for e in read_oplog(oplog.today_path()) if e["event"] == "failed"]
    assert failed and failed[0]["args"] == {"scope": "NOCell"}
    s.stop()
    wait(lambda: s.state == STOPPED, session=s)


def test_failed_readout_skips_one_waveform(cfg, tmp_path, monkeypatch):
    """M7: the 3405D once returned PICO_TIMEOUT from GetValues after a 5 s USB stall. One
    failed readout skips that waveform and the run goes on (the old code ended the run)."""
    real = VirtualDigitizer._capture_block
    calls = {"n": 0}

    def capture(self):
        if self.device == "DET10A2":
            calls["n"] += 1
            if calls["n"] in (20, 40, 41):  # one failure, then two in a row
                raise digitizer_mod.ReadoutError("GetValues returned PICO_TIMEOUT")
        return real(self)

    monkeypatch.setattr(VirtualDigitizer, "_capture_block", capture)
    s, oplog = make(cfg, "scope_monitor", tmp_path)
    s.start()
    d = s.digitizers["DET10A2"]
    wait(lambda: calls["n"] > 60 and d.root_pointer._wave_n > 50, session=s)
    assert s.states["DET10A2"] == RUNNING and "PICO_TIMEOUT" in s.warnings["DET10A2"]
    assert d.skipped == 3
    s.stop()
    wait(lambda: s.state == STOPPED, session=s)
    stop = read_oplog(oplog.today_path())[-1]
    assert stop["result"]["skipped_waveforms"] == {"DET10A2": 3}


def test_not_responding_scope_is_reconnected(cfg, tmp_path, monkeypatch):
    """3 failures in a row: close + reopen, same files, CSV sums kept, run goes on."""
    monkeypatch.setattr(digitizer_mod, "RECONNECT_WAIT_S", 0.01)
    real = VirtualDigitizer._capture_block
    real_init = VirtualDigitizer._init_hardware
    calls = {"n": 0, "init": 0}

    def capture(self):
        if self.device == "DET10A2":
            calls["n"] += 1
            if 30 <= calls["n"] < 33:
                raise digitizer_mod.ReadoutError("GetValues returned PICO_NOT_RESPONDING")
        return real(self)

    def init(self, config):
        if self.device == "DET10A2":
            calls["init"] += 1
        real_init(self, config)

    monkeypatch.setattr(VirtualDigitizer, "_capture_block", capture)
    monkeypatch.setattr(VirtualDigitizer, "_init_hardware", init)
    s, oplog = make(cfg, "scope_monitor", tmp_path)
    s.start()
    d = s.digitizers["DET10A2"]
    wait(lambda: d.reconnects == 1 and calls["n"] > 250, session=s)
    root_file = d.root_pointer.getName()
    assert calls["init"] == 2 and s.states["DET10A2"] == RUNNING
    assert "reconnected" in s.warnings["DET10A2"]
    s.stop()
    wait(lambda: s.state == STOPPED, session=s)
    assert d.files.count(root_file) == 1  # same ROOT file before and after
    stop = read_oplog(oplog.today_path())[-1]["result"]
    assert stop["reconnects"] == {"DET10A2": 1} and stop["skipped_waveforms"] == {"DET10A2": 3}
    # CSV rows still sum exactly 100 triggers: the row in progress kept its sums
    date = time.strftime("%y%m%d")
    with open(tmp_path / "data" / "picoscope" / "csv" / f"FreeSpacePD_2026June_{date}.csv",
              newline="") as f:
        vals = [float(r[1]) for r in list(csv.reader(f))[1:]]
    assert len(vals) >= 2 and max(vals) / min(vals) < 1.5


def test_scope_that_stays_dead_ends_with_error(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(digitizer_mod, "RECONNECT_WAIT_S", 0.01)
    real = VirtualDigitizer._capture_block

    def capture(self):
        if self.device == "DET10A2":
            raise digitizer_mod.ReadoutError("GetValues returned PICO_NOT_RESPONDING")
        return real(self)

    monkeypatch.setattr(VirtualDigitizer, "_capture_block", capture)
    s, _ = make(cfg, "scope_monitor", tmp_path)
    s.start()
    wait(lambda: s.states.get("DET10A2") == "error", session=s)
    assert f"after {digitizer_mod.MAX_RECONNECTS} reconnects" in s.errors["DET10A2"]
    assert s.digitizers["DET10A2"].reconnects == digitizer_mod.MAX_RECONNECTS
    assert s.state == RUNNING  # NOCell goes on
    s.stop()
    wait(lambda: s.state == STOPPED, session=s)


def test_shutdown_closes_files(cfg, tmp_path):
    s, _ = make(cfg, "scope_monitor", tmp_path)
    s.start()
    wait(lambda: s.state == RUNNING, session=s)
    s.shutdown()
    assert s.state == STOPPED
    assert all(not d.is_alive() for d in s.digitizers.values())


def test_start_twice_is_ignored(cfg, tmp_path):
    s, oplog = make(cfg, "vuv_pd", tmp_path)
    s.start()
    first = s.digitizers["H2PD"]
    s.start()
    assert s.digitizers["H2PD"] is first
    s.shutdown()
    assert [e["action"] for e in read_oplog(oplog.today_path())].count("start") == 1


def test_session_needs_digitizers(tmp_path):
    with pytest.raises(ValueError):
        PicoSession("x", {"mode": "continuous"}, OpLog(tmp_path), sim=True)
    assert session_mod.STOPPED == STOPPED


def test_all_old_configs_converted():
    cont, errors = list_scope_configs(SCOPE_DIR, "continuous")
    snap, _ = list_scope_configs(SCOPE_DIR, "snapshot")
    assert not errors
    assert [c.name for c in cont] == ["H2PD_monitor_261103.toml", "monitor_2026A.toml"]
    assert [c.name for c in snap] == ["H2PD.toml", "H2PD_260628.toml", "H2PD_261008_cali.toml",
                                      "H2PD_261103.toml", "LaserRoomPD.toml", "NOCell.toml"]
    cali = load_scope_config(SCOPE_DIR / "H2PD_261008_cali.toml")
    assert cali.digitizers["H2PD"]["data_path"] == "data/picoscope/PDcal_261013"  # was data/...


def test_invalid_config_files_are_reported(tmp_path):
    (tmp_path / "a.toml").write_text('mode = "snapshot"\n[digitizers.X]\nmodel = "2204A"\n')
    (tmp_path / "b.toml").write_text("not toml [")
    (tmp_path / "c.toml").write_text('mode = "weird"\n')
    good, errors = list_scope_configs(tmp_path)
    assert good == [] and len(errors) == 3
    assert "missing" in errors[0] and "cannot be read" in errors[1] and "mode" in errors[2]
    with pytest.raises(ScopeConfigError):
        load_scope_config(tmp_path / "a.toml")
