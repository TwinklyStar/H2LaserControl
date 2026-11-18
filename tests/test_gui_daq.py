"""GUI tests of the DAQ tabs (F8) on simulated PicoScopes and a mock camera. Needs pytest-qt."""

import time

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from h2lasercontrol.config import DEFAULT_CONFIG, load_config
from h2lasercontrol.daq.picoscope.session import PAUSED, RUNNING, STOPPED
from h2lasercontrol.daq.picoscope.virtual import VirtualDigitizer
from h2lasercontrol.gui.daq import CameraTab, ScopeTab
from h2lasercontrol.gui.main_window import MainWindow
from h2lasercontrol.oplog import OpLog, read_oplog

pytest.importorskip("pytestqt")


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, request):
    monkeypatch.setattr(VirtualDigitizer, "TRIGGER_RATE_HZ", 1000.0)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    oplog = OpLog(tmp_path / "logs", user="tester")
    settings = QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)
    w = MainWindow(load_config(DEFAULT_CONFIG), oplog, sim=True, settings=settings,
                   state_dir=str(tmp_path), daq_base_dir=str(tmp_path))
    qtbot.addWidget(w)
    request.addfinalizer(w.shutdown_daq)
    request.addfinalizer(lambda: [s.shutdown() for s in w.services])
    return w


def tab(w, key):
    return next(t for t in w.daq_tabs if t.cfg.key == key)


def actions(w):
    return [(e["device"], e["action"], e["event"]) for e in read_oplog(w.oplog.today_path())]


def test_scope_tab_start_pause_stop(window, qtbot):
    t: ScopeTab = tab(window, "scope_monitor")
    assert t.session.state == STOPPED  # nothing starts by itself (F8a)
    # start page only (no plots) until Start (user 2026-11-18)
    assert t.stack.currentIndex() == 0 and t.view is None and t.start_btn.isEnabled()

    t.start_btn.click()
    qtbot.waitUntil(lambda: t.session.state == RUNNING, timeout=10000)
    assert t.stack.currentWidget() is t.run_page and t.view is not None
    # keeps running while another tab is shown
    window.tabs.setCurrentIndex(0)
    qtbot.waitUntil(lambda: t.view.n_points["212"] >= 2, timeout=10000)
    assert t.session.state == RUNNING

    t.pause_btn.click()
    qtbot.waitUntil(lambda: t.session.state == PAUSED, timeout=5000)
    assert t.pause_btn.text().endswith("Resume") and "Paused" in t.state_label.text()
    n = t.view.n_points["212"]
    qtbot.wait(400)  # ~400 triggers at the test rate if it were still running
    assert t.view.n_points["212"] == n  # display frozen, no data taken

    t.pause_btn.click()  # resume
    qtbot.waitUntil(lambda: t.view.n_points["212"] > n, timeout=10000)
    t.stop_btn.click()
    qtbot.waitUntil(lambda: t.session.state == STOPPED, timeout=10000)
    qtbot.waitUntil(lambda: t.stack.currentIndex() == 0, timeout=5000)  # back to start page
    assert t.start_btn.isEnabled() and t.view is None
    assert ("scope_monitor", "stop", "done") in actions(window)

    t.start_btn.click()  # can be started again
    qtbot.waitUntil(lambda: t.session.state == RUNNING, timeout=10000)


def test_scope_tabs_are_independent(window, qtbot):
    mon, snap = tab(window, "scope_monitor"), tab(window, "vuv_pd")
    snap.start_btn.click()
    qtbot.waitUntil(lambda: snap.session.state == RUNNING, timeout=10000)
    assert mon.session.state == STOPPED
    mon.start_btn.click()
    qtbot.waitUntil(lambda: mon.session.state == RUNNING, timeout=10000)
    snap.stop_btn.click()
    qtbot.waitUntil(lambda: snap.session.state == STOPPED, timeout=10000)
    assert mon.session.state == RUNNING


