"""Analytical verification of Worst-Case, RSS and Monte Carlo on linear chains."""

import math
from statistics import NormalDist

import numpy as np
import pytest

from tolstack.analysis import run_analysis
from tolstack.engines.monte_carlo import monte_carlo, wilson_interval
from tolstack.engines.rss import rss
from tolstack.engines.worst_case import worst_case
from tolstack.model import Correlation, Triangular, TruncatedNormal, Uniform
from tolstack.model.distributions import norm_cdf, norm_ppf
from tolstack.validation.chain_checks import diagnose

from helpers import normal, simple_stack


def test_worst_case_simple_axial_stack():
    p = simple_stack([("H", 50, 0.1, -0.1), ("A", 20, 0.05, -0.05), ("B", 29.8, 0.0, -0.1)],
                     lsl=0.0, usl=0.5, nominal=0.2)
    d = diagnose(p)
    assert d.status == "Conditionally Valid"
    wc = worst_case(d.terms, 0.0, 0.5)
    assert wc.nominal == pytest.approx(0.2)
    assert wc.maximum == pytest.approx(0.2 + 0.1 + 0.05 + 0.1)
    assert wc.minimum == pytest.approx(0.2 - 0.1 - 0.05 - 0.0)
    assert wc.governing_max == {"H": "upper", "A": "lower", "B": "lower"}
    assert wc.exact and wc.meets_lsl and wc.meets_usl


def test_asymmetric_tolerances_shift_mean():
    p = simple_stack([("H", 50, 0.2, 0.0), ("A", 49.9, 0.0, -0.1)], rule="normal_k_sigma", k=3)
    r = run_analysis(p, mc_samples=20_000)
    # midpoints: H +0.1, A -0.05 -> mean = 0.1 + 0.1 + 0.05
    assert r.rss.mean == pytest.approx(0.25)
    assert r.rss.sigma == pytest.approx(math.hypot(0.1 / 3, 0.05 / 3))


def test_rss_independent_normals_closed_form():
    p = simple_stack([("H", 50, 0.3, -0.3), ("A", 20, 0.1, -0.1), ("B", 29.8, 0.1, -0.1)],
                     dists={"H": normal(0, 0.1), "A": normal(0.01, 0.03), "B": normal(-0.02, 0.04)},
                     lsl=0.0, usl=0.5)
    d = diagnose(p)
    r = rss(d.terms, d.correlation, 3.0, 0.0, 0.5)
    assert r.mean == pytest.approx(0.2 + 0 - 0.01 + 0.02)
    assert r.sigma == pytest.approx(math.sqrt(0.1 ** 2 + 0.03 ** 2 + 0.04 ** 2))
    nd = NormalDist(r.mean, r.sigma)
    assert r.p_below == pytest.approx(nd.cdf(0.0))
    assert r.p_above == pytest.approx(1 - nd.cdf(0.5))
    assert r.output_normal_exact


def test_rss_with_correlation_matches_hand_calculation():
    p = simple_stack([("H", 50, 0.3, -0.3), ("A", 20, 0.1, -0.1), ("B", 29.8, 0.1, -0.1)],
                     dists={"H": normal(0, 0.1), "A": normal(0, 0.03), "B": normal(0, 0.04)})
    p.correlations = [Correlation(a="A", b="B", rho=0.6), Correlation(a="H", b="A", rho=-0.2)]
    d = diagnose(p)
    r = rss(d.terms, d.correlation)
    s = {"H": 1, "A": -1, "B": -1}
    sg = {"H": 0.1, "A": 0.03, "B": 0.04}
    var = sum((s[i] * sg[i]) ** 2 for i in s) + 2 * (s["A"] * s["B"] * 0.6 * sg["A"] * sg["B"]) \
        + 2 * (s["H"] * s["A"] * -0.2 * sg["H"] * sg["A"])
    assert r.sigma == pytest.approx(math.sqrt(var))
    mc = monte_carlo(d.terms, d.correlation, n=400_000, seed=3)
    assert mc.std == pytest.approx(math.sqrt(var), rel=0.01)
    ach = np.array(mc.achieved_correlation)
    ids = [t.contributor_id for t in d.terms]
    assert ach[ids.index("A"), ids.index("B")] == pytest.approx(0.6, abs=0.01)


