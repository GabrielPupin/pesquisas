"""Path validation: incorrect, incomplete, duplicated, insufficient and conflicting cases."""

import pytest

from tolstack.analysis import run_analysis
from tolstack.errors import AnalysisBlocked, ModelError, UnitError
from tolstack.model import Chain, Contributor, Correlation, FunctionalCharacteristic, ToleranceSpec
from tolstack.units import convert, normalize_unit
from tolstack.validation.chain_checks import diagnose

from helpers import simple_stack


def _check(d, cid):
    return next(c for c in d.checks if c.id == cid)


def test_correct_path_is_conditionally_valid_never_validated(axial_project):
    d = diagnose(axial_project, "A")
    assert d.status == "Conditionally Valid"
    assert d.equation == "y = −1·B2 −1·S −1·B1 +1·H"
    assert any("1D model" in a for a in d.assumptions)
    assert all(c.outcome != "failed" for c in d.checks)


def test_missing_spacer_breaks_the_loop(axial_project):
    d = diagnose(axial_project, "B")
    assert d.status == "Invalid"
    assert "Discontinuity" in " ".join(_check(d, "TOPO").details)


def test_rejected_path_blocks_analysis_but_keeps_diagnostics(axial_project):
    with pytest.raises(AnalysisBlocked):
        run_analysis(axial_project, "B")
    assert diagnose(axial_project, "B").checks  # diagnostics still available


def test_wrong_direction_detected_by_nominal_closure(axial_project):
    axial_project.contributor("S").direction = -1
    d = diagnose(axial_project, "A")
    # the path still closes topologically (it follows feature names); the sign of S flips, so the computed
    # nominal no longer matches the declared one — mathematical closure catches the error.
    assert _check(d, "TOPO").outcome == "passed"
    assert d.status == "Invalid"
    assert _check(d, "CLOSURE").outcome == "failed"


def test_declared_sensitivity_conflicting_with_topology(axial_project):
    axial_project.contributor("H").sensitivity = -1
    d = diagnose(axial_project, "A")
    assert d.status == "Invalid"
    assert "contradicts" in " ".join(_check(d, "TOPO").details)


def test_duplicate_contributor_is_invalid(axial_project):
    axial_project.chains.append(Chain(id="D", contributor_ids=["B2", "S", "S", "B1", "H"]))
    d = diagnose(axial_project, "D")
    assert d.status == "Invalid"
    assert _check(d, "DUP").outcome == "failed"


def test_same_feature_pair_twice_is_flagged_as_double_counting(axial_project):
    axial_project.contributors.append(Contributor(
        id="S2", component="SPC", from_feature="SP_R", to_feature="SP_L", direction=-1,
        tolerance=ToleranceSpec.bilateral(19.8, 0.05, "mm")))
    axial_project.chains.append(Chain(id="D", contributor_ids=["B2", "S2", "S", "B1", "H"]))
    d = diagnose(axial_project, "D")
    assert _check(d, "DUP").outcome == "failed"


def test_dimension_spanning_two_components_is_invalid(axial_project):
    axial_project.contributor("H").to_feature = "B2_R"
    d = diagnose(axial_project, "A")
    assert d.status == "Invalid"
    assert "spans two components" in " ".join(_check(d, "TOPO").details)


def test_missing_contact_is_a_discontinuity(axial_project):
    axial_project.contacts = [k for k in axial_project.contacts if k.id != "K2"]
    d = diagnose(axial_project, "A")
    assert d.status == "Invalid"


def test_unjustified_contact_is_warned(axial_project):
    axial_project.contacts[0].assumption = ""
    d = diagnose(axial_project, "A")
    assert d.status == "Conditionally Valid"
    assert _check(d, "CONTACT").outcome == "warning"
    assert any("NO justification" in a for a in d.assumptions)


def test_missing_tolerance_is_insufficient(axial_project):
    axial_project.contributor("S").tolerance = None
    d = diagnose(axial_project, "A")
    assert d.status == "Insufficient Information"
    assert any("'S'" in m for m in d.missing_information)
    with pytest.raises(AnalysisBlocked):
        run_analysis(axial_project, "A")


def test_basic_dimension_in_chain_needs_geometric_model(axial_project):
    axial_project.contributor("H").tolerance = ToleranceSpec.basic(50, "mm")
    d = diagnose(axial_project, "A")
    assert d.status == "Insufficient Information"
    assert _check(d, "BASIC").outcome == "failed"


@pytest.mark.parametrize("ctype", ["angular_misalignment", "radial_alignment", "position_deviation",
                                   "hole_pattern_fit"])
