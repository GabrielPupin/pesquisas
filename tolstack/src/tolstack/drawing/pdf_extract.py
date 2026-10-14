"""Assisted extraction of dimensions and tolerances from vector PDF drawings.

Pipeline: text (pdfplumber) -> runs on a baseline -> title block / notes -> stacked deviations ->
boxes (basic dimensions) and feature control frames -> deterministic callout parser.
The result is a DrawingRecord of *proposals*; nothing is used until confirmed (see workflow.py).
Scanned PDFs or text converted to outlines carry no text: this is reported, OCR is not attempted.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .. import __version__
from .callout_parser import NUM, normalize, parse_callout
from .clustering import attach_stacked, detect_boxes_and_frames, rotated_chars_to_runs, words_to_runs
from .review import DrawingRecord, ExtractedCallout, ParsedCallout, TitleBlockCandidate
from .title_block import first, match_title

EXTRACTOR_VERSION = f"tolstack-{__version__}/pdf-1"


def extract_drawing(path: str | Path, drawing_id: Optional[str] = None) -> DrawingRecord:
    path = Path(path)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    did = drawing_id or path.stem
    title: list[TitleBlockCandidate] = []
    pages_runs = []
    any_text = False
    with pdfplumber.open(path) as pdf:
        n_pages = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, start=1):
            chars = page.chars
            any_text = any_text or bool(chars)
            words = [w for w in page.extract_words(extra_attrs=["size", "upright"]) if w.get("upright", True)]
            runs = words_to_runs(words) + rotated_chars_to_runs(chars)
            for r in runs:
                found = match_title(r.text)
                if found:
                    r.consumed = True
                    for fld, val in found:
                        title.append(TitleBlockCandidate(field=fld, value=val, raw_text=r.text, page=pno,
                                                         bbox=r.bbox))
            attach_stacked(runs)
            frames = detect_boxes_and_frames(runs, page.rects)
            pages_runs.append((pno, runs, frames))

    rec = DrawingRecord(id=did, file_name=path.name, sha256=sha, pages=n_pages, text_available=any_text,
                        extractor_version=EXTRACTOR_VERSION,
                        extracted_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                        title_block=title)
    if not any_text:
        rec.messages.append("No vector text found in the PDF (scanned image or text converted to outlines). "
                            "Automatic reading is not possible; enter the dimensions manually.")
        return rec
    unit = first(title, "unit")
    general = first(title, "general_tolerance")
    if unit is None:
        rec.messages.append("Drawing unit not found in the title block: every dimension stays ambiguous until "
                            "the unit is confirmed.")
    else:
        rec.messages.append(f"Unit '{unit}' read from the title block — confirm it before linking values.")
    if general:
        rec.messages.append(f"General tolerance note '{general}' found — applies to untoleranced dimensions only "
                            "after confirmation.")

    n = 0
    for pno, runs, frames in pages_runs:
        for r in runs:
            if r.consumed:
                continue
            text = r.text.strip()
            if r.stacked:
                text = f"{text} {r.stacked[0]}/{r.stacked[1]}"
            if not re.search(r"\d", text):
                continue
            status, parsed, issues, cat = parse_callout(text, unit=unit, general_tolerance=general, boxed=r.boxed)
            if cat == "note" and status == "unparsed":
                continue
            if r.rotated:
                issues = issues + ["rotated text — check reading order on the overlay"]
            if parsed is not None and parsed.tolerance_origin == "general" and general is None:
                status = "ambiguous"
            n += 1
            rec.callouts.append(ExtractedCallout(id=f"{did}-C{n:03d}", page=pno, bbox=r.bbox, raw_text=text,
                                                 category=cat, status=status, parsed=parsed, issues=issues))
        for fr in frames:
            n += 1
            rec.callouts.append(_frame_callout(f"{did}-C{n:03d}", pno, fr, unit))
    return rec


def _frame_callout(cid: str, page: int, fr, unit: Optional[str]) -> ExtractedCallout:
    cells = [" ".join(t) for t in fr.cells]
    raw = " | ".join(c if c.strip() else "[graphic symbol]" for c in cells)
    if cells and cells[0].strip():
        status, parsed, issues, _ = parse_callout(raw, unit=unit)
        if status == "unparsed":
            issues = issues + ["feature control frame layout recognised, content not understood"]
            status = "ambiguous"
        return ExtractedCallout(id=cid, page=page, bbox=fr.bbox, raw_text=raw, category="geometric",
                                status=status, parsed=parsed, issues=issues)
    # first cell without text: the characteristic symbol is drawn as graphics
    issues = ["geometric characteristic symbol is graphics, not text — select the tolerance type"]
    parsed = None
    tail = normalize(" ".join(cells[1:])) if len(cells) > 1 else ""
    m = re.match(r"^(Ø)?\s*(" + NUM + r")", tail)
    if m:
        datums = re.findall(r"\b[A-Z]\b", tail[m.end():])
        parsed = ParsedCallout(kind="geometric", geometric_value=float(m.group(2)), diameter_zone=bool(m.group(1)),
                               datums=datums, unit=unit)
    else:
        issues.append("tolerance value not readable")
    return ExtractedCallout(id=cid, page=page, bbox=fr.bbox, raw_text=raw or "(frame)", category="geometric",
                            status="ambiguous", parsed=parsed, issues=issues)
