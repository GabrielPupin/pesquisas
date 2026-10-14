"""ISO 2768-1 general tolerances for linear and angular dimensions (classes f, m, c, v).

Applied only to drawing dimensions without an individual tolerance, and only when the engineer has
confirmed the general-tolerance note of that drawing.
"""

from __future__ import annotations

from ..errors import UnsupportedFeature

# (lower exclusive bound, upper inclusive bound) in mm; first range is 0.5 .. 3 inclusive of 0.5
_LIN_RANGES = [(0.5, 3), (3, 6), (6, 30), (30, 120), (120, 400), (400, 1000), (1000, 2000), (2000, 4000)]
_LIN = {  # ± mm
    "f": [0.05, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, None],
    "m": [0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0],
    "c": [0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0, 4.0],
    "v": [None, 0.5, 1.0, 1.5, 2.5, 4.0, 6.0, 8.0],
}

# angular: by length of the shorter leg (mm); values in degrees (±)
_ANG_RANGES = [10, 50, 120, 400, float("inf")]
_ANG = {
    "f": [1.0, 0.5, 20 / 60, 10 / 60, 5 / 60],
    "m": [1.0, 0.5, 20 / 60, 10 / 60, 5 / 60],
    "c": [1.5, 1.0, 0.5, 15 / 60, 10 / 60],
    "v": [3.0, 2.0, 1.0, 0.5, 20 / 60],
}


def linear_tolerance_mm(cls: str, size_mm: float) -> float:
    c = cls.lower()
    if c not in _LIN:
        raise UnsupportedFeature(f"ISO 2768-1 class '{cls}' unknown (f, m, c, v).")
    if size_mm < 0.5:
        raise UnsupportedFeature("ISO 2768-1 linear general tolerances start at 0.5 mm; the drawing must "
                                 "state the tolerance for smaller sizes.")
    for (lo, hi), val in zip(_LIN_RANGES, _LIN[c]):
        if size_mm <= hi:
            if val is None:
                raise UnsupportedFeature(f"ISO 2768-{c}: no general tolerance for {size_mm} mm.")
            return val
    raise UnsupportedFeature(f"ISO 2768-1 linear table ends at 4000 mm (got {size_mm}).")


def angular_tolerance_deg(cls: str, shorter_leg_mm: float) -> float:
    c = cls.lower()
    if c not in _ANG:
        raise UnsupportedFeature(f"ISO 2768-1 class '{cls}' unknown (f, m, c, v).")
    for hi, val in zip(_ANG_RANGES, _ANG[c]):
        if shorter_leg_mm <= hi:
            return val
    raise UnsupportedFeature("unreachable")  # pragma: no cover
