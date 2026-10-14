"""Probability distributions of a contributor's deviation (value - nominal), in the contributor's unit.

A distribution is never inferred from a tolerance band. It is either declared per contributor or produced
by an explicitly configured project-level assumption (see ``StatisticalAssumption``), which is then
recorded as an assumption in every result that uses it.

All distributions sample through the inverse CDF of a standard-normal score ``z``. This gives a single
code path for independent and correlated sampling (Gaussian copula, see docs/formulation.md).
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Union

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..errors import ModelError

_erfc = np.vectorize(math.erfc, otypes=[float])


def norm_cdf(z: np.ndarray) -> np.ndarray:
    return 0.5 * _erfc(-np.asarray(z, dtype=float) / math.sqrt(2.0))


def norm_ppf(p: np.ndarray) -> np.ndarray:
    """Inverse standard normal CDF. Acklam rational approximation + one Halley refinement (|err| < 1e-12)."""
    p = np.asarray(p, dtype=float)
    if np.any((p <= 0) | (p >= 1)):
        raise ValueError("norm_ppf requires 0 < p < 1")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    x = np.empty_like(p)
    lo = p < plow
    hi = p > phigh
    mid = ~(lo | hi)
    if lo.any():
        q = np.sqrt(-2 * np.log(p[lo]))
        x[lo] = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if hi.any():
        q = np.sqrt(-2 * np.log(1 - p[hi]))
        x[hi] = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                 ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if mid.any():
        q = p[mid] - 0.5
        r = q * q
        x[mid] = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
                 (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    # Halley refinement
    e = norm_cdf(x) - p
    u = e * math.sqrt(2 * math.pi) * np.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


class _Base(BaseModel):
    model_config = {"extra": "forbid"}

    def mean(self) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    def std(self) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    def from_z(self, z: np.ndarray) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    def support(self) -> tuple[float, float]:
        return (-math.inf, math.inf)

    def describe(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError


class Normal(_Base):
    kind: Literal["normal"] = "normal"
    mu: float
    sigma: float = Field(gt=0)

    def mean(self):
        return self.mu

    def std(self):
        return self.sigma

    def from_z(self, z):
        return self.mu + self.sigma * z

    def describe(self):
        return f"Normal(μ={self.mu:g}, σ={self.sigma:g})"


class Uniform(_Base):
    kind: Literal["uniform"] = "uniform"
    low: float
    high: float

    @model_validator(mode="after")
    def _check(self):
        if not self.high > self.low:
            raise ModelError("Uniform: high must be > low")
        return self

    def mean(self):
        return 0.5 * (self.low + self.high)

    def std(self):
        return (self.high - self.low) / math.sqrt(12.0)

    def from_z(self, z):
        return self.low + (self.high - self.low) * norm_cdf(z)

    def support(self):
        return (self.low, self.high)

    def describe(self):
        return f"Uniform[{self.low:g}, {self.high:g}]"


class Triangular(_Base):
    kind: Literal["triangular"] = "triangular"
    low: float
    mode: float
    high: float

    @model_validator(mode="after")
    def _check(self):
        if not (self.low <= self.mode <= self.high and self.high > self.low):
            raise ModelError("Triangular: require low <= mode <= high and high > low")
        return self

    def mean(self):
        return (self.low + self.mode + self.high) / 3.0

    def std(self):
        a, c, b = self.low, self.mode, self.high
        return math.sqrt((a * a + b * b + c * c - a * b - a * c - b * c) / 18.0)

    def from_z(self, z):
        a, c, b = self.low, self.mode, self.high
        u = norm_cdf(z)
        fc = (c - a) / (b - a)
        left = a + np.sqrt(u * (b - a) * (c - a))
        right = b - np.sqrt((1 - u) * (b - a) * (b - c))
        return np.where(u < fc, left, right)

    def support(self):
        return (self.low, self.high)

    def describe(self):
        return f"Triangular({self.low:g}, {self.mode:g}, {self.high:g})"


class TruncatedNormal(_Base):
    kind: Literal["truncated_normal"] = "truncated_normal"
    mu: float
    sigma: float = Field(gt=0)
    low: float
    high: float

    @model_validator(mode="after")
    def _check(self):
        if not self.high > self.low:
            raise ModelError("TruncatedNormal: high must be > low")
        return self

    def _ab(self):
        return (self.low - self.mu) / self.sigma, (self.high - self.mu) / self.sigma

    def mean(self):
        a, b = self._ab()
        Z = float(norm_cdf(b) - norm_cdf(a))
        pa, pb = _pdf(a), _pdf(b)
        return self.mu + self.sigma * (pa - pb) / Z

    def std(self):
        a, b = self._ab()
        Z = float(norm_cdf(b) - norm_cdf(a))
        pa, pb = _pdf(a), _pdf(b)
        t1 = (a * pa - b * pb) / Z
        t2 = ((pa - pb) / Z) ** 2
        return self.sigma * math.sqrt(1 + t1 - t2)

    def from_z(self, z):
        a, b = self._ab()
        Fa, Fb = float(norm_cdf(a)), float(norm_cdf(b))
        u = norm_cdf(z)
        p = np.clip(Fa + u * (Fb - Fa), 1e-15, 1 - 1e-15)
        return np.clip(self.mu + self.sigma * norm_ppf(p), self.low, self.high)

    def support(self):
        return (self.low, self.high)

    def describe(self):
        return f"TruncNormal(μ={self.mu:g}, σ={self.sigma:g}, [{self.low:g}, {self.high:g}])"


class Empirical(_Base):
    """User-defined distribution from measured deviations (e.g. inspection data). Sampled by linear
    interpolation of the empirical quantile function."""

    kind: Literal["empirical"] = "empirical"
    samples: list[float] = Field(min_length=10)
    source: str = ""

    def mean(self):
        return float(np.mean(self.samples))

    def std(self):
        return float(np.std(self.samples, ddof=1))

    def from_z(self, z):
        return np.quantile(np.asarray(self.samples, dtype=float), norm_cdf(z))

    def support(self):
        return (min(self.samples), max(self.samples))

    def describe(self):
        return f"Empirical(n={len(self.samples)}{', ' + self.source if self.source else ''})"


def _pdf(x: float) -> float:
    if math.isinf(x):
        return 0.0
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


Distribution = Annotated[
    Union[Normal, Uniform, Triangular, TruncatedNormal, Empirical], Field(discriminator="kind")
]


class StatisticalAssumption(BaseModel):
    """Project-level, explicitly configured rule for contributors that have no declared distribution.

    ``none``                   -> no inference; such contributors make RSS/Monte Carlo unavailable.
    ``normal_k_sigma``         -> Normal centred on the tolerance midpoint, half-band = k·σ.
    ``uniform_over_tolerance`` -> Uniform over [lower, upper].
    The rule is never applied to geometric (form) contributors; those need a declared distribution.
    """

    model_config = {"extra": "forbid"}
    rule: Literal["none", "normal_k_sigma", "uniform_over_tolerance"] = "none"
    k: float = Field(default=3.0, gt=0)

    def describe(self) -> str:
        if self.rule == "normal_k_sigma":
            return (f"Assumed: deviations Normal, centred on tolerance midpoint, tolerance half-band = "
                    f"{self.k:g}σ (not measured process data).")
        if self.rule == "uniform_over_tolerance":
            return "Assumed: deviations Uniform over the full tolerance band (not measured process data)."
        return "No statistical assumption configured."

    def apply(self, lower: float, upper: float):
        if self.rule == "normal_k_sigma":
            half = 0.5 * (upper - lower)
            if half <= 0:
                return None
            return Normal(mu=0.5 * (upper + lower), sigma=half / self.k)
        if self.rule == "uniform_over_tolerance":
            if upper <= lower:
                return None
            return Uniform(low=lower, high=upper)
        return None
