"""Make the program icon from a picture (user 2026-11-25):
src/h2lasercontrol/gui/icon/source.jpg  ->  h2lasercontrol.png (256 px) and h2lasercontrol.ico
(16 … 256 px).

    python tools/make_icon.py [picture]

With a picture given, it is copied to source.jpg first. A non-square picture is cropped to
its centre square. The icon is made brighter and gets rounded corners (settings below).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

ICON_DIR = Path(__file__).resolve().parents[1] / "src" / "h2lasercontrol" / "gui" / "icon"
SOURCE = ICON_DIR / "source.jpg"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
BRIGHTNESS, CONTRAST, COLOUR = 1.35, 1.15, 1.25  # 1 = unchanged
CORNER = 0.2  # corner radius as a fraction of the width


def main(argv: list[str]) -> int:
    if argv:
        Image.open(argv[0]).convert("RGB").save(SOURCE, quality=95)
    im = Image.open(SOURCE).convert("RGBA")
    side = min(im.size)
    left, top = (im.width - side) // 2, (im.height - side) // 2
    im = im.crop((left, top, left + side, top + side)).resize((1024, 1024), Image.LANCZOS)
    # brighter, a little more contrast and colour: small icons look dark otherwise (user)
    rgb = im.convert("RGB")
    rgb = ImageEnhance.Brightness(rgb).enhance(BRIGHTNESS)
    rgb = ImageEnhance.Contrast(rgb).enhance(CONTRAST)
    rgb = ImageEnhance.Color(rgb).enhance(COLOUR)
    # rounded corners (user): transparent outside a rounded square
    mask = Image.new("L", rgb.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *[v - 1 for v in rgb.size]),
                                           radius=round(rgb.width * CORNER), fill=255)
    im = rgb.convert("RGBA")
    im.putalpha(mask)
    images = [im.resize((s, s), Image.LANCZOS) for s in SIZES]
    images[-1].save(ICON_DIR / "h2lasercontrol.png")
    images[-1].save(ICON_DIR / "h2lasercontrol.ico", sizes=[(s, s) for s in SIZES],
                    append_images=images[:-1])
    print(f"written {ICON_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
