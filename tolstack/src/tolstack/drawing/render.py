"""Render a drawing page with the extracted callouts outlined (visual verification of the extraction)."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

from .review import DrawingRecord

COLORS = {
    "parsed": (22, 140, 60), "ambiguous": (230, 140, 0), "unparsed": (130, 130, 130),
    "unsupported": (200, 30, 30), "confirmed": (30, 90, 210), "rejected": (90, 90, 90),
}


def render_overlay(pdf_path: str | Path, record: DrawingRecord, page: int = 1, scale: float = 2.0) -> Image.Image:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        img = pdf[page - 1].render(scale=scale).to_pil().convert("RGB")
    finally:
        pdf.close()
    draw = ImageDraw.Draw(img)
    for c in record.callouts:
        if c.page != page:
            continue
        conf = record.confirmation_for(c.id)
        key = conf.decision if conf else c.status
        col = COLORS[key]
        x0, top, x1, bottom = (v * scale for v in c.bbox)
        draw.rectangle([x0 - 3, top - 3, x1 + 3, bottom + 3], outline=col, width=3)
        draw.text((x0 - 3, bottom + 4), c.id.split("-")[-1], fill=col)
    for t in record.title_block:
        if t.page == page:
            x0, top, x1, bottom = (v * scale for v in t.bbox)
            draw.rectangle([x0 - 2, top - 2, x1 + 2, bottom + 2], outline=(120, 60, 170) if not t.confirmed
                           else COLORS["confirmed"], width=2)
    return img
