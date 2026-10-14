"""Worst-Case analysis of a linear 1D chain: y = Σ sᵢ·(nomᵢ + δᵢ), δᵢ ∈ [lowerᵢ, upperᵢ].

For a linear function on a box the extrema are attained at vertices, so interval arithmetic gives the
exact bounds: each term independently takes the limit that minimises (maximises) sᵢ·δᵢ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..validation.chain_checks import ResolvedTerm


@dataclass
class WorstCaseResult:
    nominal: float
    minimum: float
    maximum: float
    governing_min: dict[str, str]  # contributor -> "upper"/"lower" limit used
    governing_max: dict[str, str]
    exact: bool
    statement: str
    meets_lsl: Optional[bool] = None
    meets_usl: Optional[bool] = None
    notes: list[str] = field(default_factory=list)

    @property
    def range(self) -> float:
        return self.maximum - self.minimum

    def as_dict(self) -> dict:
        return {"nominal": self.nominal, "minimum": self.minimum, "maximum": self.maximum, "range": self.range,
                "governing_min": self.governing_min, "governing_max": self.governing_max, "exact": self.exact,
                "statement": self.statement, "meets_lsl": self.meets_lsl, "meets_usl": self.meets_usl,
                "notes": self.notes}


def worst_case(terms: list[ResolvedTerm], lsl: Optional[float] = None, usl: Optional[float] = None) -> WorstCaseResult:
    y0 = sum(t.sensitivity * t.nominal for t in terms)
    ymin, ymax = y0, y0
    gmin, gmax = {}, {}
    for t in terms:
        a, b = t.sensitivity * t.upper, t.sensitivity * t.lower
        if a >= b:
            ymax += a; gmax[t.contributor_id] = "upper"
            ymin += b; gmin[t.contributor_id] = "lower"
        else:
            ymax += b; gmax[t.contributor_id] = "lower"
            ymin += a; gmin[t.contributor_id] = "upper"
    bounded_terms = [t.contributor_id for t in terms if t.kind == "geometric"]
    exact = not bounded_terms
    if exact:
        statement = ("Exact extrema of the linear chain over the permitted deviations "
                     "(vertex enumeration of a linear function on a box).")
    else:
        statement = (f"Conservative bounds: terms {bounded_terms} are upper bounds of a geometric effect, so "
                     "the extreme values may not be physically attainable.")
    return WorstCaseResult(
        y0, ymin, ymax, gmin, gmax, exact, statement,
        meets_lsl=None if lsl is None else ymin >= lsl - 1e-12,
        meets_usl=None if usl is None else ymax <= usl + 1e-12,
    )
