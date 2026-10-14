"""ISO 286 and ISO 2768-1 against published values."""

import pytest

from tolstack.errors import UnsupportedFeature
from tolstack.standards.iso286 import deviations_mm, deviations_um, it_value
from tolstack.standards.iso2768 import angular_tolerance_deg, linear_tolerance_mm

# (class, size mm, upper µm, lower µm) — published ISO 286-2 limit deviations
KNOWN = [
    ("H7", 20, 21, 0), ("g6", 20, -7, -20), ("k6", 50, 18, 2), ("P7", 25, -14, -35), ("H8", 50, 39, 0),
    ("f7", 30, -20, -41), ("h6", 10, 0, -9), ("js6", 20, 6.5, -6.5), ("js7", 20, 10, -10), ("K7", 20, 6, -15),
    ("M7", 20, 0, -21), ("N7", 20, -7, -28), ("R7", 20, -20, -41), ("S7", 20, -27, -48), ("F7", 20, 41, 20),
    ("G7", 20, 28, 7), ("E8", 40, 89, 50), ("D9", 40, 142, 80), ("n6", 20, 28, 15), ("p6", 25, 35, 22),
    ("r6", 60, 60, 41), ("s6", 100, 93, 71), ("m6", 40, 25, 9), ("e8", 40, -50, -89), ("d9", 40, -80, -142),
    ("H11", 100, 220, 0), ("h9", 3, 0, -25), ("K6", 3, 0, -6), ("N7", 2, -4, -14),
]


@pytest.mark.parametrize("cls,size,up,lo", KNOWN)
def test_iso286_known_values(cls, size, up, lo):
    u, l = deviations_um(cls, size)
    assert (u, l) == (pytest.approx(up), pytest.approx(lo))


def test_iso286_mm_and_range_boundaries():
    assert deviations_mm("H7", 18) == (0.018, 0.0)  # 18 belongs to 10–18
    assert deviations_mm("H7", 18.001) == (0.021, 0.0)
    assert it_value(7, 500) == 63


@pytest.mark.parametrize("cls,size", [("x7", 20), ("ZC7", 20), ("H7", 600), ("H7", 0), ("K9", 20), ("H19", 20),
                                      ("IT7", 20), ("H14", 0.5)])
def test_iso286_unsupported_is_explicit(cls, size):
    with pytest.raises(UnsupportedFeature):
        deviations_um(cls, size)


def test_iso2768():
    assert linear_tolerance_mm("m", 80) == 0.3
    assert linear_tolerance_mm("f", 6) == 0.05
    assert linear_tolerance_mm("c", 150) == 1.2
    assert angular_tolerance_deg("m", 30) == 0.5
    with pytest.raises(UnsupportedFeature):
        linear_tolerance_mm("v", 1)
    with pytest.raises(UnsupportedFeature):
        linear_tolerance_mm("m", 0.2)
