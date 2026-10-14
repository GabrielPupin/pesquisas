"""Dimensional tolerance representation: nominal value with explicit upper/lower deviations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

from ..errors import ModelError

ToleranceOrigin = Literal[
    "bilateral", "unilateral", "limits", "deviations", "basic", "iso286", "iso2768", "geometric", "declared"
]


class ToleranceSpec(BaseModel):
    """nominal + deviations. value ∈ [nominal + lower, nominal + upper]."""

    model_config = {"extra": "forbid"}
    nominal: float
    upper: float
    lower: float
    unit: str
    origin: ToleranceOrigin = "deviations"
    designation: str = ""  # e.g. "H7", "ISO 2768-m", "±0.1" as written on the drawing

    @model_validator(mode="after")
    def _check(self):
        if self.upper < self.lower:
            raise ModelError(f"Upper deviation ({self.upper}) is below lower deviation ({self.lower}).")
        if self.origin == "basic" and (self.upper != 0 or self.lower != 0):
            raise ModelError("A basic (theoretically exact) dimension cannot carry a tolerance.")
        return self

    @property
    def width(self) -> float:
        return self.upper - self.lower

    @property
    def max(self) -> float:
        return self.nominal + self.upper

    @property
    def min(self) -> float:
        return self.nominal + self.lower

    @property
    def midpoint_deviation(self) -> float:
        return 0.5 * (self.upper + self.lower)

    # Constructors -----------------------------------------------------------------------------
    @classmethod
    def bilateral(cls, nominal: float, tol: float, unit: str) -> "ToleranceSpec":
        if tol < 0:
            raise ModelError("Bilateral tolerance must be non-negative.")
        return cls(nominal=nominal, upper=tol, lower=-tol, unit=unit, origin="bilateral", designation=f"±{tol:g}")

    @classmethod
    def deviations(cls, nominal: float, upper: float, lower: float, unit: str) -> "ToleranceSpec":
        origin = "unilateral" if (upper == 0 or lower == 0) and upper != lower else "deviations"
        return cls(nominal=nominal, upper=upper, lower=lower, unit=unit, origin=origin,
                   designation=f"{upper:+g}/{lower:+g}")

    @classmethod
    def limits(cls, minimum: float, maximum: float, unit: str) -> "ToleranceSpec":
        if maximum < minimum:
            raise ModelError("Limit dimension: maximum is below minimum.")
        nom = 0.5 * (minimum + maximum)
        half = 0.5 * (maximum - minimum)
        return cls(nominal=nom, upper=half, lower=-half, unit=unit, origin="limits",
                   designation=f"{minimum:g}/{maximum:g}")

    @classmethod
    def basic(cls, nominal: float, unit: str) -> "ToleranceSpec":
        return cls(nominal=nominal, upper=0.0, lower=0.0, unit=unit, origin="basic", designation=f"[{nominal:g}]")
