"""Callout parser and PDF drawing extraction against ground truth; confirmation workflow."""

import pytest

from tolstack.drawing.callout_parser import parse_callout
from tolstack.drawing.pdf_extract import extract_drawing
from tolstack.drawing.render import render_overlay
from tolstack.drawing.review import ParsedCallout
from tolstack.drawing.workflow import confirm_callout, confirm_title, link_dimension, link_geometric
from tolstack.errors import InsufficientInformation, UnitError
from tolstack.validation.chain_checks import diagnose

CASES = [
    ("25 ±0.1", "parsed", "linear", 25.0, 0.1, -0.1),
    ("25±0,1", "parsed", "linear", 25.0, 0.1, -0.1),
    ("Ø20 H7", "parsed", "diameter", 20.0, 0.021, 0.0),
    ("Ø20 g6 Ⓔ", "parsed", "diameter", 20.0, -0.007, -0.02),
    ("10 +0.05/-0", "parsed", "linear", 10.0, 0.05, 0.0),
    ("10 +0.05 -0.02", "parsed", "linear", 10.0, 0.05, -0.02),
    ("15 0/-0.12", "parsed", "linear", 15.0, 0.0, -0.12),
    ("15 −0,12/0", "parsed", "linear", 15.0, 0.0, -0.12),
    ("25.1/24.9", "parsed", "linear", 25.0, 0.1, -0.1),
    ("[25]", "parsed", "linear", 25.0, 0.0, 0.0),
    ("2x Ø6 ±0.05", "parsed", "diameter", 6.0, 0.05, -0.05),
    ("R5 ±0.2", "parsed", "radius", 5.0, 0.2, -0.2),
    ("Ø20 H7/g6", "ambiguous", "diameter", 20.0, None, None),
    ("Ø20 H7 (+0.025/0)", "ambiguous", "diameter", 20.0, 0.021, 0.0),
    ("50", "ambiguous", "linear", 50.0, None, None),
    ("Ø20 x7", "unsupported", "diameter", 20.0, None, None),
]


@pytest.mark.parametrize("text,status,kind,nom,up,lo", CASES)
def test_parser_cases(text, status, kind, nom, up, lo):
    st, pc, issues, cat = parse_callout(text, unit="mm")
    assert st == status, issues
    assert pc.kind == kind and pc.nominal == pytest.approx(nom)
    if up is not None:
        assert (pc.upper, pc.lower) == (pytest.approx(up), pytest.approx(lo))


def test_parser_geometric_and_special():
    st, pc, _, cat = parse_callout("⌖ Ø0.1 Ⓜ A B C", unit="mm")
    assert (st, cat, pc.geometric_type, pc.diameter_zone, pc.datums, pc.material_modifier) == \
        ("parsed", "geometric", "position", True, ["A", "B", "C"], "MMC")
    st, pc, _, _ = parse_callout("CILINDRICIDADE 0,005", unit="mm")
    assert pc.geometric_type == "cylindricity" and pc.geometric_value == 0.005
    assert parse_callout("M8", unit="mm")[0] == "unsupported"
    st, pc, issues, _ = parse_callout("30° ±0°30'", unit="mm")
    assert pc.kind == "angle" and pc.upper == pytest.approx(0.5)
    st, _, issues, _ = parse_callout("25 ±0.1", unit=None)
    assert st == "ambiguous" and "unit" in issues[0]
    st, pc, issues, _ = parse_callout("80", unit="mm", general_tolerance="ISO 2768-m")
    assert st == "parsed" and pc.tolerance_origin == "general" and pc.upper == 0.3


def test_extraction_matches_ground_truth(drawings):
    folder, truth = drawings
    for name, gt in truth.items():
        rec = extract_drawing(folder / name)
        assert rec.text_available
        assert len(rec.callouts) == len(gt["callouts"]), [c.raw_text for c in rec.callouts]
        for exp in gt["callouts"]:
            cands = [c for c in rec.callouts if c.raw_text.replace("[graphic symbol] | ", "") == exp["text"]
                     or c.raw_text == exp["text"]]
            assert cands, f"{name}: '{exp['text']}' not found in {[c.raw_text for c in rec.callouts]}"
            c = cands[0]
            assert c.status == exp["status"], (exp, c.issues)
            if "category" in exp:
                assert c.category == exp["category"]
            if "nominal" in exp:
                p = c.parsed
                assert p.kind == exp["kind"]
                assert p.nominal == pytest.approx(exp["nominal"])
                assert p.upper == pytest.approx(exp["upper"]) and p.lower == pytest.approx(exp["lower"])
                if "origin" in exp:
                    assert p.tolerance_origin == exp["origin"]
        found = {(t.field, t.value) for t in rec.title_block}
        for k, v in gt["title_block"].items():
            assert (k, v) in found, (k, v, found)


