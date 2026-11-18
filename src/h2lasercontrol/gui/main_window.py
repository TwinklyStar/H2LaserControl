"""Main window: browser-style tabs (one per device) above the operation history."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import PROGRAM_DIR, DeviceConfig
from ..oplog import OpLog
from ..services import DeviceService
from .daq import DAQ_TABS
from .log_panel import LogPanel
from .panels import PANELS, DevicePanel
from .style import TAB_STATES, dot_icon, set_role

log = logging.getLogger(__name__)


class TopBar(QWidget):
    """Operator row (a named class so the style sheet can address it, see style.OWN)."""


class MainWindow(QMainWindow):
    def __init__(self, config: dict[str, DeviceConfig], oplog: OpLog, *, sim: bool = False,
                 settings: QSettings | None = None, state_dir: str | None = None,
                 daq_base_dir: str | None = None):
        super().__init__()
        self.oplog = oplog
        self.sim = sim
        self.setWindowTitle("H2 Laser Control" + ("  —  SIMULATION" if sim else ""))
        self.resize(1100, 780)
        self.settings = settings or QSettings("H2LaserControl", "gui")

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        if sim:
            banner = QLabel("SIMULATION — no real device is controlled. Logs, saved angles and "
                            "simulated scope / camera data go to logs/sim/.")
            banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
            set_role(banner, "sim")
            root.addWidget(banner)

        # operator (who is operating: written into every log entry)
        top_bar = TopBar()  # named class: the app style sheet is scoped to our widgets
        top = QHBoxLayout(top_bar)
        top.setContentsMargins(16, 8, 16, 0)
        top.addStretch(1)
        top.addWidget(QLabel("Operator:"))
        self.operator = QLineEdit(self.settings.value("operator", oplog.user))
        self.operator.setFixedWidth(180)
        self.operator.setPlaceholderText("your name")
        self.operator.editingFinished.connect(self._set_operator)
        top.addWidget(self.operator)
        root.addWidget(top_bar)
        self._set_operator()

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.services: list[DeviceService] = []
        self.panels: list[DevicePanel] = []
        self.daq_tabs: list = []  # PicoScope / camera tabs (F8): own Start/Pause/Stop
        labels = {}
        for key, cfg in config.items():
            daq_cls = DAQ_TABS.get(cfg.type)
            if daq_cls is not None:
                label = cfg.settings.get("label", key)
                labels[key] = label
                tab = daq_cls(cfg, oplog, sim=sim, base_dir=daq_base_dir or PROGRAM_DIR)
                index = self.tabs.addTab(tab, label)
                tab.tab_state_changed.connect(
                    lambda s, i=index: self.tabs.setTabIcon(i, dot_icon(TAB_STATES[s])))
                self.tabs.setTabIcon(index, dot_icon(TAB_STATES["off"]))
                self.daq_tabs.append(tab)
                continue
            panel_cls = PANELS.get(cfg.type)
            if panel_cls is None:
                continue  # device type without a GUI panel yet
            label = cfg.settings.get("label", key)
            labels[key] = label
            service = DeviceService(cfg, oplog, sim=sim, state_dir=state_dir)
            panel = panel_cls(service, cfg)
            index = self.tabs.addTab(panel, label)
            panel.tab_state_changed.connect(
                lambda s, i=index: self.tabs.setTabIcon(i, dot_icon(TAB_STATES[s])))
            panel._emit_tab_state()
            self.services.append(service)
            self.panels.append(panel)

        self.log_panel = LogPanel(oplog, labels)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(self.log_panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
        self.setCentralWidget(central)

        last = self.settings.value("tab", 0, int)
        if 0 <= last < self.tabs.count():
            self.tabs.setCurrentIndex(last)

    def start(self, auto_connect: bool = True) -> None:
        for s in self.services:
            s.start()
            if auto_connect:
                s.submit("connect")

    def _set_operator(self) -> None:
        name = self.operator.text().strip()
        if name:
            self.oplog.user = name
            self.settings.setValue("operator", name)

    def closeEvent(self, event: QCloseEvent) -> None:
        busy = [p.cfg.settings.get("label", p.cfg.key) for p in self.panels if p.busy]
        busy += [t.cfg.settings.get("label", t.cfg.key) for t in self.daq_tabs if t.running]
        if busy:
            box = QMessageBox(
                QMessageBox.Icon.Warning, "Still running",
                "Still running: " + ", ".join(busy) + "\n\nStop it and quit? "
                "(The data taken so far is saved.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if box.exec() != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.settings.setValue("tab", self.tabs.currentIndex())
        for s in self.services:
            s.shutdown()
        self.shutdown_daq()
        event.accept()

    def shutdown_daq(self) -> None:
        """Stop all acquisitions and close the camera (files are closed cleanly)."""
        for t in self.daq_tabs:
            try:
                t.shutdown()
            except Exception:
                log.exception("closing %s failed", t.cfg.key)