def test_monte_carlo_matches_normal_sum():
    p = simple_stack([("H", 50, 0.3, -0.3), ("A", 20, 0.1, -0.1)],
                     dists={"H": normal(0.01, 0.1), "A": normal(0, 0.05)}, lsl=29.8, usl=30.2)
    d = diagnose(p)
    mc = monte_carlo(d.terms, None, n=400_000, seed=11, lsl=29.8, usl=30.2)
    mu, sd = 30.01, math.hypot(0.1, 0.05)
    assert abs(mc.mean - mu) < 4 * mc.se_mean
    assert mc.std == pytest.approx(sd, rel=0.01)
    nd = NormalDist(mu, sd)
    p_exact = nd.cdf(29.8) + 1 - nd.cdf(30.2)
    lo, hi = mc.ci_total
    assert lo <= p_exact <= hi


def test_monte_carlo_uniform_sum_irwin_hall():
    p = simple_stack([("H", 10, 0.1, -0.1), ("A", 3, 0.1, -0.1), ("B", 3, 0.1, -0.1)],
                     dists={k: Uniform(low=-0.1, high=0.1) for k in ("H", "A", "B")})
    d = diagnose(p)
    mc = monte_carlo(d.terms, None, n=300_000, seed=5)
    assert mc.std == pytest.approx(math.sqrt(3 * 0.2 ** 2 / 12), rel=0.01)
    assert d.terms and mc.observed_max <= 4 + 0.3 and mc.observed_min >= 4 - 0.3


def test_monte_carlo_reproducible_with_seed():
    p = simple_stack([("H", 10, 0.1, -0.1), ("A", 3, 0.1, -0.1)], rule="normal_k_sigma")
    d = diagnose(p)
    a = monte_carlo(d.terms, None, n=10_000, seed=42)
    b = monte_carlo(d.terms, None, n=10_000, seed=42)
    c = monte_carlo(d.terms, None, n=10_000, seed=43)
    assert np.array_equal(a.samples, b.samples)
    assert not np.array_equal(a.samples, c.samples)


def test_wilson_interval_zero_failures_is_not_zero():
    lo, hi = wilson_interval(0, 1000)
    assert lo == 0.0 and 0.002 < hi < 0.005


def test_rss_unavailable_without_distributions():
    p = simple_stack([("H", 50, 0.1, -0.1), ("A", 49.8, 0.1, -0.1)], rule="none", lsl=0, usl=1)
    r = run_analysis(p)
    assert r.worst_case is not None
    assert r.rss is None and r.monte_carlo is None
    assert "rss" in r.skipped and "Insufficient information" in r.skipped["rss"]


def test_distribution_numerics():
    z = np.linspace(-6, 6, 101)
    assert np.allclose(norm_ppf(norm_cdf(z)), z, atol=1e-9)
    tn = TruncatedNormal(mu=0.0, sigma=1.0, low=-1.0, high=2.0)
    x = tn.from_z(np.random.default_rng(1).standard_normal(400_000))
    assert x.mean() == pytest.approx(tn.mean(), abs=0.005)
    assert x.std() == pytest.approx(tn.std(), rel=0.01)
    tr = Triangular(low=-0.1, mode=0.02, high=0.1)
    y = tr.from_z(np.random.default_rng(2).standard_normal(400_000))
    assert y.mean() == pytest.approx(tr.mean(), abs=5e-4)
    assert y.std() == pytest.approx(tr.std(), rel=0.01)


def test_sensitivity_shares_sum_to_one(axial_project):
    r = run_analysis(axial_project, "A", mc_samples=5_000)
    assert sum(x.wc_share for x in r.sensitivity) == pytest.approx(1.0)
    assert sum(x.variance_share for x in r.sensitivity) == pytest.approx(1.0)
    assert [x.rank for x in r.sensitivity] == [1, 2, 3, 4]


def test_what_if_tighter_tolerance_reduces_sigma(axial_project):
    from tolstack.analysis import what_if
    w = what_if(axial_project, "H", upper=0.05, lower=-0.05, chain_id="A", mc_samples=5_000)
    assert w["modified"]["rss_sigma"] < w["baseline"]["rss_sigma"]
    assert w["modified"]["wc_max"] == pytest.approx(w["baseline"]["wc_max"] - 0.05)
