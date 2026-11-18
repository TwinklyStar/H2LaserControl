"""Colours, fonts and the application style sheet (one place, so the look stays consistent).

Light and dark theme (user 2026-11-19): the program follows the Windows setting (Settings →
Personalization → Colors → "Choose your mode") and switches while it runs. The dark colours
are the old H2LaserDAQ monitor's (Catppuccin Mocha). Code reads colours from `C` at the moment
it draws (`C.GREEN`, not a copied constant), and widgets that draw with fixed colours connect
to `theme.changed` to redraw.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap


@dataclass
class Colors:
    # status colours
    GREEN: str  # normal / safe (retracted, connected, running)
    ORANGE: str  # attention (inserted = beam blocked, partly inserted, paused)
    BLUE: str  # moving / busy
    RED: str  # error / stop
    GREY: str  # disconnected / unknown / secondary text
    # widgets
    ON_RED: str  # text on the red STOP button
    STOP_OFF_BG: str  # disabled STOP button
    STOP_OFF_FG: str
    BORDER: str  # group boxes
    SEP: str  # separator lines
    ERROR_BG: str  # plain-language error line
    ERROR_BORDER: str
    SIM_BG: str  # SIMULATION banner
    SIM_FG: str
    SIM_BORDER: str
    # scope plots
    PLOT_BG: str
    PLOT_FG: str  # axes, tick labels, statistics text
    SURF: str  # panel titles, statistics labels, status row
    GRID: str  # separators in the plot views
    MATH: str  # Freeze "Math" value
    STATS_FILL: tuple[int, int, int, int]  # statistics box background (RGBA)
    CH: tuple[str, ...]  # channel colours, cycled


LIGHT = Colors(
    GREEN="#2e7d32", ORANGE="#e65100", BLUE="#1565c0", RED="#c62828", GREY="#757575",
    ON_RED="#ffffff", STOP_OFF_BG="#e0b4b4", STOP_OFF_FG="#f5f5f5",
    BORDER="#c8c8c8", SEP="#dddddd", ERROR_BG="#fdecea", ERROR_BORDER="#f5c2c0",
    SIM_BG="#fff3cd", SIM_FG="#7a5b00", SIM_BORDER="#e6d28f",
    PLOT_BG="#ffffff", PLOT_FG="#212121", SURF="#e6e6e6", GRID="#c8c8c8", MATH="#8d6e00",
    STATS_FILL=(255, 255, 255, 225),
    CH=("#1565c0", "#2e7d32", "#e65100", "#c62828", "#6a1b9a", "#00838f", "#6d4c41", "#ad1457"),
)

# Catppuccin Mocha, as in the old H2LaserDAQ monitor windows
_BASE, _MANTLE, _CRUST = "#1e1e2e", "#181825", "#11111b"
_SURFACE0, _SURFACE1, _SURFACE2 = "#313244", "#45475a", "#585b70"
_TEXT, _SUBTEXT0, _OVERLAY1 = "#cdd6f4", "#a6adc8", "#7f849c"

DARK = Colors(
    GREEN="#a6e3a1", ORANGE="#fab387", BLUE="#89b4fa", RED="#f38ba8", GREY="#9399b2",
    ON_RED=_BASE, STOP_OFF_BG="#5b3f4f", STOP_OFF_FG="#9399b2",
    BORDER=_SURFACE1, SEP=_SURFACE1, ERROR_BG="#3a2433", ERROR_BORDER="#6e3a50",
    SIM_BG="#3a3424", SIM_FG="#f9e2af", SIM_BORDER="#6b5d36",
    PLOT_BG=_BASE, PLOT_FG=_TEXT, SURF=_SURFACE0, GRID=_SURFACE1, MATH="#f9e2af",
    STATS_FILL=(30, 30, 46, 225),
    CH=("#a6e3a1", "#89b4fa", "#fab387", "#f38ba8", "#cba6f7", "#89dceb", "#f9e2af", "#94e2d5"),
)

C = replace(LIGHT)  # the current colours (changed in place by apply_theme)

TAB_STATES = {"ok": "GREEN", "busy": "BLUE", "off": "GREY", "error": "RED"}


def state_color(state: str) -> str:
    """Colour of a tab status ('ok', 'busy', 'off', 'error') in the current theme."""
    return getattr(C, TAB_STATES[state])


class _Theme(QObject):
    changed = Signal()  # after the colours, palette and style sheet were switched

    def __init__(self) -> None:
        super().__init__()
        self.dark = False


theme = _Theme()

# Our own widget classes. The general rules below (font size, group boxes, button padding) are
# limited to these containers, so they do NOT reach the embedded camera window (laserdaq
# MainWindow), which must look exactly like the old camera program (F8b). A type selector also
# matches subclasses (DevicePanel -> HitMvPanel, ...). Role-based rules are safe everywhere.
# The camera window does follow the light / dark palette (whole program, user 2026-11-19).
OWN = ("DevicePanel", "ScopeTab", "ScopeStartPage", "CameraStartPage", "CameraHeader",
       "LogPanel", "TopBar")


def _scoped(selector: str) -> str:
    """'QPushButton' -> 'DevicePanel QPushButton, ScopeTab QPushButton, ...'."""
    return ", ".join(f"{c} {selector}" for c in OWN)


def style_sheet(c: Colors | None = None) -> str:
    c = c or C
    return f"""
{", ".join(OWN)}, {_scoped("QWidget")}, QTabBar {{ font-size: 10.5pt; }}
QTabBar::tab {{ padding: 8px 18px; min-width: 150px; }}
QTabBar::tab:selected {{ font-weight: bold; }}
QTabWidget#groupTabs > QTabBar::tab {{ font-size: 12pt; padding: 10px 28px; min-width: 120px; }}
{_scoped("QGroupBox")} {{ font-weight: bold; border: 1px solid {c.BORDER}; border-radius: 6px;
             margin-top: 14px; padding: 12px 10px 10px 10px; }}
{_scoped("QGroupBox::title")} {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
{_scoped("QPushButton")} {{ padding: 6px 14px; }}
QPushButton[role="primary"] {{ font-size: 12pt; font-weight: bold; padding: 10px 22px; }}
QPushButton[role="stop"] {{ background: {c.RED}; color: {c.ON_RED}; font-weight: bold;
                            padding: 8px 22px; border-radius: 4px; }}
QPushButton[role="stop"]:disabled {{ background: {c.STOP_OFF_BG}; color: {c.STOP_OFF_FG}; }}
QFrame[role="sep"] {{ color: {c.SEP}; }}
QLabel[role="big"] {{ font-size: 20pt; font-weight: bold; }}
QLabel[role="muted"] {{ color: {c.GREY}; }}
QLabel[role="alarm"] {{ color: {c.RED}; font-weight: bold; }}
QLabel[role="error"] {{ background: {c.ERROR_BG}; color: {c.RED}; border: 1px solid {c.ERROR_BORDER};
                        border-radius: 4px; padding: 6px 10px; }}
QLabel[role="sim"] {{ background: {c.SIM_BG}; color: {c.SIM_FG}; font-weight: bold; padding: 6px;
                      border-bottom: 1px solid {c.SIM_BORDER}; }}
"""


def dark_palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: _BASE, QPalette.ColorRole.WindowText: _TEXT,
        QPalette.ColorRole.Base: _MANTLE, QPalette.ColorRole.AlternateBase: _SURFACE0,
        QPalette.ColorRole.Text: _TEXT, QPalette.ColorRole.Button: _SURFACE0,
        QPalette.ColorRole.ButtonText: _TEXT, QPalette.ColorRole.BrightText: "#f38ba8",
        QPalette.ColorRole.Highlight: "#89b4fa", QPalette.ColorRole.HighlightedText: _BASE,
        QPalette.ColorRole.ToolTipBase: _SURFACE0, QPalette.ColorRole.ToolTipText: _TEXT,
        QPalette.ColorRole.Link: "#89b4fa", QPalette.ColorRole.LinkVisited: "#cba6f7",
        QPalette.ColorRole.PlaceholderText: _OVERLAY1,
        # Fusion draws bevels and frames from these
        QPalette.ColorRole.Light: _SURFACE2, QPalette.ColorRole.Midlight: _SURFACE1,
        QPalette.ColorRole.Mid: _SURFACE0, QPalette.ColorRole.Dark: _CRUST,
        QPalette.ColorRole.Shadow: "#0a0a12",
    }
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    disabled = QPalette.ColorGroup.Disabled
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        p.setColor(disabled, role, QColor("#6c7086"))
    p.setColor(disabled, QPalette.ColorRole.Button, QColor("#26263a"))
    p.setColor(disabled, QPalette.ColorRole.Base, QColor(_BASE))
    p.setColor(disabled, QPalette.ColorRole.Highlight, QColor(_SURFACE1))
    p.setColor(disabled, QPalette.ColorRole.HighlightedText, QColor(_SUBTEXT0))
    return p


def system_is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply_theme(app, dark: bool | None = None) -> None:
    """Switch colours, palette and style sheet; dark=None follows Windows."""
    dark = system_is_dark() if dark is None else dark
    src = DARK if dark else LIGHT
    for f in fields(Colors):
        setattr(C, f.name, getattr(src, f.name))
    theme.dark = dark
    app.setPalette(dark_palette() if dark else app.style().standardPalette())
    app.setStyleSheet(style_sheet())
    theme.changed.emit()


def follow_system(app) -> None:
    """Apply the Windows light/dark setting now and whenever it is changed."""
    apply_theme(app)
    app.styleHints().colorSchemeChanged.connect(lambda *_: apply_theme(app))


def dot_icon(color: str, size: int = 12) -> QIcon:
    """Small filled circle, used as the tab status indicator."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pm)


def set_role(widget, role: str) -> None:
    """Apply a style-sheet role (see style_sheet) and refresh the style."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
