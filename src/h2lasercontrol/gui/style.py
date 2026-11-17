"""Colours, fonts and the application style sheet (one place, so the look stays consistent)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

GREEN = "#2e7d32"  # normal / safe (retracted, connected)
ORANGE = "#e65100"  # attention (inserted = beam blocked, partly inserted)
BLUE = "#1565c0"  # moving / busy
RED = "#c62828"  # error / stop
GREY = "#757575"  # disconnected / unknown

TAB_STATES = {"ok": GREEN, "busy": BLUE, "off": GREY, "error": RED}

STYLE_SHEET = f"""
QWidget {{ font-size: 10.5pt; }}
QTabBar::tab {{ padding: 8px 18px; min-width: 150px; }}
QTabBar::tab:selected {{ font-weight: bold; }}
QGroupBox {{ font-weight: bold; border: 1px solid #c8c8c8; border-radius: 6px;
             margin-top: 14px; padding: 12px 10px 10px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QPushButton {{ padding: 6px 14px; }}
QPushButton[role="primary"] {{ font-size: 12pt; font-weight: bold; padding: 10px 22px; }}
QPushButton[role="stop"] {{ background: {RED}; color: white; font-weight: bold;
                            padding: 8px 22px; border-radius: 4px; }}
QPushButton[role="stop"]:disabled {{ background: #e0b4b4; color: #f5f5f5; }}
QLabel[role="big"] {{ font-size: 20pt; font-weight: bold; }}
QLabel[role="muted"] {{ color: {GREY}; }}
QLabel[role="error"] {{ background: #fdecea; color: {RED}; border: 1px solid #f5c2c0;
                        border-radius: 4px; padding: 6px 10px; }}
QLabel[role="sim"] {{ background: #fff3cd; color: #7a5b00; font-weight: bold; padding: 6px;
                      border-bottom: 1px solid #e6d28f; }}
"""


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
    """Apply a style-sheet role (see STYLE_SHEET) and refresh the style."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
