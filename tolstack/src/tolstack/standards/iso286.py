"""ISO 286-1/-2: tolerance classes -> limit deviations, nominal sizes 0 < D <= 500 mm.

Scope implemented (anything else raises UnsupportedFeature — no estimate is ever produced):
  * standard tolerance grades IT1 ... IT18 (IT14–IT18 only above 1 mm, as in ISO 286-1)
  * shafts: d e f g h js k m n p r s
  * holes:  D E F G H JS K M N P R S
      - K, M, N only for grades <= IT8; P, R, S use the Δ rule for grades <= IT7 and ES = -ei above.
Values in µm, transcribed from ISO 286-1:2010 Tables 1–3; verified in tests/test_iso286.py against
published limit values. Size ranges are "above lower, up to and including upper".
"""

from __future__ import annotations

import re
from bisect import bisect_left

from ..errors import UnsupportedFeature

# upper bounds of the main size ranges (mm)
_RANGES = [3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500]

_IT = {  # µm, per main range
    1: [0.8, 1, 1, 1.2, 1.5, 1.5, 2, 2.5, 3.5, 4.5, 6, 7, 8],
    2: [1.2, 1.5, 1.5, 2, 2.5, 2.5, 3, 4, 5, 7, 8, 9, 10],
    3: [2, 2.5, 2.5, 3, 4, 4, 5, 6, 8, 10, 12, 13, 15],
    4: [3, 4, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20],
    5: [4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27],
    6: [6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40],
    7: [10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63],
    8: [14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97],
    9: [25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155],
    10: [40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250],
    11: [60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400],
    12: [100, 120, 150, 180, 210, 250, 300, 350, 400, 460, 520, 570, 630],
    13: [140, 180, 220, 270, 330, 390, 460, 540, 630, 720, 810, 890, 970],
    14: [250, 300, 360, 430, 520, 620, 740, 870, 1000, 1150, 1300, 1400, 1550],
    15: [400, 480, 580, 700, 840, 1000, 1200, 1400, 1600, 1850, 2100, 2300, 2500],
    16: [600, 750, 900, 1100, 1300, 1600, 1900, 2200, 2500, 2900, 3200, 3600, 4000],
    17: [1000, 1200, 1500, 1800, 2100, 2500, 3000, 3500, 4000, 4600, 5200, 5700, 6300],
    18: [1400, 1800, 2200, 2700, 3300, 3900, 4600, 5400, 6300, 7200, 8100, 8900, 9700],
}

# Shaft upper fundamental deviations es (µm), main ranges
_ES = {
    "d": [-20, -30, -40, -50, -65, -80, -100, -120, -145, -170, -190, -210, -230],
    "e": [-14, -20, -25, -32, -40, -50, -60, -72, -85, -100, -110, -125, -135],
    "f": [-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68],
    "g": [-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20],
    "h": [0] * 13,
}

# Shaft lower fundamental deviations ei (µm), main ranges
_EI = {
    # k: value valid for grades IT4..IT7; 0 for <= IT3 and > IT7 (handled in code)
    "k": [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5],
    "m": [2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23],
    "n": [4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40],
    "p": [6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68],
}

# r and s use intermediate ranges above 50 mm: (upper bound mm, ei µm)
_EI_FINE = {
    "r": [(3, 10), (6, 15), (10, 19), (18, 23), (30, 28), (50, 34), (65, 41), (80, 43), (100, 51),
          (120, 54), (140, 63), (160, 65), (180, 68), (200, 77), (225, 80), (250, 84), (280, 94),
          (315, 98), (355, 108), (400, 114), (450, 126), (500, 132)],
    "s": [(3, 14), (6, 19), (10, 23), (18, 28), (30, 35), (50, 43), (65, 53), (80, 59), (100, 71),
          (120, 79), (140, 92), (160, 100), (180, 108), (200, 122), (225, 130), (250, 140), (280, 158),
          (315, 170), (355, 190), (400, 208), (450, 232), (500, 252)],
}

# Δ (µm) for holes K..ZC, columns IT3..IT8, main ranges
_DELTA = [
    [0, 0, 0, 0, 0, 0],
    [1, 1.5, 1, 3, 4, 6],
    [1, 1.5, 2, 3, 6, 7],
    [1, 2, 3, 3, 7, 9],
    [1.5, 2, 3, 4, 8, 12],
    [1.5, 3, 4, 5, 9, 14],
    [2, 3, 5, 6, 11, 16],
    [2, 4, 5, 7, 13, 19],
    [3, 4, 6, 7, 15, 23],
    [3, 4, 6, 9, 17, 26],
    [4, 4, 7, 9, 20, 29],
    [4, 5, 7, 11, 21, 32],
    [5, 5, 7, 13, 23, 34],
]

