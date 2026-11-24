"""Shifter tab (design-document F9) on simulated devices, scopes and camera. Needs pytest-qt."""

import time

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from h2lasercontrol.config import DEFAULT_CONFIG, load_config
from h2lasercontrol.daq.picoscope.session import RUNNING, STOPPED, PicoSession
from h2lasercontrol.daq.picoscope.virtual import VirtualDigitizer
from h2lasercontrol.gui.main_window import MainWindow
from h2lasercontrol.oplog import OpLog, read_oplog
from h2lasercontrol.services import device_service
from h2lasercontrol.shifter import (
    DONE,
    ShifterSettings,
    blocking,
    duration_text,
    load_shifter_settings,
    operating_state,
)
from h2lasercontrol.shifter import (
    STOPPED as SEQ_STOPPED,
)
from h2lasercontrol.sim import Dg645Sim, Ell14Sim, HitMvSim, MffSim
from h2lasercontrol.transport import FakeTransport

pytest.importorskip("pytestqt")


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, request):
    def fast_sim(cfg):
        if cfg.type == "hitmv":
            return FakeTransport(HitMvSim(busy_polls=5))
        if cfg.type == "mff":
            return {k: FakeTransport(MffSim(serial=int(u["usb_serial"])))
                    for k, u in cfg.settings["units"].items()}
        if cfg.type == "dg645":
            return FakeTransport(Dg645Sim())
        return FakeTransport(Ell14Sim(clean_polls=1))

    monkeypatch.setattr(device_service, "make_sim_transport", fast_sim)
    monkeypatch.setattr(VirtualDigitizer, "TRIGGER_RATE_HZ", 500.0)
    asked = []

    def answer_yes(box):
        asked.append(box.text())
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "exec", answer_yes)
    oplog = OpLog(tmp_path / "logs", user="tester")
    settings = QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)
    w = MainWindow(load_config(DEFAULT_CONFIG), oplog, sim=True, settings=settings,
                   state_dir=str(tmp_path), daq_base_dir=str(tmp_path))
    w.asked = asked
    qtbot.addWidget(w)
    request.addfinalizer(lambda: [s.shutdown() for s in w.services])
    request.addfinalizer(w.shutdown_daq)
    request.addfinalizer(w.shifter.shutdown)
    w.start()
    for p in w.panels:
        qtbot.waitUntil(lambda p=p: bool(p.connected and p.state), timeout=5000)
    s = w.shifter_ctx.settings
    s.pulses, s.photos = 40, 3  # short runs
    # a max-energy angle (as saved by the user on the Rotation mount tab)
    ell = panel(w, "ell14")
    ell.run("save_max_energy")
    qtbot.waitUntil(lambda: bool(ell.state.get("max_energy")) and not ell.busy, timeout=5000)
    return w


def panel(w, key):
    return next(p for p in w.panels if p.cfg.key == key)


def daq(w, key):
    return next(t for t in w.daq_tabs if t.cfg.key == key)


def entries(w):
    return read_oplog(w.oplog.today_path())


def run_and_wait(w, qtbot, start, timeout=30000):
    runner = w.shifter.runner
    start()
    assert runner.running
    qtbot.waitUntil(lambda: not runner.running, timeout=timeout)
    return runner.outcome, runner.message


def go_operating(w, qtbot):
    """Return to operating state (the simulated flip mounts start inserted)."""
    outcome, msg = run_and_wait(w, qtbot, w.shifter.return_btn.click)
    assert outcome == DONE, msg
    w.shifter._refresh()


def test_settings_file_and_defaults(tmp_path):
    s = load_shifter_settings()  # config/shifter.toml (user 2026-11-24)
    assert (s.pulses, s.photos, s.energy_percent_355) == (1000, 100, 10)
    assert (s.vuv_pd_axis, s.mirror_axis, s.blocker_355, s.blocker_820) == (0, 1, "flip1", "flip2")
    assert load_shifter_settings(tmp_path / "missing.toml") == ShifterSettings()
    bad = tmp_path / "bad.toml"
    bad.write_text("pulse = 5\n")
    with pytest.raises(ValueError, match="unknown"):
        load_shifter_settings(bad)
    assert duration_text(50) == "about 50 s" and duration_text(130) == "about 2 min"


def test_shifter_tab_first_and_not_ready_until_operating_state(window, qtbot):
    w = window
    assert w.tabs.tabText(0) == "Shifter" and w.tabs.currentIndex() == 0
    sh = w.shifter
    sh._refresh()
    names = [i.name for i in sh.items]
    assert names[:5] == ["VUV photodiode", "Projection mirror", "355 nm blocker",
                         "820 nm blocker", "Rotation mount"]
    assert {"Delay generator (C)", "Camera", "NO cell monitor", "VUV PD snapshot"} <= set(names)
    # simulated flip mounts start inserted: nothing can start, and the box says why
    assert "not OK" in sh.overall_label.text()
    for box in sh.boxes.values():
        assert not box.start_btn.isEnabled()
        assert "355 nm blocker INSERTED" in box.problem_label.text()
    go_operating(w, qtbot)
    vuv = sh.boxes["vuv_energy"]
    assert vuv.start_btn.isEnabled() and not vuv.problem_label.text()
    # the profile measurements need the open camera
    assert not sh.boxes["profile_122"].start_btn.isEnabled()
    assert "Camera closed" in sh.boxes["profile_122"].problem_label.text()


