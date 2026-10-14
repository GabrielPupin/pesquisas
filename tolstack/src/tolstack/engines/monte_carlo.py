"""Monte Carlo simulation of a 1D chain.

Sampling: z ~ N(0, R) via a factor L with L Lᵀ = R (Gaussian copula); each deviation δᵢ = Fᵢ⁻¹(Φ(zᵢ)).
For normal marginals the Pearson correlation equals R exactly; for other marginals R is the
correlation of the normal scores (the achieved Pearson correlation is reported).
Each sample evaluates y = Σ sᵢ (nomᵢ + δᵢ). Non-finite results are counted and reported, never dropped
silently. Sample min/max are observations, not worst-case limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Optional

import numpy as np

from ..errors import InsufficientInformation
from ..validation.chain_checks import ResolvedTerm


def wilson_interval(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(1 - (1 - conf) / 2)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return (lo, hi)


@dataclass
class MonteCarloResult:
    n: int
    seed: int
    mean: float
    std: float
    median: float
    percentiles: dict[float, float]
    observed_min: float
    observed_max: float
    n_below: Optional[int]
    n_above: Optional[int]
    ci_below: Optional[tuple[float, float]]
    ci_above: Optional[tuple[float, float]]
    ci_total: Optional[tuple[float, float]]
    confidence: float
    se_mean: float
    convergence: list[dict]
    hist_counts: list[int]
    hist_edges: list[float]
    invalid_samples: int
    invalid_diagnosis: list[str]
    achieved_correlation: Optional[list[list[float]]] = None
    notes: list[str] = field(default_factory=list)
    samples: Optional[np.ndarray] = None

    @property
    def p_below(self):
        return None if self.n_below is None else self.n_below / self.n_valid

    @property
    def p_above(self):
        return None if self.n_above is None else self.n_above / self.n_valid

    @property
    def p_total(self):
        if self.n_below is None and self.n_above is None:
            return None
        return ((self.n_below or 0) + (self.n_above or 0)) / self.n_valid

    @property
    def n_valid(self):
        return self.n - self.invalid_samples

    def as_dict(self) -> dict:
        return {"n": self.n, "seed": self.seed, "mean": self.mean, "std": self.std, "median": self.median,
                "percentiles": {str(k): v for k, v in self.percentiles.items()},
                "observed_min": self.observed_min, "observed_max": self.observed_max,
                "p_below": self.p_below, "p_above": self.p_above, "p_total": self.p_total,
                "ci_below": self.ci_below, "ci_above": self.ci_above, "ci_total": self.ci_total,
                "confidence": self.confidence, "se_mean": self.se_mean, "convergence": self.convergence,
                "invalid_samples": self.invalid_samples, "invalid_diagnosis": self.invalid_diagnosis,
                "notes": self.notes}


def _factor(R: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        w, V = np.linalg.eigh(R)  # PSD but singular (e.g. rho = ±1)
        return V @ np.diag(np.sqrt(np.clip(w, 0, None)))


def monte_carlo(terms: list[ResolvedTerm], R: Optional[np.ndarray] = None, n: int = 200_000, seed: int = 12345,
                lsl: Optional[float] = None, usl: Optional[float] = None,
                percentiles=(0.135, 1, 5, 50, 95, 99, 99.865), confidence: float = 0.95,
                keep_samples: bool = True, batch: int = 250_000) -> MonteCarloResult:
    m = len(terms)
    for t in terms:
        if t.distribution is None and t.width != 0:
            raise InsufficientInformation(f"No distribution for '{t.contributor_id}'.")
    if R is None:
        R = np.eye(m)
    L = _factor(R)
    rng = np.random.default_rng(seed)
    s = np.array([t.sensitivity for t in terms])
    y0 = float(sum(t.sensitivity * t.nominal for t in terms))
    correlated = not np.allclose(R, np.eye(m))

    ys = np.empty(n)
    dev_sums = np.zeros(m); dev_sq = np.zeros((m, m)); cnt = 0
    done = 0
    while done < n:
        b = min(batch, n - done)
        z = rng.standard_normal((b, m)) @ L.T
        dev = np.empty((b, m))
        for i, t in enumerate(terms):
            dev[:, i] = t.distribution.from_z(z[:, i]) if t.distribution is not None else t.lower
        ys[done:done + b] = y0 + dev @ s
        if correlated:
            dev_sums += dev.sum(axis=0); dev_sq += dev.T @ dev; cnt += b
        done += b

    finite = np.isfinite(ys)
    invalid = int((~finite).sum())
    diag = []
    if invalid:
        diag.append(f"{invalid} sample(s) produced a non-finite output; check distributions with unbounded "
                    "or degenerate parameters. They are excluded from statistics and counted here.")
    y = ys[finite]
    nv = y.size
    pct = {p: float(np.percentile(y, p)) for p in percentiles}
    nb = int((y < lsl).sum()) if lsl is not None else None
    na = int((y > usl).sum()) if usl is not None else None
    ci_b = wilson_interval(nb, nv, confidence) if nb is not None else None
    ci_a = wilson_interval(na, nv, confidence) if na is not None else None
    ci_t = wilson_interval((nb or 0) + (na or 0), nv, confidence) if (nb is not None or na is not None) else None

    conv = []
    k = 1000
    checkpoints = []
    while k < nv:
        checkpoints.append(k); k *= 2
    checkpoints.append(nv)
    for c in checkpoints:
        yc = y[:c]
        fails = ((yc < lsl).sum() if lsl is not None else 0) + ((yc > usl).sum() if usl is not None else 0)
        conv.append({"n": int(c), "mean": float(yc.mean()), "std": float(yc.std(ddof=1)),
                     "p_fail": float(fails / c) if (lsl is not None or usl is not None) else None})
    counts, edges = np.histogram(y, bins=60)
    ach = None
    if correlated and cnt > 1:
        mean_d = dev_sums / cnt
        cov = dev_sq / cnt - np.outer(mean_d, mean_d)
        sd = np.sqrt(np.clip(np.diag(cov), 1e-300, None))
        ach = (cov / np.outer(sd, sd)).round(4).tolist()
    notes = ["Observed min/max are sample extremes, not guaranteed worst-case limits."]
    if ci_t is not None and (nb or 0) + (na or 0) == 0:
        notes.append(f"No nonconforming sample in {nv}; the probability is below the upper confidence bound "
                     f"{ci_t[1]:.3g}, not zero.")
    std = float(y.std(ddof=1))
    return MonteCarloResult(
        n, seed, float(y.mean()), std, float(np.median(y)), pct, float(y.min()), float(y.max()),
        nb, na, ci_b, ci_a, ci_t, confidence, std / math.sqrt(nv), conv, counts.tolist(), edges.tolist(),
        invalid, diag, ach, notes, y if keep_samples else None)
