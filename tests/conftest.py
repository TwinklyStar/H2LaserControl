"""Shared fixtures."""

import pytest


@pytest.fixture
def themes(qapp):
    """`themes(dark)` switches the light/dark theme for one test. Afterwards the application is
    restored exactly (no style sheet, default palette, light colours), as the other tests expect:
    the theme is global state."""
    from h2lasercontrol.gui.style import apply_theme

    sheet, palette = qapp.styleSheet(), qapp.palette()
    yield lambda dark: apply_theme(qapp, dark=dark)
    apply_theme(qapp, dark=False)
    qapp.setStyleSheet(sheet)
    qapp.setPalette(palette)
