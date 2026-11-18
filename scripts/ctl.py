"""Run ONE driver action from the command line (for Phase 1 hardware checks and maintenance).

    python scripts/ctl.py list
    python scripts/ctl.py ell14 get_position
    python scripts/ctl.py ell14 move_abs deg=45 --allow-motion
    python scripts/ctl.py hitmv insert axis=1 --allow-motion
    python scripts/ctl.py flipmounts retract unit=flip2 --allow-motion

Actions that move hardware are refused unless --allow-motion is given (lab rule: every motion
needs explicit permission and a person checking it). Ctrl+C during a motion stops the device.
Everything is recorded in the operation log (logs/).
"""

import argparse
import logging
import sys
import threading

from h2lasercontrol.config import load_config
from h2lasercontrol.drivers import Ell14, HitMv, Mff, create_driver
from h2lasercontrol.oplog import OpLog

DRIVER_CLASSES = {"ell14": Ell14, "hitmv": HitMv, "mff": Mff}


def parse_value(text: str):
    for conv in (int, float):
        try:
            return conv(text)
        except ValueError:
            pass
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("device", help="device key from config/devices.toml, or 'list'")
    ap.add_argument("action", nargs="?")
    ap.add_argument("args", nargs="*", help="key=value arguments")
    ap.add_argument("--allow-motion", action="store_true", help="permit an action that moves")
    ap.add_argument("--debug", action="store_true", help="print raw bytes")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.debug else logging.WARNING,
                        format="%(asctime)s %(name)s %(message)s")
    config = load_config()

    if a.device == "list":
        for key, cfg in config.items():
            print(f"{key} ({cfg.type}):")
            for name, info in sorted(DRIVER_CLASSES[cfg.type].actions().items()):
                print(f"  {name}{'   [MOVES]' if info.moves else ''}")
        return 0

    if a.device not in config or not a.action:
        ap.error(f"give a device ({', '.join(config)}) and an action")
    cfg = config[a.device]
    info = DRIVER_CLASSES[cfg.type].actions().get(a.action)
    if info is None:
        ap.error(f"unknown action {a.action!r}; see 'ctl.py list'")
    if info.moves and not a.allow_motion:
        print(f"REFUSED: {a.device}.{a.action} moves hardware; add --allow-motion "
              "(only with permission and someone watching the device).")
        return 2
    kwargs = {}
    for item in a.args:
        k, sep, v = item.partition("=")
        if not sep:
            ap.error(f"argument {item!r} is not key=value")
        kwargs[k] = parse_value(v)

    drv = create_driver(cfg, OpLog("logs"))
    drv.execute("connect")
    outcome: dict = {}

    def run():
        try:
            outcome["result"] = drv.execute(a.action, **kwargs)
        except Exception as e:  # noqa: BLE001 - reported to the user below
            outcome["error"] = e

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        print("Ctrl+C: stopping the device ...")
        drv.request_stop()
        worker.join(30)
    finally:
        drv.execute("disconnect")
    if "error" in outcome:
        e = outcome["error"]
        print(f"FAILED: {type(e).__name__}: {e}")
        return 1
    print(outcome.get("result"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