def test_vuv_energy_measurement(window, qtbot, tmp_path):
    w = window
    sh = w.shifter
    go_operating(w, qtbot)
    mark = len(entries(w))
    hit = panel(w, "hitmv")
    box = sh.boxes["vuv_energy"]
    box.start_btn.click()
    runner = sh.runner
    assert runner.running
    assert "block the laser beam" in w.asked[-1] and "about" in w.asked[-1]  # F9e
    # the device tabs used are locked while it runs
    assert hit.locked and daq(w, "vuv_pd").locked and not hit.can_act
    # the snapshot opens only after the photodiode is fully inserted
    qtbot.waitUntil(lambda: runner.index == 2, timeout=15000)
    info = hit.state["axes"]["vuv_photodiode"]
    assert info["named"] == "INSERTED"
    qtbot.waitUntil(lambda: not runner.running, timeout=30000)
    assert runner.outcome == DONE, runner.message
    assert not hit.locked and not daq(w, "vuv_pd").locked
    assert daq(w, "vuv_pd").session.state == STOPPED  # closed again
    # preview: the same snapshot view (128-average), result: all 40 pulses
    assert sh.snapshot_view is not None and sh.snapshot_view.n_avg == 128
    r = runner.summary()
    assert r["n"] == 40 and r["stderr_nVs"] > 0
    csv = r["csv"]
    assert csv.endswith(".csv")
    with open(csv, encoding="utf-8") as f:
        assert "(N = 40 triggers)" in f.read()
    assert len(r["root"]) == 1
    import uproot
    with uproot.open(r["root"][0]) as f:
        assert f["rawWave"].num_entries == 40  # exactly N waveforms in the ROOT file
    assert "Area" in box.result_label.text() and "Finished" in box.result_label.text()
    # order of the device actions in the operation history
    acts = [(e["device"], e["action"], (e.get("args") or {}).get("axis",
             (e.get("args") or {}).get("unit")))
            for e in entries(w)[mark:] if e["event"] == "done"
            and e["action"] in ("insert", "retract", "acquire")]
    assert acts == [("flipmounts", "insert", "flip1"), ("hitmv", "insert", 0),
                    ("vuv_pd", "acquire", None), ("hitmv", "retract", 0),
                    ("flipmounts", "retract", "flip1")]
    done = [e for e in entries(w) if e["device"] == "shifter" and e["action"] == "vuv_energy"]
    assert [e["event"] for e in done] == ["start", "done"]
    assert "VUV area" in done[-1]["result"]["text"]


def test_stop_then_return(window, qtbot):
    w = window
    sh = w.shifter
    go_operating(w, qtbot)
    sh.boxes["vuv_energy"].start_btn.click()
    runner = sh.runner
    qtbot.waitUntil(lambda: runner.index == 1, timeout=10000)  # photodiode inserting
    hit = panel(w, "hitmv")
    # the move shows live in the feedthrough tab and in the step ("x % inserted")
    qtbot.waitUntil(lambda: hit.moving is not None, timeout=5000)
    assert hit.moving == (0, "insert") and "Inserting VUV photodiode" in hit.busy_label.text()
    qtbot.waitUntil(lambda: "% inserted" in runner.step.detail, timeout=5000)
    sh.stop_btn.click()
    qtbot.waitUntil(lambda: not runner.running, timeout=10000)
    assert runner.outcome == SEQ_STOPPED
    assert [r.state for r in runner.records][:3] == ["done", "failed", "skipped"]
    assert "Stopped" in sh.boxes["vuv_energy"].result_label.text()
    sh._refresh()
    assert not sh.boxes["vuv_energy"].start_btn.isEnabled()  # not in the operating state
    assert sh.return_btn.isEnabled()
    go_operating(w, qtbot)
    assert hit.state["axes"]["vuv_photodiode"]["named"] == "RETRACTED"
    assert sh.boxes["vuv_energy"].start_btn.isEnabled()


def open_camera(w, qtbot):
    cam = daq(w, "camera")
    cam.start_btn.click()
    qtbot.waitUntil(lambda: cam.window is not None, timeout=10000)
    qtbot.waitUntil(lambda: cam.window._live_view.last_frame is not None, timeout=10000)
    return cam


