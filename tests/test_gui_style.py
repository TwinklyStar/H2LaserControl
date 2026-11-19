"""Program-wide GUI style (gui/style.py). Needs pytest-qt."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QSlider

pytest.importorskip("pytestqt")


@pytest.mark.parametrize("dark", [False, True])
def test_slider_click_jumps_to_clicked_point(qtbot, themes, dark):
    """Camera gain sliders (user 2026-11-19): a click on the bar sets the value there, also with
    the program's style sheet (a style sheet wraps the style)."""
    from h2lasercontrol.gui.style import AppStyle

    themes(dark)  # style sheet + palette as in the program
    style = AppStyle()
    s = QSlider(Qt.Orientation.Horizontal)
    s.setStyle(style)
    s.setRange(100, 1250)  # analog gain 1.00 ... 12.50
    s.setValue(100)
    s.resize(400, 30)
    qtbot.addWidget(s)
    s.show()
    qtbot.waitExposed(s)
    qtbot.mouseClick(s, Qt.MouseButton.LeftButton, pos=QPoint(300, 15))
    expected = 100 + 0.75 * (1250 - 100)
    assert abs(s.value() - expected) < 0.05 * (1250 - 100)  # not one page step (+10)


@pytest.mark.parametrize("dark", [False, True])
def test_combo_box_is_macos_popup_button(qtbot, themes, dark):
    """Drop-down lists (user 2026-11-19, macOS screenshots): up/down chevron image exists,
    and the open list paints items with the macOS delegate (tick, blue bar)."""
    from pathlib import Path

    from PySide6.QtWidgets import QComboBox

    from h2lasercontrol.gui.style import AppStyle, C, ComboItemDelegate, _updown_icon

    themes(dark)
    cb = QComboBox()
    cb.setStyle(AppStyle())
    cb.addItems(["Standard", "90°"])
    qtbot.addWidget(cb)
    cb.show()
    qtbot.waitExposed(cb)
    assert isinstance(cb.itemDelegate(), ComboItemDelegate)
    assert Path(_updown_icon(C.TEXT)).read_text(encoding="utf-8").startswith("<svg")
    cb.showPopup()
    assert cb.view().isVisible()
    cb.hidePopup()
