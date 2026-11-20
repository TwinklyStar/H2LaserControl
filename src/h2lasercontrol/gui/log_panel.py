"""Operation history: today's op-log entries, newest at the top, live."""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..oplog import OpLog, read_oplog
from .style import C, theme

MAX_ROWS = 2000
COLOR_ROLE = Qt.ItemDataRole.UserRole + 1  # name of the row's theme colour (style.C), or None
# routine queries: kept in the file, not shown
HIDDEN_ACTIONS = {"status", "identify", "read_now"}


class _Bridge(QObject):
    """OpLog listeners run in device threads; this re-emits entries into the GUI thread."""

    entry = Signal(dict)


class LogPanel(QWidget):
    COLUMNS = ("Time", "Operator", "Device", "Action", "Details", "Result")

    def __init__(self, oplog: OpLog, device_labels: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self.device_labels = device_labels
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 4, 16, 8)

        top = QHBoxLayout()
        title = QLabel("<b>Operation history</b> (today)")
        self.filter = QComboBox()
        self.filter.addItem("All devices", None)
        for key, label in device_labels.items():
            self.filter.addItem(label, key)
        self.filter.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(QLabel("Show:"))
        top.addWidget(self.filter)
        lay.addLayout(top)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        for i in range(len(self.COLUMNS) - 1):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)

        path = oplog.today_path()
        if os.path.exists(path):
            for e in read_oplog(path)[-MAX_ROWS:]:
                self.add_entry(e)
        self._bridge = _Bridge()
        self._bridge.entry.connect(self.add_entry)
        oplog.listeners.append(self._bridge.entry.emit)
        theme.changed.connect(self._retheme)

    def add_entry(self, e: dict[str, Any]) -> None:
        if e.get("action") in HIDDEN_ACTIONS:
            return
        event = e.get("event")
        if event == "failed":
            result, kind = f"FAILED: {e.get('error')}", "RED"
        elif event == "start":
            result, kind = "started", "GREY"
        else:
            result, kind = _summary(e.get("action"), e.get("result")), None
        args = ", ".join(f"{k}={v}" for k, v in (e.get("args") or {}).items())
        values = [
            str(e.get("time", ""))[11:19],
            str(e.get("user", "")),
            self.device_labels.get(e.get("device"), str(e.get("device"))),
            str(e.get("action", "")).replace("_", " "),
            args,
            result,
        ]
        self.table.insertRow(0)
        for col, v in enumerate(values):
            item = QTableWidgetItem(v)
            item.setToolTip(v)
            if kind is not None:
                item.setForeground(QColor(getattr(C, kind)))
            item.setData(Qt.ItemDataRole.UserRole, e.get("device"))
            item.setData(COLOR_ROLE, kind)
            self.table.setItem(0, col, item)
        if self.table.rowCount() > MAX_ROWS:
            self.table.removeRow(self.table.rowCount() - 1)
        self._apply_filter_row(0)

    def _retheme(self) -> None:
        for row in range(self.table.rowCount()):
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                kind = item.data(COLOR_ROLE) if item is not None else None
                if kind:
                    item.setForeground(QColor(getattr(C, kind)))

    def _apply_filter(self) -> None:
        for row in range(self.table.rowCount()):
            self._apply_filter_row(row)

    def _apply_filter_row(self, row: int) -> None:
        want = self.filter.currentData()
        dev = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self.table.setRowHidden(row, want is not None and dev != want)


def _summary(action: str | None, result: Any) -> str:
    """Short human-readable result (the full value stays in the log file)."""
    if action == "connect":
        return "connected"
    if result is None:
        return "OK"
    if isinstance(result, float):
        return f"{result:.2f}°"  # ELL14 angles
    if isinstance(result, dict):
        if "text" in result:  # e.g. DG645 change made outside the program
            return _short(result["text"])
        if "new_us" in result:  # DG645: our channel, offset from nominal
            return f"{result.get('channel', '')} {result['old_us']:+.3f} → {result['new_us']:+.3f} µs"
        if "position" in result and len(result) <= 2:
            return f"position {result['position']}"
        return _short(", ".join(f"{k} {v}" for k, v in result.items()))
    return _short(result)


def _short(value: Any, limit: int = 120) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