def test_profile_122_and_355(window, qtbot, tmp_path):
    w = window
    sh = w.shifter
    cam = open_camera(w, qtbot)
    go_operating(w, qtbot)
    assert cam.current_config() == "default.toml"
    box = sh.boxes["profile_122"]
    assert box.combo.currentText() == "H2_122_Jun20.toml"
    assert box.start_btn.isEnabled()
    outcome, msg = run_and_wait(w, qtbot, box.start_btn.click, timeout=60000)
    assert outcome == DONE, msg
    assert cam.current_config() == "H2_122_Jun20.toml"
    photos = sh.runner.summary()["photos"]
    assert photos["photos"] == 3
    assert len(list((tmp_path / "data" / "camera").rglob("*.bmp"))) >= 3
    assert sh.preview_stack.currentWidget() is sh.camera_page

    # 355 nm: 820 blocker in, 10 % energy, back to max
    sh._refresh()
    box = sh.boxes["profile_355"]
    box.combo.setCurrentText("H2_355.toml")
    mark = len(entries(w))
    outcome, msg = run_and_wait(w, qtbot, box.start_btn.click, timeout=60000)
    assert outcome == DONE, msg
    ell = [e for e in entries(w)[mark:] if e["device"] == "ell14" and e["event"] == "done"]
    assert [e["action"] for e in ell] == ["set_energy", "go_to_max_energy"]
    assert ell[0]["args"] == {"percent": 10.0}
    assert abs(ell[0]["result"]["estimated_percent"] - 10) < 1
    flips = [(e["action"], e["args"]["unit"]) for e in entries(w)[mark:]
             if e["device"] == "flipmounts" and e["event"] == "done"]
    assert flips == [("insert", "flip2"), ("retract", "flip2")]
    assert cam.current_config() == "H2_355.toml"
    # Return puts the camera config from before the first profile back
    go_operating(w, qtbot)
    assert cam.current_config() == "default.toml"
    assert sh.ctx.camera_config_before is None


def test_vuv_snapshot_running_in_daq_tab_blocks_vuv(window, qtbot):
    w = window
    go_operating(w, qtbot)
    t = daq(w, "vuv_pd")
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.session.state == RUNNING, timeout=10000)
    items = operating_state(w.shifter_ctx)
    assert [i.name for i in blocking(items, "vuv_energy")] == ["VUV PD snapshot"]
    assert not blocking(items, "profile_122") or all(
        i.name == "Camera" for i in blocking(items, "profile_122"))
    t.stop_btn.click()
    qtbot.waitUntil(lambda: t.session.state == STOPPED, timeout=10000)


def test_no_cell_monitor_in_shifter_tab(window, qtbot):
    w = window
    sh = w.shifter
    assert sh.monitor_stack.currentIndex() == 0 and "not running" in sh.monitor_idle_label.text()
    sh.monitor_start_btn.click()
    mon = daq(w, "scope_monitor")
    qtbot.waitUntil(lambda: sh.monitor_view is not None, timeout=10000)
    assert sh.monitor_view.channels == ["NO_cell"]  # only the NO cell (user 2026-11-24)
    qtbot.waitUntil(lambda: sh.monitor_view.wave_frames > 0, timeout=10000)
    mon.stop_btn.click()
    qtbot.waitUntil(lambda: mon.session.state == STOPPED, timeout=10000)
    qtbot.waitUntil(lambda: sh.monitor_view is None, timeout=5000)


def test_session_stops_by_itself_after_max_triggers(tmp_path):
    oplog = OpLog(tmp_path / "logs", user="tester")
    from h2lasercontrol.config import PROGRAM_DIR
    from h2lasercontrol.daq.picoscope.configs import load_scope_config

    sc = load_scope_config(PROGRAM_DIR / "config" / "picoscope" / "H2PD_261103.toml")
    s = PicoSession("vuv_pd", sc.settings(), oplog, sim=True, base_dir=tmp_path)
    VirtualDigitizer.TRIGGER_RATE_HZ, old = 1000.0, VirtualDigitizer.TRIGGER_RATE_HZ
    try:
        s.start(max_triggers=25)
        t0 = time.time()
        while s.state != STOPPED and time.time() - t0 < 10:
            s.poll()
            time.sleep(0.02)
    finally:
        VirtualDigitizer.TRIGGER_RATE_HZ = old
    assert s.state == STOPPED and not s.errors
    assert [d.total_triggers for d in s.digitizers.values()] == [25]
    last = read_oplog(oplog.today_path())[-1]
    assert last["action"] == "acquire" and last["result"]["waveforms"] == {
        n: 25 for n in s.digitizers}


def test_camera_config_trigger_mode_round_trip(tmp_path):
    from h2lasercontrol.config import PROGRAM_DIR
    from h2lasercontrol.laserdaq.config import load_config as load_cam
    from h2lasercontrol.laserdaq.config import save_config

    src = PROGRAM_DIR / "config" / "camera" / "H2_355.toml"
    cfg = load_cam(src)
    assert cfg.trigger_mode == "" and cfg.trigger_fps == 0
    out = tmp_path / "a.toml"
    save_config(cfg, out)
    assert "trigger" not in out.read_text()  # files without a trigger stay as they were
    cfg.trigger_mode, cfg.trigger_fps = "hardware", 25.0
    save_config(cfg, out)
    back = load_cam(out)
    assert (back.trigger_mode, back.trigger_fps) == ("hardware", 25.0)
