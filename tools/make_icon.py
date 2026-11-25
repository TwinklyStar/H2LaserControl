"""Make the program icon from a picture (user 2026-11-25):
src/h2lasercontrol/gui/icon/source.jpg  ->  h2lasercontrol.png (256 px) and h2lasercontrol.ico
(16 … 256 px).

    python tools/make_icon.py [picture]

With a picture given, it is copied to source.jpg first. A non-square picture is cropped to
its centre square.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ICON_DIR = Path(__file__).resolve().parents[1] / "src" / "h2lasercontrol" / "gui" / "icon"
SOURCE = ICON_DIR / "source.jpg"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main(argv: list[str]) -> int:
    if argv:
        Image.open(argv[0]).convert("RGB").save(SOURCE, quality=95)
    im = Image.open(SOURCE).convert("RGBA")
    side = min(im.size)
    left, top = (im.width - side) // 2, (im.height - side) // 2
    im = im.crop((left, top, left + side, top + side))
    images = [im.resize((s, s), Image.LANCZOS) for s in SIZES]
    images[-1].save(ICON_DIR / "h2lasercontrol.png")
    images[-1].save(ICON_DIR / "h2lasercontrol.ico", sizes=[(s, s) for s in SIZES],
                    append_images=images[:-1])
    print(f"written {ICON_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
