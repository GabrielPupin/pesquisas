"""Generates vector PDF demonstration drawings and their ground truth (examples/drawings/*.json).

The drawings exercise the extractor on: bilateral tolerances, stacked deviations (small font above/below),
ISO 286 classes, decimal comma, limit dimensions, a basic dimension in a box, an untoleranced dimension
covered by ISO 2768-m, a rotated dimension, a feature control frame whose symbol is vector graphics
(not text — the extractor must ask for the type), and title blocks in English and Portuguese.
Run:  python examples/make_demo_drawings.py
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "drawings"
FONT = "Helvetica"
for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
    if Path(cand).exists():
        pdfmetrics.registerFont(TTFont("DrawSans", cand))
        FONT = "DrawSans"
        break


def arrow(c, x, y, dx):
    p = c.beginPath()
    p.moveTo(x, y); p.lineTo(x + 6 * dx, y + 2); p.lineTo(x + 6 * dx, y - 2); p.close()
    c.drawPath(p, fill=1, stroke=0)


def dim_h(c, x1, x2, y, ybase, text, size=10, stacked=None):
    c.setLineWidth(0.4)
    c.line(x1, ybase, x1, y + 3); c.line(x2, ybase, x2, y + 3)
    c.line(x1, y, x2, y); arrow(c, x1, y, 1); arrow(c, x2, y, -1)
    c.setFont(FONT, size)
    w = pdfmetrics.stringWidth(text, FONT, size)
    tx = (x1 + x2) / 2 - w / 2
    c.drawString(tx, y + 3, text)
    if stacked:
        c.setFont(FONT, size * 0.62)
        c.drawString(tx + w + 1.5, y + 3 + size * 0.45, stacked[0])
        c.drawString(tx + w + 1.5, y + 3 - size * 0.05, stacked[1])


def dim_v(c, x, y1, y2, xbase, text, size=10):
    c.setLineWidth(0.4)
    c.line(xbase, y1, x - 3, y1); c.line(xbase, y2, x - 3, y2)
    c.line(x, y1, x, y2)
    c.saveState()
    c.translate(x - 3, (y1 + y2) / 2)
    c.rotate(90)
    c.setFont(FONT, size)
    c.drawCentredString(0, 0, text)
    c.restoreState()


def boxed(c, x, y, text, size=10):
    c.setFont(FONT, size)
    w = pdfmetrics.stringWidth(text, FONT, size)
    c.drawString(x, y, text)
    c.setLineWidth(0.5)
    c.rect(x - 2.5, y - 3, w + 5, size + 4)


def fcf_vector_cylindricity(c, x, y, value, size=10):
    """Feature control frame: [symbol drawn as vector][value]."""
    h = size + 6
    c.setLineWidth(0.5)
    c.rect(x, y, h, h)
    cx, cy = x + h / 2, y + h / 2
    c.circle(cx, cy, h * 0.22)
    c.line(cx - h * 0.38, cy - h * 0.3, cx - h * 0.08, cy + h * 0.3)
    c.line(cx + h * 0.08, cy - h * 0.3, cx + h * 0.38, cy + h * 0.3)
    c.setFont(FONT, size)
    w = pdfmetrics.stringWidth(value, FONT, size)
    c.rect(x + h, y, w + 8, h)
    c.drawString(x + h + 4, y + 4, value)


def title_block(c, lines, size=8):
    W, H = landscape(A4)
    x0, y0 = W - 260, 30
    c.setLineWidth(0.8)
    c.rect(x0, y0, 230, 14 * len(lines) + 8)
    c.setFont(FONT, size)
    for i, ln in enumerate(lines):
        c.drawString(x0 + 6, y0 + 8 + 14 * (len(lines) - 1 - i), ln)


def frame(c):
    W, H = landscape(A4)
    c.setLineWidth(1.2)
    c.rect(20, 20, W - 40, H - 40)


def housing(path):
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    frame(c)
    c.setLineWidth(1.0)
    # section of the housing (schematic)
    c.rect(150, 220, 360, 160)           # outer
    c.rect(200, 250, 250, 100)           # bore cavity
    c.line(200, 300, 450, 300)           # centre line (thin)
    dim_h(c, 200, 450, 420, 350, "50 ±0,1")                                   # shoulder to cover seat
    dim_h(c, 150, 510, 460, 380, "80")                                        # untoleranced (ISO 2768-m)
    dim_h(c, 200, 300, 190, 250, "Ø47", stacked=("+0,007", "-0,018"))         # bearing seat, stacked devs
    boxed(c, 330, 196, "30")                                                  # basic dimension
    dim_v(c, 120, 220, 380, 150, "60 ±0.2")                                   # rotated text
    c.setFont(FONT, 10)
    c.drawString(560, 330, "Ø20 H7")
    fcf_vector_cylindricity(c, 560, 300, "0,005")
    title_block(c, ["DWG NO: TS-100", "TITLE: HOUSING", "REV: B", "UNITS: mm",
                    "GENERAL TOLERANCES ISO 2768-m", "ISO 8015"])
    c.showPage(); c.save()
    return [
        {"text": "50 ±0,1", "status": "parsed", "kind": "linear", "nominal": 50.0, "upper": 0.1, "lower": -0.1},
        {"text": "80", "status": "parsed", "kind": "linear", "nominal": 80.0, "upper": 0.3, "lower": -0.3,
         "origin": "general"},
        {"text": "Ø47 +0,007/-0,018", "status": "parsed", "kind": "diameter", "nominal": 47.0, "upper": 0.007,
         "lower": -0.018},
        {"text": "30", "status": "parsed", "kind": "linear", "nominal": 30.0, "upper": 0.0, "lower": 0.0,
         "origin": "basic"},
        {"text": "60 ±0.2", "status": "parsed", "kind": "linear", "nominal": 60.0, "upper": 0.2, "lower": -0.2},
        {"text": "Ø20 H7", "status": "parsed", "kind": "diameter", "nominal": 20.0, "upper": 0.021, "lower": 0.0},
        {"text": "0,005", "status": "ambiguous", "category": "geometric"},
    ], {"drawing_number": "TS-100", "revision": "B", "unit": "mm", "general_tolerance": "ISO 2768-m",
        "size_principle": "independency"}


def spacer(path):
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    frame(c)
    c.setLineWidth(1.0)
    c.rect(250, 250, 200, 80)
    dim_h(c, 250, 450, 370, 330, "19,8 ±0,05")
    dim_h(c, 250, 350, 210, 250, "20,2/20,0")
    c.setFont(FONT, 10)
    c.drawString(480, 300, "Ø32 +0,1/0")
    title_block(c, ["DESENHO Nº: TS-110", "TÍTULO: ESPAÇADOR", "REVISÃO: A", "UNIDADE: mm",
                    "TOLERÂNCIAS GERAIS ISO 2768-m"])
    c.showPage(); c.save()
    return [
        {"text": "19,8 ±0,05", "status": "parsed", "kind": "linear", "nominal": 19.8, "upper": 0.05, "lower": -0.05},
        {"text": "20,2/20,0", "status": "parsed", "kind": "linear", "nominal": 20.1, "upper": 0.1, "lower": -0.1,
         "origin": "limits"},
        {"text": "Ø32 +0,1/0", "status": "parsed", "kind": "diameter", "nominal": 32.0, "upper": 0.1, "lower": 0.0},
    ], {"drawing_number": "TS-110", "revision": "A", "unit": "mm", "general_tolerance": "ISO 2768-m"}


def shaft(path):
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    frame(c)
    c.setLineWidth(1.0)
    c.rect(150, 270, 400, 60)
    c.setFont(FONT, 10)
    c.drawString(300, 350, "Ø20 g6")
    fcf_vector_cylindricity(c, 300, 380, "0,005")
    c.drawString(600, 300, "M8")
    title_block(c, ["DWG NO: TS-120", "TITLE: SHAFT", "REV: A", "UNITS: mm", "ISO 8015"])
    c.showPage(); c.save()
    return [
        {"text": "Ø20 g6", "status": "parsed", "kind": "diameter", "nominal": 20.0, "upper": -0.007, "lower": -0.020},
        {"text": "0,005", "status": "ambiguous", "category": "geometric"},
        {"text": "M8", "status": "unsupported"},
    ], {"drawing_number": "TS-120", "revision": "A", "unit": "mm", "size_principle": "independency"}


def no_text(path):
    """Text converted to outlines: no extractable text (the extractor must say so)."""
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    frame(c)
    c.rect(200, 200, 300, 100)
    c.showPage(); c.save()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    truth = {}
    for name, fn in (("TS-100_housing.pdf", housing), ("TS-110_spacer.pdf", spacer), ("TS-120_shaft.pdf", shaft)):
        callouts, tb = fn(OUT / name)
        truth[name] = {"callouts": callouts, "title_block": tb}
    no_text(OUT / "outlined_text.pdf")
    (OUT / "ground_truth.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8")
    print("written to", OUT)