def test_monitor_hides_trigger_shows_rate_and_reads_history(window, qtbot, tmp_path):
    # history written by an earlier run: one row per minute for the last 2 days
    csv_dir = tmp_path / "data" / "picoscope" / "csv"
    csv_dir.mkdir(parents=True)
    now = time.time()
    files: dict[str, list[str]] = {}
    for t in range(int(now - 2 * 86400), int(now) - 60, 60):
        day = time.strftime("%y%m%d", time.localtime(t))
        files.setdefault(day, []).append(f"{t},{t % 3},{t % 4}\n")
    for day, rows in files.items():
        (csv_dir / f"NOCell_2026June_{day}.csv").write_text("timestamp,NO_cell,Trig\n" + "".join(rows))
    t: ScopeTab = tab(window, "scope_monitor")
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.session.state == RUNNING, timeout=10000)
    v = t.view
    # trigger channel (NOCell ch B "Trig") not plotted; the 3405D has an external trigger
    assert v.channels == ["212", "820", "NO_cell"]
    assert v.window == "5 hr" and v.window_combo.count() == 10
    assert 295 <= v.n_points["NO_cell"] <= 302  # 5 h of history, one row per minute
    v.set_window("1 day")
    assert 1435 <= v.n_points["NO_cell"] <= 1442
    v.window_combo.setCurrentText("10 min")
    assert v.n_points["NO_cell"] <= 12 and t.trend_window == "10 min"
    # follows the newest data until the user zooms; "Latest" follows again
    assert not v.latest_btn.isEnabled()
    v._on_manual_range()
    assert v.latest_btn.isEnabled()
    v.latest_btn.click()
    assert not v.latest_btn.isEnabled()
    # trigger rate in the status row (posted every 5 s by each digitizer)
    qtbot.waitUntil(lambda: "DET10A2" in v._lbl_rate.text() and "NOCell" in v._lbl_rate.text()
                    and v._lbl_rate.text().count("Hz") == 2, timeout=15000)
    assert "triggers/s" not in t.detail_label.text()
    # the CSV file itself still has the trigger column (format unchanged)
    t.stop_btn.click()
    qtbot.waitUntil(lambda: t.session.state == STOPPED, timeout=10000)
    today = csv_dir / f"NOCell_2026June_{time.strftime('%y%m%d')}.csv"
    assert today.read_text().splitlines()[0] == "timestamp,NO_cell,Trig"
    # the window choice is kept for the next run
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.view is not None, timeout=10000)
    assert t.view.window == "10 min"


def test_monitor_waveforms_refresh_with_every_trigger(window, qtbot, monkeypatch):
    monkeypatch.setattr(VirtualDigitizer, "TRIGGER_RATE_HZ", 25.0)  # the real trigger rate
    t: ScopeTab = tab(window, "scope_monitor")
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.view is not None and t.view.wave_frames > 0, timeout=10000)
    v = t.view
    f0, t0 = v.wave_frames, time.monotonic()
    qtbot.wait(2000)
    fps = (v.wave_frames - f0) / (time.monotonic() - t0)
    assert fps > 15, fps  # was one redraw per 100 triggers (every 4 s)
    # sliding average of the last 100 waveforms per scope; trigger channel not averaged
    qtbot.waitUntil(lambda: v._wave_avg["DET10A2"].count >= 60, timeout=10000)
    assert set(v._wave_avg["NOCell"].mean_waves()) == {"NO_cell"}
    x, y = v._wfm_curves["212"].getData()
    assert len(x) == 1000 and y.min() < 0
    t.stop_btn.click()
    qtbot.waitUntil(lambda: t.session.state == STOPPED, timeout=10000)


