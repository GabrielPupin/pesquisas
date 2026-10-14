"""First-order statistical propagation (RSS generalised with covariance).

    mean_y = Σ sᵢ·(nomᵢ + μᵢ)          (μᵢ = mean deviation — captures asymmetric tolerances / shifts)
    σ_y²   = sᵀ Σ s,   Σ = D R D        (D = diag σᵢ, R = correlation matrix)
For independent contributors this reduces to σ_y = sqrt(Σ (sᵢσᵢ)²). Exact for mean and variance of a
linear chain; the failure probability uses a normal approximation of y, which is flagged when any
input is not normal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Optional

import numpy as np

from ..model.distributions import Normal
from ..validation.chain_checks import ResolvedTerm


@dataclass
class RSSResult:
    mean: float
    sigma: float
    k: float
    lower_k: float
    upper_k: float
    p_below: Optional[float]
    p_above: Optional[float]
    output_normal_exact: bool
    notes: list[str] = field(default_factory=list)
    sigmas: dict[str, float] = field(default_factory=dict)

    @property
    def p_total(self) -> Optional[float]:
        if self.p_below is None and self.p_above is None:
            return None
        return (self.p_below or 0.0) + (self.p_above or 0.0)

    def as_dict(self) -> dict:
        return {"mean": self.mean, "sigma": self.sigma, "k": self.k, "lower_k": self.lower_k,
                "upper_k": self.upper_k, "p_below": self.p_below, "p_above": self.p_above,
                "p_total": self.p_total, "output_normal_exact": self.output_normal_exact, "notes": self.notes}


def covariance(terms: list[ResolvedTerm], R: Optional[np.ndarray]) -> np.ndarray:
    sig = np.array([t.distribution.std() if t.distribution is not None else 0.0 for t in terms])
    if R is None:
        R = np.eye(len(terms))
    return np.outer(sig, sig) * R


def rss(terms: list[ResolvedTerm], R: Optional[np.ndarray] = None, k: float = 3.0,
        lsl: Optional[float] = None, usl: Optional[float] = None) -> RSSResult:
    s = np.array([t.sensitivity for t in terms])
    mu = np.array([t.distribution.mean() if t.distribution is not None else t.lower for t in terms])
    nom = np.array([t.nominal for t in terms])
    C = covariance(terms, R)
    mean = float(s @ (nom + mu))
    var = float(s @ C @ s)
    sigma = math.sqrt(max(var, 0.0))
    all_normal = all(isinstance(t.distribution, Normal) or t.distribution is None for t in terms)
    notes = []
    if not all_normal:
        notes.append("Some inputs are not normal: mean and σ are exact for the linear chain, but the "
                     "failure probability assumes a normal output (approximation). Use Monte Carlo for tails.")
    pb = pa = None
    if sigma > 0:
        nd = NormalDist(mean, sigma)
        pb = nd.cdf(lsl) if lsl is not None else None
        pa = 1 - nd.cdf(usl) if usl is not None else None
    else:
        notes.append("Output variance is zero (all contributors fixed).")
        pb = (1.0 if mean < lsl else 0.0) if lsl is not None else None
        pa = (1.0 if mean > usl else 0.0) if usl is not None else None
    return RSSResult(mean, sigma, k, mean - k * sigma, mean + k * sigma, pb, pa, all_normal, notes,
                     {t.contributor_id: (t.distribution.std() if t.distribution else 0.0) for t in terms})
