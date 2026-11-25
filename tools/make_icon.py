"""Draw the program icon: src/h2lasercontrol/gui/icon/h2lasercontrol.png (256 px) and .ico
(16 … 256 px, each size drawn separately so the small ones stay sharp).

    python tools/make_icon.py

Design: blue rounded square, white "H₂", a violet laser beam with a glow across the bottom.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

OUT = Path(__file__).resolve().parents[1] / "src" / "h2lasercontrol" / "gui" / "icon"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    s = size / 256  # design units: 256 × 256
    m = 8 * s if size >= 32 else 0.5  # margin
    box = QRectF(m, m, size - 2 * m, size - 2 * m)
    path = QPainterPath()
    path.addRoundedRect(box, 52 * s, 52 * s)
    grad = QLinearGradient(box.topLeft(), box.bottomRight())
    grad.setColorAt(0, QColor("#2f6bff"))
    grad.setColorAt(1, QColor("#0a2a8a"))
    p.fillPath(path, grad)
    p.setClipPath(path)

    # laser beam across the lower part: wide soft glow, then a bright core
    y = 196 * s
    half = 26 * s
    glow = QLinearGradient(QPointF(0, y - half), QPointF(0, y + half))
    glow.setColorAt(0.0, QColor(190, 120, 255, 0))
    glow.setColorAt(0.5, QColor(200, 140, 255, 190))
    glow.setColorAt(1.0, QColor(190, 120, 255, 0))
    p.fillRect(QRectF(0, y - half, size, 2 * half), glow)
    p.setPen(QPen(QColor("#f3e8ff"), max(1.0, 6 * s), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.FlatCap))
    p.drawLine(QPointF(0, y), QPointF(size, y))

    # "H₂"
    p.setPen(QColor("white"))
    big = QFont("Segoe UI", 1)
    big.setBold(True)
    big.setPixelSize(max(9, round(132 * s)))
    small = QFont(big)
    small.setPixelSize(max(6, round(74 * s)))
    fb, fs = QFontMetricsF(big), QFontMetricsF(small)
    wh, w2 = fb.horizontalAdvance("H"), fs.horizontalAdvance("2")
    gap = 4 * s
    x0 = (size - (wh + gap + w2)) / 2
    base = 142 * s
    p.setFont(big)
    p.drawText(QPointF(x0, base), "H")
    p.setFont(small)
    p.drawText(QPointF(x0 + wh + gap, base + 22 * s), "2")
    p.end()
    return img


def main() -> int:
    from PIL import Image

    QGuiApplication(sys.argv[:1])
    OUT.mkdir(parents=True, exist_ok=True)
    images = []
    for size in SIZES:
        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        draw(size).save(buf, "PNG")
        images.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
    images[-1].save(OUT / "h2lasercontrol.png")
    images[-1].save(OUT / "h2lasercontrol.ico", sizes=[(s, s) for s in SIZES],
                    append_images=images[:-1])
    print(f"written {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