def test_snapshot_hides_trigger_channel(window, qtbot):
    t: ScopeTab = tab(window, "vuv_pd")
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.view is not None and t.view.averager.count > 0, timeout=10000)
    assert t.view.channels == ["A"] and t.view.channel_labels == ["Sig"]
    assert set(t.view.averager.mean_waves()) == {"A"}  # the trigger (B) is not even averaged
    qtbot.waitUntil(lambda: "H2PD" in t.view._lbl_rate.text() and "Hz" in t.view._lbl_rate.text(),
                    timeout=15000)
    t.stop_btn.click()
    qtbot.waitUntil(lambda: t.session.state == STOPPED, timeout=10000)


def test_snapshot_freeze_and_save(window, qtbot, tmp_path):
    t: ScopeTab = tab(window, "vuv_pd")
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.view is not None and t.view.averager.count > 0, timeout=10000)
    t.view._freeze_btn.click()
    assert t.view._freeze_btn.text() == "Unfreeze" and "Math:" in t.view._lbl_math.text()
    t.view._save_btn.click()
    files = list((tmp_path / "data" / "picoscope" / "snapshots").glob("snapshot_H2PD_*_001.csv"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8").splitlines()
    assert text[0] == "# H2LaserDAQ Snapshot" and text[2] == "# Device  : H2PD"
    assert text[4].startswith("# Area (live)  :") and text[5].startswith("# Offset       :")
    assert "time_s,live_V,frozen_V" in text
    assert ("vuv_pd", "save_snapshot", "done") in actions(window)
    t.stop_btn.click()
    qtbot.waitUntil(lambda: t.session.state == STOPPED, timeout=10000)


def test_snapshot_scope_style_averaging(window, qtbot, monkeypatch):
    monkeypatch.setattr(VirtualDigitizer, "TRIGGER_RATE_HZ", 25.0)  # the real trigger rate
    t: ScopeTab = tab(window, "vuv_pd")
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.view is not None and t.view.averager.count > 0, timeout=10000)
    v = t.view
    assert v.n_avg == 128 and v._lbl_navg.text() == "128"  # from refresh_trigger_cnt = 100
    # redrawn with every new waveform: ~25 fps at 25 Hz triggers (user: 10-25 fps)
    f0, t0 = v.frames, time.monotonic()
    qtbot.wait(2000)
    fps = (v.frames - f0) / (time.monotonic() - t0)
    assert fps > 15, fps
    # statistics box: offset, area, std, N, stderr
    html = v._stats_box.textItem.toHtml()
    for key in ("Offset", "Area", "Std", "N", "Stderr", "mV", "nV·s"):
        assert key in html
    # arrows: 128 -> 256 ... -> 1024 -> ∞ (and back); a change restarts the average
    v._n_up.click()
    assert v.n_avg == 256 and v.averager.count <= 1
    for _ in range(3):
        v._n_up.click()
    assert v._lbl_navg.text() == "∞" and not v._n_up.isEnabled()
    qtbot.waitUntil(lambda: v.averager.count >= 3, timeout=5000)
    assert "(∞)" in v._stats_box.textItem.toHtml()
    v.set_n(4)
    qtbot.waitUntil(lambda: v.averager.count == 4, timeout=5000)
    qtbot.wait(300)
    assert v.averager.count == 4  # never more than N
    v._clear_btn.click()
    assert v.averager.count <= 1
    for _ in range(12):
        v._n_down.click()
    assert v.n_avg == 1 and not v._n_down.isEnabled()
    t.stop_btn.click()
    qtbot.waitUntil(lambda: t.session.state == STOPPED, timeout=10000)
    t.start_btn.click()  # the chosen N is kept for the next run
    qtbot.waitUntil(lambda: t.view is not None, timeout=10000)
    assert t.view.n_avg == 1


def test_camera_tab_start_page_open_capture_close(window, qtbot, tmp_path):
    t: CameraTab = tab(window, "camera")
    assert t.stack.currentIndex() == 0 and t.window is None  # start page, camera not open
    assert "not open" in t.stack.widget(0).findChildren(type(t.start_status))[1].text()

    t.start_btn.click()
    qtbot.waitUntil(lambda: t.window is not None, timeout=10000)
    assert t.stack.currentWidget() is t.open_page
    w = t.window
    qtbot.waitUntil(lambda: w._live_view.last_frame is not None, timeout=10000)
    # the old camera GUI, unchanged: its controls are there
    for name in ("_config_combo", "_exposure_spin", "_analog_gain_slider", "_autogain_btn",
                 "_free_radio", "_capture_btn", "_run_btn"):
        assert hasattr(w, name), name
    assert w._config_combo.findText("default.toml") >= 0  # config/camera/*.toml listed
    # the sidebar is wide enough for its content (it was cut off on the right, 2026-11-18)
    from PySide6.QtWidgets import QScrollArea
    scroll = w.findChild(QScrollArea)
    assert scroll.viewport().width() >= scroll.widget().minimumSizeHint().width()

    w._capture_btn.click()
    qtbot.waitUntil(lambda: ("camera", "record", "done") in actions(window), timeout=10000)
    day = tmp_path / "data" / "camera" / time.strftime("%Y-%m-%d")
    assert len(list(day.glob("*.bmp"))) == 1 and len(list(day.glob("*_config.toml"))) == 1

    t.close_btn.click()
    assert t.window is None and t.stack.currentIndex() == 0
    acts = [a for a in actions(window) if a[0] == "camera"]
    assert [a[1] for a in acts] == ["open", "record", "close"]


def test_close_window_stops_everything(window, qtbot):
    mon, cam = tab(window, "scope_monitor"), tab(window, "camera")
    mon.start_btn.click()
    cam.start_btn.click()
    qtbot.waitUntil(lambda: mon.session.state == RUNNING and cam.window is not None,
                    timeout=10000)
    assert mon.running
    window.close()  # "still running" question answered Yes by the fixture
    assert mon.session.state == STOPPED and cam.window is None
    assert all(not d.is_alive() for d in mon.session.digitizers.values())


def test_scope_start_failure_returns_to_start_page(window, qtbot, monkeypatch):
    def fail(self, config):
        raise RuntimeError("PicoScope 2204A 12017/0366 not found")

    monkeypatch.setattr(VirtualDigitizer, "_init_hardware", fail)
    t: ScopeTab = tab(window, "vuv_pd")
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.session.state == STOPPED and t.stack.currentIndex() == 0,
                    timeout=10000)
    assert t.start_error.isVisibleTo(t) and "not found" in t.start_error.text()
    assert ("vuv_pd", "acquire", "failed") in actions(window)


