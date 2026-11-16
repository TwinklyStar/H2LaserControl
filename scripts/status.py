"""READ-ONLY status of all configured devices. Sends only queries; nothing moves, nothing is written
to the devices. Every query is recorded in the operation log (logs/).

Usage: python scripts/status.py [--debug]
"""

import argparse
import logging
import sys

from h2lasercontrol.config import load_config
from h2lasercontrol.drivers import Ell14, HitMv, create_driver
from h2lasercontrol.oplog import OpLog

ELL14_QUERIES = ["status", "get_position", "get_home_offset", "get_jog_step", "get_velocity"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true", help="print raw bytes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s %(name)s %(message)s")
    oplog = OpLog("logs")
    failed = False
    for key, cfg in load_config().items():
        print(f"=== {key} ({cfg.type}) ===")
        try:
            drv = create_driver(cfg, oplog)
            print(f"  port: {drv.transport.name} -> {getattr(drv.transport, 'port', '?')}")
            print(f"  identify: {drv.execute('connect')}")
            try:
                if isinstance(drv, HitMv):
                    print(f"  status: {drv.execute('status')}")
                    for axis in drv.axes:
                        print(f"  axis {axis} speed ?:D{axis}: {drv.execute('get_speed', axis=axis)}")
                        hs = drv.execute("get_homing_speed", axis=axis)
                        print(f"  axis {axis} homing ?:B{axis}: {hs}")
                elif isinstance(drv, Ell14):
                    for name in ELL14_QUERIES:
                        print(f"  {name}: {drv.execute(name)}")
            finally:
                drv.execute("disconnect")
        except Exception as e:  # noqa: BLE001 - report and continue with the next device
            failed = True
            print(f"  !! {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
