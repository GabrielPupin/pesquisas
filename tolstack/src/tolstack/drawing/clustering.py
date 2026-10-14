"""Spatial grouping of PDF text into callout candidates.

Input: words (upright) and characters (rotated) from pdfplumber, plus rectangles.
Output: Runs — pieces of text on one baseline — annotated with stacked deviations, enclosing boxes
(basic dimensions) and feature-control-frame membership. All rules are geometric and deterministic;
thresholds are expressed relative to the font size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_SIGNED = re.compile(r"^[+\-−–]?\s*\d+(?:[.,]\d+)?$|^0$")


@dataclass
class Run:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float
    rotated: bool = False
    stacked: Optional[tuple[str, str]] = None
    boxed: bool = False
    consumed: bool = False
    extra_boxes: list = field(default_factory=list)

    @property
    def bbox(self):
        return (self.x0, self.top, self.x1, self.bottom)

    def union(self, other: "Run"):
        self.x0 = min(self.x0, other.x0); self.top = min(self.top, other.top)
        self.x1 = max(self.x1, other.x1); self.bottom = max(self.bottom, other.bottom)


def words_to_runs(words: list[dict], gap_factor: float = 0.6) -> list[Run]:
    """Join upright words on the same baseline and similar size whose gap is below gap_factor·size."""
    ws = sorted(words, key=lambda w: (round(w["top"], 0), w["x0"]))
    runs: list[Run] = []
    for w in ws:
        size = float(w.get("size", w["bottom"] - w["top"]))
        placed = False
        for r in reversed(runs[-6:]):
            same_line = abs(r.bottom - w["bottom"]) < 0.3 * size and abs(r.size - size) < 0.15 * size
            if same_line and 0 <= w["x0"] - r.x1 < gap_factor * size:
                r.text += " " + w["text"]
                r.x1 = max(r.x1, w["x1"]); r.top = min(r.top, w["top"]); r.bottom = max(r.bottom, w["bottom"])
                placed = True
                break
        if not placed:
            runs.append(Run(w["text"], w["x0"], w["top"], w["x1"], w["bottom"], size))
    return runs


def rotated_chars_to_runs(chars: list[dict]) -> list[Run]:
    """Group non-upright characters (text rotated ±90°) into runs, reading order taken from the text matrix."""
    rot = [c for c in chars if not c.get("upright", True)]
    cols: list[list[dict]] = []
    for c in sorted(rot, key=lambda c: (round(c["x0"], 0), c["top"])):
        for col in cols:
            if abs(col[0]["x0"] - c["x0"]) < 1.0 and abs(col[-1]["top"] - c["top"]) < 3 * c["size"]:
                col.append(c)
                break
        else:
            cols.append([c])
    runs = []
    for col in cols:
        m = col[0].get("matrix") or (0, 1, -1, 0, 0, 0)
        upward = m[1] > 0  # rotated +90°: text reads bottom -> top
        col = sorted(col, key=lambda c: c["top"], reverse=upward)
        text, prev = "", None
        for c in col:
            if prev is not None:
                gap = (prev["top"] - c["bottom"]) if upward else (c["top"] - prev["bottom"])
                if gap > 0.25 * c["size"]:
                    text += " "
            text += c["text"]
            prev = c
        size = max(c["size"] for c in col)
        runs.append(Run(text, min(c["x0"] for c in col), min(c["top"] for c in col),
                        max(c["x1"] for c in col), max(c["bottom"] for c in col), size, rotated=True))
    return runs


def attach_stacked(runs: list[Run]) -> None:
    """Attach two small signed numbers stacked to the right of a nominal as its upper/lower deviations."""
    small = [r for r in runs if _SIGNED.match(r.text.strip()) and not r.rotated]
    for r in runs:
        if r.consumed or r.rotated or not re.search(r"\d$", r.text.strip()):
            continue
        cands = [s for s in small if s is not r and not s.consumed and s.size <= 0.85 * r.size
                 and r.x1 - 0.5 <= s.x0 <= r.x1 + 1.5 * r.size
                 and s.top >= r.top - 0.6 * r.size and s.bottom <= r.bottom + 0.6 * r.size]
        if len(cands) == 2:
            up, lo = sorted(cands, key=lambda s: s.top)
            if up.bottom <= lo.bottom and up.top < lo.top:
                r.stacked = (up.text.strip(), lo.text.strip())
                for s in (up, lo):
                    s.consumed = True
                    r.union(s)


def _group_cells(rects: list[dict], tol: float = 1.0) -> list[list[dict]]:
    """Group rectangles that share top/bottom edges and touch horizontally (feature control frames)."""
    groups: list[list[dict]] = []
    for r in sorted(rects, key=lambda r: (round(r["top"], 0), r["x0"])):
        for g in groups:
            last = g[-1]
            if abs(last["top"] - r["top"]) < tol and abs(last["bottom"] - r["bottom"]) < tol \
                    and abs(last["x1"] - r["x0"]) < tol:
                g.append(r)
                break
        else:
            groups.append([r])
    return groups


def _inside(run: Run, r: dict, margin: float = 0.5) -> bool:
    return run.x0 >= r["x0"] - margin and run.x1 <= r["x1"] + margin and \
        run.top >= r["top"] - margin and run.bottom <= r["bottom"] + margin


@dataclass
class FrameCandidate:
    cells: list[list[str]]  # texts per cell, in x order
    bbox: tuple[float, float, float, float]
    size: float


def detect_boxes_and_frames(runs: list[Run], rects: list[dict]) -> list[FrameCandidate]:
    """Mark basic-dimension boxes and collect feature control frames. Large rectangles (views, borders,
    title blocks) are ignored: a cell must be at most ~3 text heights tall."""
    frames = []
    small_rects = []
    for r in rects:
        h = r["bottom"] - r["top"]
        if h <= 0:
            continue
        hosted = [x for x in runs if _inside(x, r)]
        size = max((x.size for x in hosted), default=None)
        if size is not None and h <= 3.0 * size:
            small_rects.append(r)
    # empty cells (e.g. a characteristic symbol drawn as graphics) adjacent to a text cell of equal height
    for r in rects:
        if r in small_rects:
            continue
        for s in list(small_rects):
            if abs(r["top"] - s["top"]) < 1.0 and abs(r["bottom"] - s["bottom"]) < 1.0 and \
                    (abs(r["x1"] - s["x0"]) < 1.0 or abs(s["x1"] - r["x0"]) < 1.0) and \
                    not any(_inside(x, r) for x in runs):
                small_rects.append(r)
                break
    for g in _group_cells(small_rects):
        cells_runs = [[x for x in runs if _inside(x, cell) and not x.consumed] for cell in g]
        if len(g) == 1:
            hosted = cells_runs[0]
            cell = g[0]
            if len(hosted) == 1 and (cell["x1"] - cell["x0"]) <= (hosted[0].x1 - hosted[0].x0) + 2.5 * hosted[0].size:
                hosted[0].boxed = True
            continue
        texts = [[x.text for x in sorted(cr, key=lambda x: x.x0)] for cr in cells_runs]
        for cr in cells_runs:
            for x in cr:
                x.consumed = True
        size = max((x.size for cr in cells_runs for x in cr), default=10.0)
        frames.append(FrameCandidate(texts, (g[0]["x0"], g[0]["top"], g[-1]["x1"], g[0]["bottom"]), size))
    return frames
