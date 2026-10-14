"""Title-block and general-note recognition (drawing number, revision, unit, general tolerance, standard).

Every value is a candidate until the engineer confirms it.
"""

from __future__ import annotations

import re
from typing import Optional

_PATTERNS = [
    ("drawing_number", re.compile(
        r"^(?:DWG\.?\s*(?:NO\.?|Nº|N°|#)|DRAWING\s*(?:NO\.?|NUMBER)|DESENHO\s*(?:Nº|N°|NO\.?)?)\s*:?\s*(\S+)$", re.I)),
    ("revision", re.compile(r"^(?:REV(?:ISION|ISÃO|ISAO)?\.?)\s*:?\s*([A-Z0-9]{1,3})$", re.I)),
    ("unit", re.compile(r"^(?:UNITS?|UNIDADES?|DIMENSIONS?\s+IN|COTAS\s+EM)\s*:?\s*"
                        r"(MM|IN|INCH|INCHES|MILLIMETERS?|MILLIMETRES?|MIL[IÍ]METROS?)\.?$", re.I)),
]
_GENERAL = re.compile(r"ISO\s*2768\s*-?\s*([FMCV])\s*([HKL])?", re.I)
_ISO8015 = re.compile(r"ISO\s*8015", re.I)
_ASME = re.compile(r"ASME\s*Y\s*14\.5", re.I)
_ENVELOPE = re.compile(r"ISO\s*14405.*(Ⓔ|ⓔ|\(E\))|ENVELOPE\s+REQUIREMENT|REQUISITO\s+DE\s+ENVOLT", re.I)


def _unit(v: str) -> str:
    v = v.lower()
    return "mm" if v.startswith("m") else "in"


def match_title(text: str) -> list[tuple[str, str]]:
    """Return (field, value) candidates found in one text run; empty list if none."""
    t = re.sub(r"\s+", " ", text.strip())
    out = []
    for field, rx in _PATTERNS:
        m = rx.match(t)
        if m:
            out.append((field, _unit(m.group(1)) if field == "unit" else m.group(1)))
    g = _GENERAL.search(t)
    if g:
        out.append(("general_tolerance", f"ISO 2768-{g.group(1).lower()}" + (g.group(2).upper() if g.group(2) else "")))
    if _ENVELOPE.search(t):
        out.append(("size_principle", "envelope"))
    elif _ISO8015.search(t):
        out.append(("standard", "ISO_GPS"))
        out.append(("size_principle", "independency"))
    if _ASME.search(t):
        out.append(("standard", "ASME_Y14.5"))
        out.append(("size_principle", "envelope"))  # ASME Y14.5 Rule #1 unless independency is stated
    return out


def first(cands, field: str) -> Optional[str]:
    for c in cands:
        if c.field == field:
            return c.value
    return None
