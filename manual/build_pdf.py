"""Build manual.pdf from manual.md (run in the H2LaserControl conda env):

    python manual/build_pdf.py

Needs nothing beyond the program's own packages: a small Markdown converter (only what
manual.md uses: headings, paragraphs, lists, tables, quotes, images, **bold**, *italic*, `code`)
and Qt WebEngine to print the HTML to PDF.
"""
import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "manual.md"
OUT = HERE / "H2LaserControl_manual.pdf"

CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10.5pt; line-height: 1.45;
       color: #1d1d1f; }
h1 { font-size: 22pt; margin: 0 0 2mm 0; color: #0a58ca; }
h2 { font-size: 16pt; margin: 9mm 0 3mm 0; padding-bottom: 1mm;
     border-bottom: 2px solid #0a58ca; color: #0a58ca; }
h2.newpage { break-before: page; margin-top: 0; }
h3 { font-size: 12.5pt; margin: 7mm 0 2mm 0; break-after: avoid; }
p { margin: 1.5mm 0; }
ul, ol { margin: 1.5mm 0; padding-left: 6mm; }
li { margin: 0.8mm 0; }
img { width: 100%; border: 1px solid #c7c7cc; border-radius: 4px; margin: 2mm 0 3mm 0; }
figure { margin: 0; break-inside: avoid; text-align: center; }
img[alt="The main window"] { width: 88%; }
table { border-collapse: collapse; margin: 2mm 0; width: 100%; }
th, td { border: 1px solid #c7c7cc; padding: 1.2mm 2.5mm; text-align: left; }
th { background: #eef3fb; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; background: #fff4e5;
             border-left: 4px solid #e67e00; }
code { font-family: Consolas, monospace; font-size: 9.5pt; background: #f2f2f7;
       padding: 0 1mm; border-radius: 2px; }
.sub { color: #6e6e73; }
"""


def inline(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(f"<code>{html.escape(p[1:-1])}</code>")
            continue
        p = html.escape(p, quote=False)
        p = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", p)
        p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", p)
        out.append(p)
    return "".join(out)


def convert(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    h2_count = 0

    def gather(start: int, cont) -> tuple[list[str], int]:
        block, j = [], start
        while j < len(lines) and lines[j].strip() and cont(lines[j], j == start):
            block.append(lines[j])
            j += 1
        return block, j

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        m = re.match(r"(#{1,3}) (.*)", s)
        if m:
            level = len(m.group(1))
            cls = ""
            if level == 2:
                h2_count += 1
                cls = ' class="newpage"' if h2_count > 1 else ""
            out.append(f"<h{level}{cls}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue
        m = re.match(r"!\[(.*?)\]\((.*?)\)$", s)
        if m:
            src = (HERE / m.group(2)).as_uri()
            out.append(f'<figure><img src="{src}" alt="{html.escape(m.group(1))}"></figure>')
            i += 1
            continue
        if s.startswith("|"):
            block, i = gather(i, lambda ln, first: ln.strip().startswith("|"))
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in block]
            head, body = rows[0], [r for r in rows[1:] if not set("".join(r)) <= set("-: ")]
            t = ["<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>"]
            t += ["<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body]
            out.append("".join(t) + "</table>")
            continue
        if s.startswith(">"):
            block, i = gather(i, lambda ln, first: ln.strip().startswith(">"))
            text = " ".join(b.strip()[1:].strip() for b in block)
            out.append(f"<blockquote>{inline(text)}</blockquote>")
            continue
        m = re.match(r"(- |\d+\. )", s)
        if m:
            tag = "ul" if s.startswith("- ") else "ol"
            items: list[str] = []
            while i < len(lines) and lines[i].strip():
                ln = lines[i]
                mm = re.match(r"(- |\d+\. )(.*)", ln)
                if mm:
                    items.append(mm.group(2))
                else:  # continuation line of the previous item
                    items[-1] += " " + ln.strip()
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
            continue
        block, i = gather(i, lambda ln, first: first or not re.match(r"(#|!\[|\||>|- |\d+\. )",
                                                                     ln.strip()))
        text = " ".join(b.strip() for b in block)
        italic = re.fullmatch(r"\*[^*].*[^*]\*", text) is not None
        cls = ' class="sub"' if italic else ""
        out.append(f"<p{cls}>{inline(text)}</p>")
    return ("<!doctype html><html><head><meta charset='utf-8'><title>H2 Laser Control manual"
            f"</title><style>{CSS}</style></head><body>{''.join(out)}</body></html>")


def main() -> int:
    from PySide6.QtCore import QMarginsF, QTimer, QUrl
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWidgets import QApplication

    page_html = convert(SRC.read_text(encoding="utf-8"))
    tmp_html = HERE / "_manual.html"
    tmp_html.write_text(page_html, encoding="utf-8")
    app = QApplication(sys.argv)
    page = QWebEnginePage()
    result = {"ok": False}

    def loaded(ok: bool) -> None:
        if not ok:
            print("could not load the HTML")
            app.quit()
            return
        layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                             QMarginsF(15, 16, 15, 16), QPageLayout.Unit.Millimeter)
        page.printToPdf(str(OUT), layout)

    def done(path: str, ok: bool) -> None:
        result["ok"] = ok
        QTimer.singleShot(0, app.quit)

    page.loadFinished.connect(loaded)
    page.pdfPrintingFinished.connect(done)
    page.load(QUrl.fromLocalFile(str(tmp_html)))
    app.exec()
    tmp_html.unlink(missing_ok=True)
    print(f"written {OUT}" if result["ok"] else "PDF printing failed")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