SHAFT_LETTERS = {"d", "e", "f", "g", "h", "js", "k", "m", "n", "p", "r", "s"}
HOLE_LETTERS = {x.upper() for x in SHAFT_LETTERS}

_CLASS_RE = re.compile(r"^(js|JS|[a-zA-Z])(\d{1,2})$")


def _range_index(size_mm: float) -> int:
    if not (0 < size_mm <= 500):
        raise UnsupportedFeature(f"ISO 286 tables implemented for 0 < size <= 500 mm (got {size_mm} mm).")
    return bisect_left(_RANGES, size_mm)


def it_value(grade: int, size_mm: float) -> float:
    """Standard tolerance ITgrade in µm."""
    if grade not in _IT:
        raise UnsupportedFeature(f"IT{grade} not implemented (IT1..IT18).")
    if grade >= 14 and size_mm <= 1:
        raise UnsupportedFeature(f"IT{grade} is not defined for sizes up to 1 mm (ISO 286-1).")
    return float(_IT[grade][_range_index(size_mm)])


def _fine(letter: str, size_mm: float) -> float:
    _range_index(size_mm)
    for upper, val in _EI_FINE[letter]:
        if size_mm <= upper:
            return float(val)
    raise UnsupportedFeature(f"Size {size_mm} outside table for '{letter}'.")  # pragma: no cover


def _shaft_ei_fundamental(letter: str, grade: int, size_mm: float) -> float:
    i = _range_index(size_mm)
    if letter == "k":
        return float(_EI["k"][i]) if 4 <= grade <= 7 else 0.0
    if letter in _EI:
        return float(_EI[letter][i])
    if letter in _EI_FINE:
        return _fine(letter, size_mm)
    raise KeyError(letter)


def _js_half(grade: int, size_mm: float) -> float:
    it = it_value(grade, size_mm)
    # ISO 286-1: for IT7..IT11 an odd IT value (in µm) is rounded down to the nearest even value.
    if 7 <= grade <= 11 and float(it).is_integer() and int(it) % 2 == 1:
        it -= 1
    return it / 2.0


def parse_class(designation: str) -> tuple[str, int]:
    m = _CLASS_RE.match(designation.strip())
    if not m:
        raise UnsupportedFeature(f"'{designation}' is not a tolerance class designation (e.g. H7, g6, js6).")
    return m.group(1), int(m.group(2))


def deviations_um(designation: str, size_mm: float) -> tuple[float, float]:
    """Return (upper, lower) deviation in µm for a tolerance class such as 'H7' or 'g6'."""
    letter, grade = parse_class(designation)
    it = it_value(grade, size_mm)
    is_hole = letter[0].isupper()
    lt = letter.lower()
    if lt not in SHAFT_LETTERS:
        raise UnsupportedFeature(
            f"Fundamental deviation '{letter}' not implemented in Phase 1 "
            f"(holes: {sorted(HOLE_LETTERS)}, shafts: {sorted(SHAFT_LETTERS)}).")
    if lt == "js":
        h = _js_half(grade, size_mm)
        return h, -h

    if not is_hole:
        if lt in _ES:
            es = float(_ES[lt][_range_index(size_mm)])
            return es, es - it
        ei = _shaft_ei_fundamental(lt, grade, size_mm)
        return ei + it, ei

    # holes
    if lt in _ES:  # D..H: EI = -es
        EI = -float(_ES[lt][_range_index(size_mm)])
        return EI + it, EI
    i = _range_index(size_mm)
    if lt in ("k", "m", "n"):
        if grade > 8:
            raise UnsupportedFeature(f"Hole {letter}{grade}: grades above IT8 not implemented for K/M/N.")
        if grade < 3:
            raise UnsupportedFeature(f"Hole {letter}{grade}: Δ defined for IT3..IT8 only.")
        delta = _DELTA[i][grade - 3]
        ei_shaft = _EI["k"][i] if lt == "k" else _EI[lt][i]  # k value for IT4..IT7 per ISO rule
        if lt == "k" and size_mm <= 3:
            delta = 0.0
        ES = -float(ei_shaft) + delta
        return ES, ES - it
    # P, R, S
    ei_shaft = _shaft_ei_fundamental(lt, grade, size_mm)
    if grade <= 7:
        if grade < 3:
            raise UnsupportedFeature(f"Hole {letter}{grade}: Δ defined for IT3..IT8 only.")
        ES = -ei_shaft + _DELTA[i][grade - 3]
    else:
        ES = -ei_shaft
    return ES, ES - it


def deviations_mm(designation: str, size_mm: float) -> tuple[float, float]:
    up, lo = deviations_um(designation, size_mm)
    return round(up / 1000.0, 9) + 0.0, round(lo / 1000.0, 9) + 0.0
