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
from .style import follow_system

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"


def _setup_logging(log_dir: Path):
    """Debug log `h2lasercontrol.log` (the previous run is kept as `.prev.log`, it shows how
    that run ended) and `fault.log` for native crash traces / GUI-freeze stack dumps (as the
    old camera program did). Returns the open fault-log file."""
    import faulthandler

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "h2lasercontrol.log"
    if log_file.exists():
        try:
            log_file.replace(log_file.with_name("h2lasercontrol.prev.log"))
        except OSError:
            pass
    fault_file = open(log_dir / "fault.log", "w")  # noqa: SIM115 - open for the whole run
    faulthandler.enable(fault_file)
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console],
                        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s  %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("PIL", "matplotlib", "fsspec"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return fault_file


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="h2lasercontrol")
    ap.add_argument("--sim", action="store_true", help="simulated devices (no hardware)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--no-connect", action="store_true", help="do not connect at start")
    args = ap.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    follow_system(app)  # light / dark like Windows, also when it is switched while running

    # only one real instance: two programs cannot share the serial ports
    lock = QLockFile(str(Path(tempfile.gettempdir()) /
                         ("h2lasercontrol-sim.lock" if args.sim else "h2lasercontrol.lock")))
    if not lock.tryLock(100):
        QMessageBox.warning(None, "H2 Laser Control", "H2 Laser Control is already running.")
        return 1
    # after the lock: a second copy must not rotate the running copy's log
    fault_file = _setup_logging(LOG_DIR / "sim" if args.sim else LOG_DIR)

    oplog = OpLog(LOG_DIR / "sim" if args.sim else LOG_DIR)
    # simulation must never overwrite the real saved angles (config/saved_angles.json)
    state_dir = str(LOG_DIR / "sim") if args.sim else None
    # simulated PicoScope / camera data must never mix with real data: logs/sim/data/...
    daq_base_dir = str(LOG_DIR / "sim") if args.sim else None
    window = MainWindow(load_config(args.config), oplog, sim=args.sim, state_dir=state_dir,
                        daq_base_dir=daq_base_dir)
    app.aboutToQuit.connect(window.shutdown_daq)  # scopes and camera are always closed
    # dumps every thread's stack to the fault log if the GUI freezes > 3 s (camera program)
    from ..laserdaq.gui.hang_watchdog import HangWatchdog

    watchdog = HangWatchdog(out=fault_file, parent=window)
    watchdog.start()
    window.show()
    window.start(auto_connect=not args.no_connect)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
