"""Builds the demonstration projects (JSON) used by the README, the GUI and the tests.

1. axial_clearance_demo.json  — shaft supported by two bearings and a spacer in a housing; axial end play.
   Chain A is the correct path; chain B omits the spacer (kept as a rejected path for traceability).
2. fit_cylindricity_demo.json — Ø20 H7/g6 bore–shaft fit with cylindricity 0.005 on both features under
   the independency principle (ISO 8015).
Run:  python examples/build_demo_projects.py
"""

from __future__ import annotations

from pathlib import Path

from tolstack.io.project_json import save_project
from tolstack.model import (
    Approval, Chain, Component, Contact, Contributor, Correlation, Feature, FunctionalCharacteristic,
    GeometricTolerance, Normal, Project, StatisticalAssumption, ToleranceSpec, Uniform,
)
from tolstack.model.contributor import SourceRef
from tolstack.standards.iso286 import deviations_mm

HERE = Path(__file__).parent


def axial_demo() -> Project:
    p = Project(
        project_id="DEMO-AX-001", name="Shaft bearing arrangement — axial end play", revision="A",
        author="tolstack demo", base_unit="mm", standard="ISO_GPS",
        description="Housing bore with shoulder, two deep-groove ball bearings and a spacer. "
                    "Output: axial clearance between the outer bearing face and the housing cover face.",
        statistical_assumption=StatisticalAssumption(rule="normal_k_sigma", k=3.0),
    )
    p.components = [
        Component(id="HSG", name="Housing", part_number="TS-100", drawing="TS-100", revision="B"),
        Component(id="BRG1", name="Bearing 1 (6204)", part_number="6204"),
        Component(id="SPC", name="Spacer", part_number="TS-110", drawing="TS-110", revision="A"),
        Component(id="BRG2", name="Bearing 2 (6204)", part_number="6204"),
    ]
    p.features = [
        Feature(id="HSG_L", component="HSG", name="Housing shoulder face"),
        Feature(id="HSG_R", component="HSG", name="Housing cover seat face"),
        Feature(id="B1_L", component="BRG1", name="Bearing 1 left face"),
        Feature(id="B1_R", component="BRG1", name="Bearing 1 right face"),
        Feature(id="SP_L", component="SPC", name="Spacer left face"),
        Feature(id="SP_R", component="SPC", name="Spacer right face"),
        Feature(id="B2_L", component="BRG2", name="Bearing 2 left face"),
        Feature(id="B2_R", component="BRG2", name="Bearing 2 right face"),
    ]
    p.contacts = [
        Contact(id="K1", feature_a="HSG_L", feature_b="B1_L",
                assumption="Bearing 1 held against the housing shoulder by the wave-spring preload."),
        Contact(id="K2", feature_a="B1_R", feature_b="SP_L", assumption="Preload transmitted through the spacer."),
        Contact(id="K3", feature_a="SP_R", feature_b="B2_L", assumption="Preload transmitted through the spacer."),
    ]
    p.contributors = [
        Contributor(id="H", name="Housing shoulder-to-cover seat", component="HSG", from_feature="HSG_L",
                    to_feature="HSG_R", direction=1, tolerance=ToleranceSpec.bilateral(50.0, 0.10, "mm"),
                    source=SourceRef(document="TS-100", revision="B")),
        Contributor(id="B1", name="Bearing 1 width", component="BRG1", from_feature="B1_L", to_feature="B1_R",
                    direction=1, tolerance=ToleranceSpec.deviations(15.0, 0.0, -0.12, "mm"),
                    source=SourceRef(document="ISO 492 normal class, d=20 mm")),
        Contributor(id="S", name="Spacer length", component="SPC", from_feature="SP_L", to_feature="SP_R",
                    direction=1, tolerance=ToleranceSpec.bilateral(19.8, 0.05, "mm"),
                    distribution=Normal(mu=0.004, sigma=0.012),
                    source=SourceRef(document="TS-110", revision="A"),
                    notes="Distribution from SPC data of the turning cell (Cpk ≈ 1.28)."),
        Contributor(id="B2", name="Bearing 2 width", component="BRG2", from_feature="B2_L", to_feature="B2_R",
                    direction=1, tolerance=ToleranceSpec.deviations(15.0, 0.0, -0.12, "mm"),
                    source=SourceRef(document="ISO 492 normal class, d=20 mm")),
    ]
    p.correlations = [Correlation(a="B1", b="B2", rho=0.5, source="Bearings supplied from the same lot")]
    p.characteristic = FunctionalCharacteristic(
        id="EP", name="Axial end play", type="axial_clearance", start_feature="B2_R", end_feature="HSG_R",
        unit="mm", lsl=0.05, usl=0.45, nominal_declared=0.20, axis="+X (left → right)",
        configuration="Bearing stack pushed to the left (towards the shoulder) by the preload spring.",
    )
    p.chains = [
        Chain(id="A", name="Through bearings and spacer", contributor_ids=["B2", "S", "B1", "H"],
              rationale="From the outer face of bearing 2 back through the preloaded stack to the housing "
                        "shoulder, then across the housing to the cover seat."),
        Chain(id="B", name="Spacer omitted (incorrect)", contributor_ids=["B2", "B1", "H"],
              rationale="Candidate entered without the spacer.",
              approval=Approval(state="rejected", reviewer="demo reviewer", timestamp="2026-10-14T00:00:00+00:00",
                                comment="Loop does not close: spacer missing.", status_at_review="Invalid")),
    ]
    return p