def test_pdf_without_text_is_reported(drawings):
    folder, _ = drawings
    rec = extract_drawing(folder / "outlined_text.pdf")
    assert not rec.text_available and not rec.callouts
    assert "No vector text" in rec.messages[0]


def test_overlay_renders(drawings):
    folder, _ = drawings
    rec = extract_drawing(folder / "TS-100_housing.pdf")
    img = render_overlay(folder / "TS-100_housing.pdf", rec)
    assert img.size[0] > 1000


def test_confirmation_is_required_before_use(drawings, axial_project, fit_project):
    folder, _ = drawings
    rec = extract_drawing(folder / "TS-100_housing.pdf", drawing_id="TS100")
    axial_project.drawings.append(rec)
    c50 = next(c for c in rec.callouts if c.raw_text == "50 ±0,1")
    with pytest.raises(InsufficientInformation):
        link_dimension(axial_project, "TS100", c50.id, "H")
    with pytest.raises(Exception):
        confirm_callout(rec, c50.id, reviewer="  ")
    confirm_title(rec, "drawing_number"); confirm_title(rec, "revision")
    confirm_callout(rec, c50.id, reviewer="G. Pupin")
    contrib = link_dimension(axial_project, "TS100", c50.id, "H", component="HSG", from_feature="HSG_L",
                             to_feature="HSG_R", direction=1)
    assert contrib.source.document == "TS-100" and contrib.source.revision == "B"
    assert contrib.tolerance.upper == pytest.approx(0.1)
    assert diagnose(axial_project, "A").status == "Conditionally Valid"

    # general tolerance requires the note to be confirmed
    c80 = next(c for c in rec.callouts if c.raw_text == "80")
    confirm_callout(rec, c80.id, reviewer="G. Pupin")
    with pytest.raises(InsufficientInformation):
        link_dimension(axial_project, "TS100", c80.id, "W")
    confirm_title(rec, "general_tolerance")
    assert link_dimension(axial_project, "TS100", c80.id, "W").tolerance.origin == "iso2768"

    # ambiguous geometric frame: must be confirmed with the type selected
    fr = next(c for c in rec.callouts if c.category == "geometric")
    with pytest.raises(InsufficientInformation):
        confirm_callout(rec, fr.id, reviewer="G. Pupin")
    vals = fr.parsed.model_copy(update={"geometric_type": "cylindricity", "unit": "mm"})
    conf = confirm_callout(rec, fr.id, reviewer="G. Pupin", values=vals, comment="symbol read on the drawing")
    assert conf.edited and conf.original.geometric_type is None
    confirm_title(rec, "size_principle")
    gt = link_geometric(axial_project, "TS100", fr.id, "G9", "HSG_L")
    assert gt.type == "cylindricity" and gt.size_principle == "independency" and gt.value == 0.005


def test_rejected_and_angular_callouts_cannot_be_linked(drawings, axial_project):
    folder, _ = drawings
    rec = extract_drawing(folder / "TS-100_housing.pdf", drawing_id="TS100")
    axial_project.drawings.append(rec)
    c = rec.callouts[0]
    confirm_callout(rec, c.id, reviewer="x", decision="rejected", comment="not this one")
    with pytest.raises(InsufficientInformation):
        link_dimension(axial_project, "TS100", c.id, "Z")
    ang = ParsedCallout(kind="angle", nominal=30, upper=0.5, lower=-0.5, unit="deg")
    confirm_callout(rec, rec.callouts[1].id, reviewer="x", values=ang)
    with pytest.raises(UnitError):
        link_dimension(axial_project, "TS100", rec.callouts[1].id, "Z")
