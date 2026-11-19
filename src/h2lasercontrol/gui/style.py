"""Colours, fonts and the application style sheet (one place, so the look stays consistent).

Light and dark theme (user 2026-11-19): the program follows the Windows setting (Settings →
Personalization → Colors → "Choose your mode") and switches while it runs. The dark colours
are neutral greys with the macOS dark-mode system colours (user 2026-11-19: not the old
H2LaserDAQ purple-blue). Code reads colours from `C` at the moment
it draws (`C.GREEN`, not a copied constant), and widgets that draw with fixed colours connect
to `theme.changed` to redraw.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleFactory


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
    # surfaces, macOS System Settings pattern (user 2026-11-19, screenshots): light = white
    # window, boxes and buttons a little darker; dark = dark window, controls lighter
    WINDOW: str  # window background
    BOX: str  # group box fill ("information box")
    FIELD: str  # text fields, lists, tables
    CONTROL: str  # button fill
    CONTROL_HOVER: str
    CONTROL_DOWN: str
    TEXT: str
    TEXT2: str  # secondary text
    TEXT_OFF: str  # disabled text
    ACCENT: str  # selection, links, primary buttons
    ACCENT_DOWN: str


# Apple light mode (user 2026-11-19). Status colours (text and dots) = Apple's "increased
# contrast" system colours: the standard ones (green #34c759, orange #ff9500) are only ~2:1 on
# white, too pale for the big state words. Exception: orange. Apple's high-contrast orange
# (#c93400) looks red next to the error red, so "INSERTED" (attention) could be read as an
# error; #c45c00 stays clearly orange and readable. Plot curves = the standard system colours.
LIGHT = Colors(
    GREEN="#248a3d", ORANGE="#c45c00", BLUE="#0040dd", RED="#d70015", GREY="#6e6e73",
    ON_RED="#ffffff", STOP_OFF_BG="#f0b3b8", STOP_OFF_FG="#fbeff0",
    BORDER="#e3e3e8", SEP="#e5e5ea", ERROR_BG="#fdecec", ERROR_BORDER="#f6c4c6",
    SIM_BG="#fff4d1", SIM_FG="#7a5600", SIM_BORDER="#ecd58f",
    PLOT_BG="#ffffff", PLOT_FG="#1d1d1f", SURF="#ececf0", GRID="#d1d1d6", MATH="#a05a00",
    STATS_FILL=(255, 255, 255, 225),
    # blue, green, orange, red, purple, cyan, brown, pink (same order as DARK)
    CH=("#007aff", "#34c759", "#ff9500", "#ff3b30", "#af52de", "#32ade6", "#a2845e", "#ff2d55"),
    WINDOW="#ffffff", BOX="#f5f5f7", FIELD="#ffffff",
    CONTROL="#e5e5ea", CONTROL_HOVER="#dadadf", CONTROL_DOWN="#cdcdd2",
    TEXT="#1d1d1f", TEXT2="#6e6e73", TEXT_OFF="#aeaeb2",
    ACCENT="#007aff", ACCENT_DOWN="#0062cc",
)

# macOS dark mode: neutral greys + Apple's dark-mode system colours. Pattern of the macOS
# dark settings window: dark background, controls (buttons, pop-ups) clearly lighter.
DARK = Colors(
    GREEN="#30d158", ORANGE="#ff9f0a", BLUE="#0a84ff", RED="#ff453a", GREY="#98989d",
    ON_RED="#ffffff", STOP_OFF_BG="#4a2e2c", STOP_OFF_FG="#6e6e73",
    BORDER="#3a3a3a", SEP="#3d3d3d", ERROR_BG="#3b2220", ERROR_BORDER="#6b2f2a",
    SIM_BG="#3a3320", SIM_FG="#ffd60a", SIM_BORDER="#6b5a1e",
    PLOT_BG="#1e1e1e", PLOT_FG="#e5e5e5", SURF="#323232", GRID="#464646", MATH="#ffd60a",
    STATS_FILL=(30, 30, 30, 225),
    # same order as LIGHT: blue, green, orange, red, purple, cyan, brown, pink
    CH=("#0a84ff", "#30d158", "#ff9f0a", "#ff453a", "#bf5af2", "#64d2ff", "#ac8e68", "#ff375f"),
    WINDOW="#262626", BOX="#2e2e2e", FIELD="#1e1e1e",
    CONTROL="#58585a", CONTROL_HOVER="#646466", CONTROL_DOWN="#727274",
    TEXT="#e5e5e5", TEXT2="#98989d", TEXT_OFF="#6e6e73",
    ACCENT="#0a84ff", ACCENT_DOWN="#0070e0",
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

# Our own widget classes. Font size and padding rules are limited to these containers, so the
# embedded camera window (laserdaq MainWindow) keeps its old layout and sizes (F8b). Colours,
# button and box shapes apply everywhere, the camera window included (user 2026-11-19: one
# button style in the whole program). A type selector also matches subclasses
# (DevicePanel -> HitMvPanel, ...).
OWN = ("DevicePanel", "ScopeTab", "ScopeStartPage", "CameraStartPage", "CameraHeader",
       "LogPanel", "TopBar")


def _scoped(selector: str) -> str:
    """'QPushButton' -> 'DevicePanel QPushButton, ScopeTab QPushButton, ...'."""
    return ", ".join(f"{c} {selector}" for c in OWN)


def style_sheet(c: Colors | None = None) -> str:
    c = c or C
    return f"""
{", ".join(OWN)}, {_scoped("QWidget")}, QTabBar {{ font-size: 10.5pt; }}
QTabBar::tab {{ padding: 8px 18px; min-width: 150px; margin: 3px 2px; border: none;
                border-radius: 6px; background: {c.CONTROL}; color: {c.TEXT}; }}
