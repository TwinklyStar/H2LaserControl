"""GUI tests on simulated devices (no hardware). Needs pytest-qt."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from h2lasercontrol.config import DEFAULT_CONFIG, load_config
from h2lasercontrol.gui.main_window import MainWindow
from h2lasercontrol.oplog import OpLog, read_oplog
from h2lasercontrol.services import device_service
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
    # answer "Yes" to confirmation dialogs
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    oplog = OpLog(tmp_path / "logs", user="tester")
    settings = QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)
    w = MainWindow(load_config(DEFAULT_CONFIG), oplog, sim=True, settings=settings,
                   state_dir=str(tmp_path), daq_base_dir=str(tmp_path))
    qtbot.addWidget(w)
    # shut the device threads down even if the test fails (otherwise the run hangs at exit)
    request.addfinalizer(lambda: [s.shutdown() for s in w.services])
    request.addfinalizer(w.shutdown_daq)
    w.start()
    for p in w.panels:
        qtbot.waitUntil(lambda p=p: bool(p.connected and p.state), timeout=5000)
    return w


def panel(w, key):
    return next(p for p in w.panels if p.cfg.key == key)


def test_group_tabs_with_one_sub_tab_per_device(window):
    def texts(tw):
        return [tw.tabText(i) for i in range(tw.count())]

    assert texts(window.tabs) == ["Control", "DAQ"]  # user 2026-11-19
    assert texts(window.sub_tabs["Control"]) == ["VUV feedthroughs", "Rotation mount",
                                                 "Flip mounts", "Delay generator"]
    assert texts(window.sub_tabs["DAQ"]) == ["Scope monitor", "VUV PD snapshot", "Camera"]


def test_initial_window_is_4_to_3(window):
    w, h = window.width(), window.height()
    assert abs(w / h - 4 / 3) < 0.01  # user 2026-11-19


def test_dark_theme_switch_while_connected(window, themes):
    from PySide6.QtGui import QPalette

    from h2lasercontrol.gui.style import DARK, LIGHT, C, theme

    hit = panel(window, "hitmv")
    assert LIGHT.GREEN in hit.status_label.text()  # "● Connected" in the light green
    themes(True)
    assert theme.dark and C.GREEN == DARK.GREEN
    assert window.palette().color(QPalette.ColorRole.Window).name() == DARK.WINDOW
    assert DARK.GREEN in hit.status_label.text()  # redrawn without reconnecting
    icon = window.tabs.tabIcon(0).pixmap(12, 12).toImage()
    assert icon.pixelColor(6, 6).name() == DARK.GREEN  # Control: all connected
    themes(False)
    assert LIGHT.GREEN in hit.status_label.text()
    assert window.palette().color(QPalette.ColorRole.Window).name() == LIGHT.WINDOW


def test_group_tab_shows_error_of_hidden_device(window):
    from h2lasercontrol.gui.style import C

    window.tabs.setCurrentIndex(1)  # DAQ shown, Control hidden
    window._set_sub_state("Control", 1, "error")
    assert window._sub_states["Control"][1] == "error"
    icon = window.tabs.tabIcon(0).pixmap(12, 12).toImage()
    assert icon.pixelColor(6, 6).name() == C.RED  # red dot on the Control tab
    window._set_sub_state("Control", 1, "ok")
    icon = window.tabs.tabIcon(0).pixmap(12, 12).toImage()
    assert icon.pixelColor(6, 6).name() != C.RED


def test_flip_mount_retract_and_insert(window, qtbot):
    flip = panel(window, "flipmounts")
    assert list(flip.cards) == ["flip1", "flip2"]  # 355 nm and 820 nm blockers on one tab
    assert flip.cards["flip2"].state_label.text() == "INSERTED"
    card = flip.cards["flip1"]
    assert card.state_label.text() == "INSERTED"  # real unit's state on 2026-11-17
    assert card.retract_btn.isEnabled() and not card.insert_btn.isEnabled()
    assert flip.stop_btn.isHidden()  # a 0.5 s flip cannot be stopped
    card.retract_btn.click()
    qtbot.waitUntil(lambda: card.state_label.text() == "RETRACTED" and not flip.busy,
                    timeout=5000)
    assert card.insert_btn.isEnabled() and not card.retract_btn.isEnabled()
    card.insert_btn.click()
    qtbot.waitUntil(lambda: card.state_label.text() == "INSERTED" and not flip.busy,
                    timeout=5000)
    done = [(e["action"], e["args"]) for e in read_oplog(window.oplog.today_path())
            if e["event"] == "done" and e["device"] == "flipmounts"]
    assert ("retract", {"unit": "flip1"}) in done and ("insert", {"unit": "flip1"}) in done


def test_positions_lost_locks_both_feedthroughs(window, qtbot):
    hit = panel(window, "hitmv")
    hit.state = {**hit.state, "positions_lost": True,
                 "axes": {n: {**i, "position": 0} for n, i in hit.state["axes"].items()}}
    hit.update_view()
    for card in hit.cards.values():
        assert card.state_label.text() == "POSITION UNKNOWN"
        assert not card.insert_btn.isEnabled() and not card.retract_btn.isEnabled()
        assert "HIT Sample" in card.hint_label.text()


def test_insert_and_retract_mirror(window, qtbot):
    hit = panel(window, "hitmv")
    card = hit.cards[1]
    assert card.state_label.text() == "RETRACTED"
    assert card.insert_btn.isEnabled() and not card.retract_btn.isEnabled()
    card.insert_btn.click()
    qtbot.waitUntil(lambda: card.state_label.text() == "INSERTED", timeout=10000)
    assert hit.cards[0].state_label.text() == "RETRACTED"  # photodiode untouched
    assert card.retract_btn.isEnabled() and not card.insert_btn.isEnabled()
    card.retract_btn.click()
    qtbot.waitUntil(lambda: card.state_label.text() == "RETRACTED", timeout=10000)
    entries = read_oplog(window.oplog.today_path())
    done = [(e["action"], e["args"]) for e in entries if e["event"] == "done"]
    assert ("insert", {"axis": 1}) in done and ("retract", {"axis": 1}) in done
    assert all(e["user"] == "tester" for e in entries)


def test_insert_needs_no_confirmation(window, qtbot, monkeypatch):
    def no_dialog(self):
        raise AssertionError("Insert must not ask for confirmation (user, 2026-11-18)")

    monkeypatch.setattr(QMessageBox, "exec", no_dialog)
    hit = panel(window, "hitmv")
    hit.cards[0].insert_btn.click()
    qtbot.waitUntil(lambda: hit.cards[0].state_label.text() == "INSERTED" and not hit.busy,
                    timeout=10000)


def test_interlock_locks_other_axis(window, qtbot):
    hit = panel(window, "hitmv")
    pd, mirror = hit.cards[0], hit.cards[1]
    assert pd.insert_btn.isEnabled() and mirror.insert_btn.isEnabled()
    mirror.insert_btn.click()
    # locked already while the mirror is moving, and while it is inserted
    qtbot.waitUntil(lambda: hit.busy, timeout=5000)
    assert not pd.insert_btn.isEnabled()
    qtbot.waitUntil(lambda: mirror.state_label.text() == "INSERTED", timeout=10000)
    assert not pd.insert_btn.isEnabled() and not pd.retract_btn.isEnabled()
    assert "Locked" in pd.hint_label.text() and "VUV mirror" in pd.hint_label.text()
    assert mirror.retract_btn.isEnabled()  # getting out is always allowed
    mirror.retract_btn.click()
    qtbot.waitUntil(lambda: mirror.state_label.text() == "RETRACTED" and not hit.busy,
                    timeout=10000)
    assert pd.insert_btn.isEnabled() and "Locked" not in pd.hint_label.text()


def test_stop_button_stops_move(window, qtbot, monkeypatch):
    monkeypatch.setattr(device_service, "make_sim_transport",
                        lambda cfg: FakeTransport(HitMvSim(busy_polls=10**6)))
    hit = panel(window, "hitmv")
    # reconnect so the slow simulator is used
    hit.connect_btn.click()
    qtbot.waitUntil(lambda: not hit.connected, timeout=5000)
    hit.connect_btn.click()
    qtbot.waitUntil(lambda: bool(hit.connected and hit.state), timeout=5000)
    hit.cards[0].insert_btn.click()
    qtbot.waitUntil(lambda: hit.busy and hit.stop_btn.isEnabled(), timeout=5000)
    hit.stop_btn.click()
    qtbot.waitUntil(lambda: not hit.busy, timeout=10000)
    assert "stopped (STOP pressed)" in hit.error_label.text()
    assert hit.cards[0].state_label.text() == "PARTLY INSERTED"
    # stopped halfway: both Insert and Retract can be chosen (user, 2026-11-17)
    assert hit.cards[0].retract_btn.isEnabled()
    assert hit.cards[0].insert_btn.isEnabled()
    assert not hit.cards[1].insert_btn.isEnabled()  # interlock: photodiode partly in


def test_rotation_mount_go_to_angle(window, qtbot):
    ell = panel(window, "ell14")
    ell.abs_spin.setValue(45.0)
    ell.run("move_abs", deg=45.0)
    qtbot.waitUntil(lambda: ell.angle_label.text().startswith("45.0"), timeout=5000)
    rows = [window.log_panel.table.item(r, 3).text() for r in range(window.log_panel.table.rowCount())]
    assert "move abs" in rows


def test_energy_section(window, qtbot, tmp_path):
    ell = panel(window, "ell14")
    assert "not saved" in ell.energy_label.text()
    assert not any(w.isEnabled() for w in ell.energy_controls)  # nothing saved yet
    ell._save_max()  # confirm dialog answered "Yes" by the fixture
    qtbot.waitUntil(lambda: "of max" in ell.energy_label.text(), timeout=5000)
    assert "100 %" in ell.energy_label.text()
    assert all(w.isEnabled() for w in ell.energy_controls)
    assert (tmp_path / "saved_angles.json").exists()  # test folder, not config/
    ell.pct_spin.setValue(50)
    ell.run("set_energy", percent=50.0)
    qtbot.waitUntil(lambda: "50 %" in ell.energy_label.text(), timeout=5000)
    ell.run("go_to_min_energy")
    qtbot.waitUntil(lambda: ell.energy_label.text().startswith("Now ≈ 0 %"), timeout=5000)


def test_rotation_mount_refuses_bad_offset(window, qtbot):
    ell = panel(window, "ell14")
    ell.run("set_home_offset", deg=0.5)  # below the 0.7 deg minimum
    qtbot.waitUntil(lambda: ell.has_error, timeout=5000)  # (window not shown: no isVisible)
    assert "home offset" in ell.error_label.text()


def test_delay_generator_steps_and_limits(window, qtbot):
    """User 2026-11-20: only C is adjusted, in µs from nominal, steps 0.1 µs, −1.5 … +3 µs."""
    dg = panel(window, "dg645")
    assert dg.offset_label.text().startswith("+0.000 µs")
    assert "36.580 467 ms" in dg.abs_label.text()
    assert dg.rows["E"][2].text() == "36.999 100 ms"  # other groups' channels shown, read only
    assert dg.stop_btn.isHidden()
    dg.plus_btn.click()
    qtbot.waitUntil(lambda: dg.offset_label.text().startswith("+0.100 µs") and not dg.busy,
                    timeout=5000)
    assert "Last change: +0.000 µs → +0.100 µs by tester" in dg.last_label.text()
    dg.spin.setValue(-1.5)
    dg.set_btn.click()
    qtbot.waitUntil(lambda: dg.offset_label.text().startswith("-1.500 µs") and not dg.busy,
                    timeout=5000)
    assert not dg.minus_btn.isEnabled() and dg.plus_btn.isEnabled()  # at the lower limit
    assert dg.spin.minimum() == -1.5 and dg.spin.maximum() == 3.0
    dg.nominal_btn.click()
    qtbot.waitUntil(lambda: dg.offset_label.text().startswith("+0.000 µs") and not dg.busy,
                    timeout=5000)
    sent = [e["exchanges"] for e in read_oplog(window.oplog.today_path())
            if e["device"] == "dg645" and e["event"] == "done"
            and e["action"] in ("step", "set_offset")]
    writes = [tx for ex in sent for tx, rx in ex if "?" not in tx and tx != "LCAL\n"]
    assert writes == ["DLAY 4,0,0.036580567000\n", "DLAY 4,0,0.036578967000\n",
                      "DLAY 4,0,0.036580467000\n"]  # channel C only


def test_delay_generator_maintenance_nominal(window, qtbot):
    """Maintenance (user 2026-11-20): change the nominal value of C; nothing sent to the DG645."""
    dg = panel(window, "dg645")
    assert dg.maint.isHidden()
    dg.maint_toggle.click()
    assert not dg.maint.isHidden()
    assert "from the configuration file" in dg.nominal_label.text()
    dg.plus_btn.click()
    qtbot.waitUntil(lambda: dg.offset_label.text().startswith("+0.100 µs") and not dg.busy,
                    timeout=5000)
    dg.use_current_btn.click()  # confirmation answered "Yes" by the fixture
    qtbot.waitUntil(lambda: dg.offset_label.text().startswith("+0.000 µs") and not dg.busy,
                    timeout=5000)
    assert "36.580 567 ms" in dg.nominal_label.text() and "by tester" in dg.nominal_label.text()
    assert "T0 + 36.580 567 ms" in dg.limits_label.text()
    assert dg.nominal_spin.value() == pytest.approx(36.580567)
