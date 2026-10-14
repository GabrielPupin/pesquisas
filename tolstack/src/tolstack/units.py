"""Length units. Conversion is explicit; unknown or ambiguous spellings are rejected."""

from __future__ import annotations

from .errors import UnitError

# factor to millimetres
_LENGTH_TO_MM = {
    "mm": 1.0,
    "um": 1e-3,
    "in": 25.4,
}

_ALIASES = {
    "mm": "mm",
    "millimeter": "mm",
    "millimetre": "mm",
    "um": "um",
    "µm": "um",  # micro sign
    "μm": "um",  # greek mu
    "micron": "um",
    "in": "in",
    "inch": "in",
}

ANGULAR_UNITS = {"deg", "°", "rad", "arcmin", "arcsec"}


def normalize_unit(unit: str) -> str:
    """Return the canonical spelling of a length unit or raise UnitError."""
    if unit is None:
        raise UnitError("Unit is required; no default unit is assumed.")
    key = unit.strip().lower()
    if key in ANGULAR_UNITS:
        raise UnitError(f"'{unit}' is an angular unit; linear 1D chains accept only length units.")
    if key not in _ALIASES:
        raise UnitError(f"Unknown or ambiguous unit '{unit}'. Accepted: mm, um/µm, in.")
    return _ALIASES[key]


def convert(value: float, from_unit: str, to_unit: str) -> float:
    f = normalize_unit(from_unit)
    t = normalize_unit(to_unit)
    return value * _LENGTH_TO_MM[f] / _LENGTH_TO_MM[t]


def factor(from_unit: str, to_unit: str) -> float:
    return convert(1.0, from_unit, to_unit)
