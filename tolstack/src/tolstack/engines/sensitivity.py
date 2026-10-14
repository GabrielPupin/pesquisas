"""Sensitivity and contribution ranking.

Physical sensitivity  sᵢ = ∂y/∂xᵢ (how strongly the output responds to the contributor).
Worst-case share      |sᵢ|·Tᵢ / Σ|sⱼ|·Tⱼ (share of the worst-case range).
Statistical share     sᵢ·(Σ s)ᵢ / σ_y² (share of output variance; with correlation it can be negative).
A large sensitivity with a capable process can contribute little variance, and vice versa — both are
reported side by side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..validation.chain_checks import ResolvedTerm
from .rss import covariance


@dataclass
class SensitivityRow:
    contributor_id: str
    name: str
    sensitivity: float
    tolerance_width: float
    wc_share: float
    effect_on_min: float
    effect_on_max: float
    sigma: Optional[float]
    variance_share: Optional[float]
    rank: int = 0

    def as_dict(self):
        return self.__dict__.copy()


def sensitivity_table(terms: list[ResolvedTerm], R: Optional[np.ndarray] = None,
                      statistical: bool = True) -> list[SensitivityRow]:
    s = np.array([t.sensitivity for t in terms])
    w = np.array([abs(t.sensitivity) * t.width for t in terms])
    wsum = w.sum()
    var_share = [None] * len(terms)
    sig = [None] * len(terms)
    if statistical:
        C = covariance(terms, R)
        Cs = C @ s
        var = float(s @ Cs)
        if var > 0:
            var_share = list(s * Cs / var)
        sig = [t.distribution.std() if t.distribution is not None else 0.0 for t in terms]
    rows = []
    for i, t in enumerate(terms):
        a, b = t.sensitivity * t.upper, t.sensitivity * t.lower
        rows.append(SensitivityRow(t.contributor_id, t.name, t.sensitivity, t.width,
                                   float(w[i] / wsum) if wsum > 0 else 0.0, min(a, b), max(a, b),
                                   sig[i], None if var_share[i] is None else float(var_share[i])))
    key = (lambda r: -(r.variance_share if r.variance_share is not None else -1)) if statistical and \
        any(r.variance_share is not None for r in rows) else (lambda r: -r.wc_share)
    for rank, r in enumerate(sorted(rows, key=key), start=1):
        r.rank = rank
    return sorted(rows, key=lambda r: r.rank)
