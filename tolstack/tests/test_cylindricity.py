"""Cylindricity in a diametral fit: envelope vs independency, double counting, scope limits."""

import pytest

from tolstack.analysis import run_analysis
from tolstack.engines.monte_carlo import monte_carlo
from tolstack.model import Chain
from tolstack.validation.chain_checks import diagnose


def _check(d, cid):
    return next(c for c in d.checks if c.id == cid)


def test_size_only_fit_h7_g6(fit_project):
    fit_project.chains = [Chain(id="S", contributor_ids=["D_BORE", "D_SHAFT"])]
    for g in fit_project.geometric_tolerances:
        g.size_principle = "envelope"  # form contained in size -> correctly not in chain
    r = run_analysis(fit_project, "S", mc_samples=5_000)
    assert r.worst_case.minimum == pytest.approx(0.007)
    assert r.worst_case.maximum == pytest.approx(0.041)
    assert r.worst_case.exact


def test_independency_reduces_min_clearance_by_both_cylindricities(fit_project):
    r = run_analysis(fit_project, "FIT", mc_samples=5_000)
    assert r.worst_case.minimum == pytest.approx(0.007 - 0.010)
    assert r.worst_case.maximum == pytest.approx(0.041)
    assert not r.worst_case.exact  # bound, not attained value
    assert any("conservative bound" in a for a in r.diagnosis.assumptions)


def test_envelope_plus_cylindricity_is_double_counting(fit_project):
    fit_project.geometric_tolerances[0].size_principle = "envelope"
    d = diagnose(fit_project, "FIT")
    assert d.status == "Invalid"
    assert "double-counts" in " ".join(_check(d, "TOPO").details)


def test_undeclared_size_principle_is_insufficient(fit_project):
    fit_project.geometric_tolerances[1].size_principle = None
    d = diagnose(fit_project, "FIT")
    assert d.status == "Insufficient Information"
    assert any("Size principle" in m for m in d.missing_information)


def test_omitting_cylindricity_under_independency_is_detected(fit_project):
    fit_project.chains = [Chain(id="S", contributor_ids=["D_BORE", "D_SHAFT"])]
    d = diagnose(fit_project, "S")
    assert d.status == "Invalid"
    assert _check(d, "MISSING").outcome == "failed"


def test_cylindricity_rejected_in_axial_chain(axial_project, fit_project):
    axial_project.geometric_tolerances = fit_project.geometric_tolerances[:1]
    axial_project.geometric_tolerances[0].feature_id = "SP_L"
    from tolstack.model import Contributor
    axial_project.contributors.append(Contributor(id="CYL", kind="geometric", geometric_id="G1"))
    axial_project.chains.append(Chain(id="X", contributor_ids=["B2", "S", "B1", "H", "CYL"]))
    d = diagnose(axial_project, "X")
    assert d.status == "Invalid"
    assert "not a distance along the stack axis" in " ".join(_check(d, "KIND").details)


def test_other_geometric_types_not_propagated(fit_project):
    fit_project.geometric_tolerances[0].type = "position"
    d = diagnose(fit_project, "FIT")
    assert d.status == "Insufficient Information"


def test_geometric_effect_needs_declared_distribution(fit_project):
    fit_project.geometric_tolerances[0].effect_distribution = None
    r = run_analysis(fit_project, "FIT", mc_samples=5_000)
    assert r.worst_case is not None and r.rss is None and "rss" in r.skipped


def test_one_sided_effect_monte_carlo_moments(fit_project):
    d = diagnose(fit_project, "FIT")
    mc = monte_carlo(d.terms, None, n=400_000, seed=9)
    # analytic: sizes Normal(k=3) on H7 [0, .021] and g6 [-.020, -.007]; cylindricities U[0, .005]
    mean = 0.0105 - (-0.0135) - 0.0025 - 0.0025
    var = (0.0105 / 3) ** 2 + (0.0065 / 3) ** 2 + 2 * (0.005 ** 2 / 12)
    assert mc.mean == pytest.approx(mean, abs=4 * mc.se_mean)
    assert mc.std == pytest.approx(var ** 0.5, rel=0.01)


def test_interference_sign_convention(fit_project):
    fit_project.characteristic.type = "diametral_interference"
    fit_project.characteristic.nominal_declared = 0.0
    fit_project.characteristic.lsl, fit_project.characteristic.usl = None, None
    d = diagnose(fit_project, "FIT")
    s = {t.contributor_id: t.sensitivity for t in d.terms}
    assert s == {"D_BORE": -1, "D_SHAFT": 1, "CYL_BORE": 1, "CYL_SHAFT": 1}
    assert d.status == "Conditionally Valid"