QTabBar::tab:hover {{ background: {c.CONTROL_HOVER}; }}
QTabBar::tab:selected {{ font-weight: bold; background: {c.ACCENT}; color: #ffffff; }}
QTabWidget#groupTabs > QTabBar::tab {{ font-size: 12pt; padding: 10px 28px; min-width: 120px; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {c.SEP}; }}
QGroupBox {{ background: {c.BOX}; border: 1px solid {c.BORDER}; border-radius: 8px;
             margin-top: 14px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
{_scoped("QGroupBox")} {{ font-weight: bold; padding: 12px 10px 10px 10px; }}
QPushButton, QToolButton {{ padding: 4px 10px; background: {c.CONTROL}; color: {c.TEXT};
                            border: none; border-radius: 6px; }}
QPushButton:hover, QToolButton:hover {{ background: {c.CONTROL_HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {c.CONTROL_DOWN}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {c.TEXT_OFF}; }}
QPushButton:flat {{ background: transparent; }}
{_scoped("QPushButton")} {{ padding: 6px 14px; }}
QPushButton[role="primary"] {{ font-size: 12pt; font-weight: bold; padding: 10px 22px; }}
QPushButton[role="stop"] {{ background: {c.RED}; color: {c.ON_RED}; font-weight: bold;
                            padding: 8px 22px; border-radius: 4px; }}
QPushButton[role="stop"]:hover {{ background: {c.RED}; }}
QPushButton[role="stop"]:pressed {{ background: {c.RED}; }}
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


def make_palette(c: Colors, dark: bool) -> QPalette:
    """Palette for the whole program (also the camera window, combo boxes, spin boxes, tabs):
    window, fields and controls as in macOS System Settings."""
    ctl = QColor(c.CONTROL)
    # Fusion draws bevels and frames from Light ... Shadow
    light, midlight = (ctl.lighter(118), ctl.lighter(108)) if dark else ("#ffffff", "#f0f0f3")
    mid, dark_ = (ctl.darker(160), ctl.darker(300)) if dark else ("#c7c7cc", "#a1a1a6")
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.WINDOW, QPalette.ColorRole.WindowText: c.TEXT,
        QPalette.ColorRole.Base: c.FIELD,
        QPalette.ColorRole.AlternateBase: "#232323" if dark else "#f5f5f7",
        QPalette.ColorRole.Text: c.TEXT, QPalette.ColorRole.Button: c.CONTROL,
        QPalette.ColorRole.ButtonText: c.TEXT, QPalette.ColorRole.BrightText: c.RED,
        QPalette.ColorRole.Highlight: c.ACCENT, QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: c.BOX, QPalette.ColorRole.ToolTipText: c.TEXT,
        QPalette.ColorRole.Link: c.ACCENT,
        QPalette.ColorRole.LinkVisited: "#bf5af2" if dark else "#af52de",
        QPalette.ColorRole.PlaceholderText: c.TEXT_OFF,
        QPalette.ColorRole.Light: light, QPalette.ColorRole.Midlight: midlight,
        QPalette.ColorRole.Mid: mid, QPalette.ColorRole.Dark: dark_,
        QPalette.ColorRole.Shadow: "#000000" if dark else "#8e8e93",
    }
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    disabled = QPalette.ColorGroup.Disabled
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        p.setColor(disabled, role, QColor(c.TEXT_OFF))
    p.setColor(disabled, QPalette.ColorRole.Button, QColor(c.BOX))
    p.setColor(disabled, QPalette.ColorRole.Base, QColor(c.WINDOW))
    p.setColor(disabled, QPalette.ColorRole.Highlight, QColor(c.BORDER))
    p.setColor(disabled, QPalette.ColorRole.HighlightedText, QColor(c.TEXT2))
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
    app.setPalette(make_palette(C, dark))
    app.setStyleSheet(style_sheet())
    theme.changed.emit()


def follow_system(app) -> None:
    """Apply the Windows light/dark setting now and whenever it is changed."""
    apply_theme(app)
    app.styleHints().colorSchemeChanged.connect(lambda *_: apply_theme(app))


class AppStyle(QProxyStyle):
    """Fusion with one change: a left click on a slider bar jumps to that point (user
    2026-11-19, camera gain sliders; Fusion only steps one page towards the click)."""

    def __init__(self) -> None:
        super().__init__(QStyleFactory.create("Fusion"))

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_Slider_AbsoluteSetButtons:
            return Qt.MouseButton.LeftButton.value
        return super().styleHint(hint, option, widget, returnData)


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