def test_unsupported_characteristic_type_is_insufficient(axial_project, ctype):
    # perpendicularity/angularity, hole patterns (position) and alignment need 2D/3D models (Phase 3+)
    axial_project.characteristic.type = ctype
    assert diagnose(axial_project, "A").status == "Insufficient Information"


def test_lsl_above_usl_is_invalid(axial_project):
    axial_project.characteristic.lsl, axial_project.characteristic.usl = 0.5, 0.1
    assert diagnose(axial_project, "A").status == "Invalid"


def test_no_limits_is_warning_only(axial_project):
    axial_project.characteristic.lsl = axial_project.characteristic.usl = None
    d = diagnose(axial_project, "A")
    assert d.status == "Conditionally Valid" and _check(d, "LIMITS").outcome == "warning"


def test_user_defined_scalar_requires_sensitivities():
    p = simple_stack([("H", 50, 0.1, -0.1), ("A", 49.8, 0.1, -0.1)])
    p.characteristic = FunctionalCharacteristic(id="U", name="u", type="user_defined_scalar")
    d = diagnose(p)
    assert d.status == "Insufficient Information"
    p.contributor("H").sensitivity = 0.5
    p.contributor("A").sensitivity = -0.5
    d = diagnose(p)
    assert d.status == "Conditionally Valid"
    assert any("declared by the user" in a for a in d.assumptions)


def test_user_declared_equivalent_requires_justification(axial_project):
    c = axial_project.contributor("S")
    c.kind = "user_declared_equivalent"
    assert diagnose(axial_project, "A").status == "Insufficient Information"
    c.justification = "Perpendicularity of spacer faces converted by the engineer using face height ratio."
    d = diagnose(axial_project, "A")
    assert d.status == "Conditionally Valid"
    assert any("not verified" in a for a in d.assumptions)


def test_inconsistent_correlations_rejected():
    p = simple_stack([("H", 50, 0.1, -0.1), ("A", 20, 0.1, -0.1), ("B", 29.8, 0.1, -0.1)], rule="normal_k_sigma")
    p.correlations = [Correlation(a="H", b="A", rho=0.9), Correlation(a="H", b="B", rho=0.9),
                      Correlation(a="A", b="B", rho=-0.9)]
    d = diagnose(p)
    assert d.status == "Invalid" and _check(d, "CORR").outcome == "failed"


def test_units_conversion_and_rejection():
    assert convert(1, "in", "mm") == pytest.approx(25.4)
    assert convert(5, "µm", "mm") == pytest.approx(0.005)
    for bad in ("deg", "cm?", "", "MM2"):
        with pytest.raises(UnitError):
            normalize_unit(bad)
    p = simple_stack([("H", 2, 0.004, -0.004), ("A", 49.8, 0.1, -0.1)])
    p.contributor("H").tolerance = ToleranceSpec(nominal=2.0, upper=0.004, lower=-0.004, unit="in")
    d = diagnose(p)
    h = next(t for t in d.terms if t.contributor_id == "H")
    assert h.nominal == pytest.approx(50.8) and h.upper == pytest.approx(0.1016)
    p.contributor("A").tolerance = ToleranceSpec(nominal=49.8, upper=0.1, lower=-0.1, unit="deg")
    assert diagnose(p).status == "Invalid"


def test_tolerance_spec_rules():
    with pytest.raises(ModelError):
        ToleranceSpec(nominal=1, upper=-0.1, lower=0.1, unit="mm")
    with pytest.raises(ModelError):
        ToleranceSpec(nominal=1, upper=0.1, lower=0, unit="mm", origin="basic")
    lim = ToleranceSpec.limits(24.9, 25.1, "mm")
    assert lim.nominal == pytest.approx(25.0) and lim.upper == pytest.approx(0.1)


def test_multiple_valid_paths_are_reported_separately(axial_project):
    # an equivalent path entered in a different order is also valid: both are diagnosed independently
    axial_project.chains.append(Chain(id="C", contributor_ids=["B2", "S", "B1", "H"], name="duplicate entry"))
    assert diagnose(axial_project, "A").status == diagnose(axial_project, "C").status == "Conditionally Valid"
    with pytest.raises(ModelError):
        axial_project.chain(None)


def test_check_records_are_well_formed(axial_project, fit_project):
    for proj in (axial_project, fit_project):
        for ch in proj.chains:
            for c in diagnose(proj, ch).checks:
                assert isinstance(c.details, list)
                if c.outcome in ("passed", "not_evaluable"):
                    assert c.severity is None
                if c.outcome == "failed":
                    assert c.severity in ("invalid", "insufficient")