def fit_demo() -> Project:
    p = Project(
        project_id="DEMO-FIT-001", name="Bore–shaft fit Ø20 H7/g6 with cylindricity", revision="A",
        author="tolstack demo", base_unit="mm", standard="ISO_GPS",
        description="Plain bearing seat. Both features carry cylindricity 0.005 mm; no envelope indication, "
                    "so the independency principle (ISO 8015) applies.",
        statistical_assumption=StatisticalAssumption(rule="normal_k_sigma", k=3.0),
    )
    p.components = [Component(id="HSG", name="Housing", drawing="TS-100", revision="B"),
                    Component(id="SHF", name="Shaft", drawing="TS-120", revision="A")]
    p.features = [Feature(id="BORE", component="HSG", name="Bore Ø20", kind="cylinder", role="hole"),
                  Feature(id="JOURNAL", component="SHF", name="Journal Ø20", kind="cylinder", role="shaft")]
    hu, hl = deviations_mm("H7", 20.0)
    su, sl = deviations_mm("g6", 20.0)
    p.contributors = [
        Contributor(id="D_BORE", name="Bore diameter", component="HSG", kind="size", from_feature="BORE",
                    tolerance=ToleranceSpec(nominal=20.0, upper=hu, lower=hl, unit="mm", origin="iso286",
                                            designation="H7")),
        Contributor(id="D_SHAFT", name="Journal diameter", component="SHF", kind="size", from_feature="JOURNAL",
                    tolerance=ToleranceSpec(nominal=20.0, upper=su, lower=sl, unit="mm", origin="iso286",
                                            designation="g6")),
        Contributor(id="CYL_BORE", name="Bore cylindricity effect", component="HSG", kind="geometric",
                    geometric_id="G1"),
        Contributor(id="CYL_SHAFT", name="Journal cylindricity effect", component="SHF", kind="geometric",
                    geometric_id="G2"),
    ]
    p.geometric_tolerances = [
        GeometricTolerance(id="G1", type="cylindricity", feature_id="BORE", value=0.005, unit="mm",
                           standard="ISO_GPS", size_principle="independency",
                           effect_distribution=Uniform(low=0.0, high=0.005),
                           notes="Distribution of the form effect: engineering assumption, uniform over [0, t]."),
        GeometricTolerance(id="G2", type="cylindricity", feature_id="JOURNAL", value=0.005, unit="mm",
                           standard="ISO_GPS", size_principle="independency",
                           effect_distribution=Uniform(low=0.0, high=0.005)),
    ]
    p.characteristic = FunctionalCharacteristic(
        id="C", name="Diametral running clearance", type="diametral_clearance", start_feature="BORE",
        end_feature="JOURNAL", unit="mm", lsl=0.005, usl=0.045, nominal_declared=0.0,
        configuration="Shaft centred in the bore (no load-induced offset modelled).")
    p.chains = [Chain(id="FIT", name="Size + cylindricity", contributor_ids=["D_BORE", "D_SHAFT", "CYL_BORE", "CYL_SHAFT"],
                      rationale="Mating clearance = hole mating size − shaft mating size; under independency the "
                                "form deviation reduces both mating sizes' clearance.")]
    return p


if __name__ == "__main__":
    save_project(axial_demo(), HERE / "axial_clearance_demo.json")
    save_project(fit_demo(), HERE / "fit_cylindricity_demo.json")
    print("written:", HERE / "axial_clearance_demo.json", HERE / "fit_cylindricity_demo.json")
