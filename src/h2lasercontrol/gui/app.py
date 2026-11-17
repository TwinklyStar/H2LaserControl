"""Start the GUI:  python -m h2lasercontrol.gui [--sim] [--config PATH]"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from ..config import DEFAULT_CONFIG, load_config
from ..oplog import OpLog
from .main_window import MainWindow
from .style import STYLE_SHEET

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="h2lasercontrol")
    ap.add_argument("--sim", action="store_true", help="simulated devices (no hardware)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--no-connect", action="store_true", help="do not connect at start")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)

    # only one real instance: two programs cannot share the serial ports
    lock = QLockFile(str(Path(tempfile.gettempdir()) /
                         ("h2lasercontrol-sim.lock" if args.sim else "h2lasercontrol.lock")))
    if not lock.tryLock(100):
        QMessageBox.warning(None, "H2 Laser Control", "H2 Laser Control is already running.")
        return 1

    oplog = OpLog(LOG_DIR / "sim" if args.sim else LOG_DIR)
    # simulation must never overwrite the real saved angles (config/saved_angles.json)
    state_dir = str(LOG_DIR / "sim") if args.sim else None
    window = MainWindow(load_config(args.config), oplog, sim=args.sim, state_dir=state_dir)
    window.show()
    window.start(auto_connect=not args.no_connect)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