def test_scope_config_dropdown(window, qtbot):
    t: ScopeTab = tab(window, "vuv_pd")
    names = [t.config_combo.itemData(i) for i in range(t.config_combo.count())]
    assert "H2PD_261103.toml" in names and "monitor_2026A.toml" not in names  # snapshot only
    assert t.config_combo.currentData() == "H2PD_261103.toml"  # default from devices.toml
    t.config_combo.setCurrentIndex(names.index("LaserRoomPD.toml"))
    assert "12017/0137" in t.config_info.text()  # description follows the choice
    t.start_btn.click()
    qtbot.waitUntil(lambda: t.session.state == RUNNING, timeout=10000)
    assert not t.config_combo.isEnabled()  # no change while running
    assert t.view.device == "LaserRoomPD"
    start = [e for e in read_oplog(window.oplog.today_path()) if e["action"] == "start"]
    assert start[-1]["args"]["config"] == "LaserRoomPD.toml"
    t.stop_btn.click()
    qtbot.waitUntil(lambda: t.stack.currentIndex() == 0, timeout=10000)
    assert t.config_combo.isEnabled() and t.config_combo.currentData() == "LaserRoomPD.toml"
    mon = tab(window, "scope_monitor")
    mon_names = [mon.config_combo.itemData(i) for i in range(mon.config_combo.count())]
    assert mon_names == ["H2PD_monitor_261103.toml", "monitor_2026A.toml"]
