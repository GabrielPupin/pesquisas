"""Engineering report (PDF)."""

from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..analysis import AnalysisResult
from ..model.project import Project
from ..validation.chain_checks import diagnose
from .tabular import tables

_FONT, _BOLD = "Helvetica", "Helvetica-Bold"
for reg, bold in (("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),):
    if Path(reg).exists() and Path(bold).exists():
        pdfmetrics.registerFont(TTFont("RptSans", reg))
        pdfmetrics.registerFont(TTFont("RptSans-Bold", bold))
        _FONT, _BOLD = "RptSans", "RptSans-Bold"

PHASE1_LIMITATIONS = [
    "1D model only: features are assumed perpendicular to the stack axis; part tilt, orientation and "
    "location deviations are not represented.",
    "Geometric tolerances are propagated only for cylindricity in a diametral fit (conservative bound). All "
    "other geometric tolerances are recorded but not propagated; their effects are listed as neglected.",
    "The stack-up path is entered by the engineer; automatic path generation is Phase 2.",
    "Drawing values were read from vector PDF text and used only after explicit confirmation.",
    "The software verifies the calculation under the stated assumptions. Physical validity of the path, the "
    "assumptions and the input data remains the responsibility of the approving engineer.",
]


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["Normal"], fontName=_FONT, fontSize=8.5, leading=11, alignment=TA_LEFT)
    return {
        "title": ParagraphStyle("t", parent=base, fontName=_BOLD, fontSize=16, leading=20, spaceAfter=6),
        "h1": ParagraphStyle("h1", parent=base, fontName=_BOLD, fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4),
        "body": base,
        "small": ParagraphStyle("s", parent=base, fontSize=7.2, leading=9),
        "cell": ParagraphStyle("c", parent=base, fontSize=7, leading=8.5),
        "warn": ParagraphStyle("w", parent=base, textColor=colors.HexColor("#8a4b00")),
    }


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def _table(head, rows, st, widths=None):
    data = [[Paragraph(f"<b>{h}</b>", st["cell"]) for h in head]]
    data += [[Paragraph(_fmt(x).replace("<", "&lt;"), st["cell"]) for x in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e9ef")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def _histogram(res: AnalysisResult, unit: str) -> Drawing:
    m = res.monte_carlo
    W, H, pad = 170 * mm, 55 * mm, 22
    d = Drawing(W, H)
    edges, counts = m.hist_edges, m.hist_counts
    lo, hi = edges[0], edges[-1]
    wc = (res.worst_case.minimum, res.worst_case.maximum) if res.worst_case else ()
    for v in (res.lsl, res.usl, *wc):
        if v is not None:
            lo, hi = min(lo, v), max(hi, v)
    span = (hi - lo) or 1.0
    lo -= 0.03 * span; hi += 0.03 * span; span = hi - lo
    cmax = max(counts) or 1
    X = lambda x: pad + (x - lo) / span * (W - 2 * pad)
    for i, c in enumerate(counts):
        x0, x1 = X(edges[i]), X(edges[i + 1])
        h = c / cmax * (H - 2 * pad)
        d.add(Rect(x0, pad, max(x1 - x0 - 0.4, 0.3), h, fillColor=colors.HexColor("#5a7fb8"), strokeColor=None))
    d.add(Line(pad, pad, W - pad, pad, strokeWidth=0.5))
    for v, lab in ((res.lsl, "LSL"), (res.usl, "USL")):
        if v is not None:
            d.add(Line(X(v), pad, X(v), H - pad + 4, strokeColor=colors.HexColor("#c0392b"), strokeWidth=1))
            d.add(String(X(v) + 2, H - pad + 2, f"{lab} {v:g}", fontName=_FONT, fontSize=7,
                         fillColor=colors.HexColor("#c0392b")))
    if res.worst_case:
        for v in (res.worst_case.minimum, res.worst_case.maximum):
            d.add(Line(X(v), pad, X(v), H - pad, strokeColor=colors.HexColor("#555555"), strokeWidth=0.6,
                       strokeDashArray=[2, 2]))
    for k in range(5):
        x = lo + span * k / 4
        d.add(String(X(x) - 10, pad - 10, f"{x:.4g}", fontName=_FONT, fontSize=6.5))
    d.add(String(pad, 4, f"Monte Carlo output distribution [{unit}] (dashed: Worst-Case limits)",
                 fontName=_FONT, fontSize=7))
    return d


def export_pdf(project: Project, res: AnalysisResult, path: str | Path) -> Path:
    st = _styles()
    T = tables(project, res)
    u = project.base_unit
    meta = res.meta
    ch = project.characteristic
    story = []
    story += [Paragraph("Tolerance stack-up report", st["title"]),
              Paragraph(f"<b>{project.name}</b> — project {project.project_id}, revision {project.revision}", st["body"]),
              Paragraph(f"Chain <b>{meta['chain_id']}</b> ({meta['chain_name']}) · generated {meta['timestamp']} · "
                        f"{meta['software']}", st["body"]),
              Paragraph(f"Model fingerprint (SHA-256): {meta['fingerprint']}", st["small"]),
              Spacer(1, 4)]
    appr = meta["approval"]
    story.append(Paragraph(
        f"Path status: <b>{res.diagnosis.status}</b> · Engineer approval: <b>{appr['state']}</b>"
        + (f" by {appr['reviewer']} ({appr['timestamp']}) — {appr['comment']}" if appr["state"] != "pending" else ""),
        st["body"]))
    for w in res.warnings:
        story.append(Paragraph("⚠ " + w, st["warn"]))

    story.append(Paragraph("1. Functional characteristic", st["h1"]))
    story.append(_table(["name", "type", "boundaries", "axis", "nominal (declared)", "LSL", "USL", "unit"],
                        [[ch.name, ch.type, f"{ch.start_feature} → {ch.end_feature}", ch.axis, ch.nominal_declared,
                          ch.lsl, ch.usl, ch.unit]], st))
    if ch.configuration:
        story.append(Paragraph(f"Assembly configuration: {ch.configuration}", st["small"]))

    story.append(Paragraph("2. Input dimensions and tolerances", st["h1"]))
    h, rows = T["Inputs"]
    story.append(_table(h, rows, st))
    story.append(Paragraph("3. Geometric tolerances and datums", st["h1"]))
    h, rows = T["Geometric"]
    story.append(_table(h, rows, st) if rows else Paragraph("No geometric tolerance recorded in the model.", st["small"]))
    story.append(Paragraph("4. Source traceability", st["h1"]))
    h, rows = T["Traceability"]
    story.append(_table(h, rows, st))

    story.append(Paragraph("5. Stack-up path and validation", st["h1"]))
    for line in res.diagnosis.path_explanation:
        story.append(Paragraph("• " + line, st["small"]))
    story.append(Spacer(1, 3))
    h, rows = T["Checks"]
    story.append(_table(h, rows, st, widths=[14 * mm, 20 * mm, 32 * mm, 16 * mm, 16 * mm, 50 * mm, 34 * mm]))
    others = [c for c in project.chains if c.id != meta["chain_id"]]
    if others:
        story.append(Paragraph("Alternative / rejected paths (retained for traceability)", st["body"]))
        orow = []
        for c in others:
            dd = diagnose(project, c)
            orow.append([c.id, c.name, dd.status, c.approval.state, c.approval.comment, " | ".join(dd.problems[:3])])
        story.append(_table(["chain", "name", "status", "approval", "comment", "main problems"], orow, st))

    story.append(Paragraph("6. Mathematical formulation", st["h1"]))
    for line in [
        f"Output equation (unit {u}): {res.diagnosis.equation}, each term = nominal + deviation δᵢ.",
        "Worst-Case: y_max/min = Σ sᵢ·nomᵢ + Σ max/min(sᵢ·upperᵢ, sᵢ·lowerᵢ) (exact for a linear chain).",
        "RSS: mean = Σ sᵢ(nomᵢ + μᵢ); σ_y² = sᵀ·Σ·s with Σ = D·R·D (first-order; exact for linear chains).",
        "Monte Carlo: δ = F⁻¹(Φ(z)), z ~ N(0, R) (Gaussian copula); y evaluated per sample; Wilson intervals "
        "for nonconformity probabilities.",
    ]:
        story.append(Paragraph(line, st["body"]))

    story.append(Paragraph("7. Assumptions", st["h1"]))
    for a in res.diagnosis.assumptions or ["None recorded."]:
        story.append(Paragraph("• " + a, st["small"]))
    story.append(Paragraph(meta["statistical_assumption"], st["small"]))
    if res.diagnosis.missing_information:
        story.append(Paragraph("Missing information", st["body"]))
        for a in res.diagnosis.missing_information:
            story.append(Paragraph("• " + a, st["small"]))

    story.append(PageBreak())
    story.append(Paragraph("8. Results", st["h1"]))
    if res.worst_case:
        story.append(Paragraph(res.worst_case.statement, st["small"]))
        story.append(_table(["contributor", "limit giving y_min", "limit giving y_max"],
                            [[k, res.worst_case.governing_min[k], res.worst_case.governing_max[k]]
                             for k in res.worst_case.governing_min], st))
        story.append(Spacer(1, 3))
    h, rows = T["Results"]
    story.append(_table(h, rows, st, widths=[30 * mm, 50 * mm, 50 * mm]))
    if res.rss:
        for n in res.rss.notes:
            story.append(Paragraph("RSS: " + n, st["small"]))
    if res.monte_carlo:
        story.append(Spacer(1, 4))
        story.append(_histogram(res, u))
        for n in res.monte_carlo.notes + res.monte_carlo.invalid_diagnosis:
            story.append(Paragraph("Monte Carlo: " + n, st["small"]))
        h, rows = T["MC convergence"]
        story.append(Paragraph("Convergence (running estimates)", st["body"]))
        story.append(_table(h, rows, st, widths=[25 * mm, 35 * mm, 35 * mm, 35 * mm]))

    story.append(Paragraph("9. Sensitivity and contribution ranking", st["h1"]))
    story.append(Paragraph("Sensitivity = physical response ∂y/∂x. WC share = share of the worst-case range. "
                           "Variance share = share of the output variance (statistical contribution).", st["small"]))
    h, rows = T["Sensitivity"]
    story.append(_table(h, rows, st))

    story.append(Paragraph("10. Conclusions", st["h1"]))
    for c in res.conclusions:
        story.append(Paragraph("• " + c, st["body"]))
    story.append(Paragraph("11. Limitations of this analysis", st["h1"]))
    for c in PHASE1_LIMITATIONS:
        story.append(Paragraph("• " + c, st["small"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Software verification ≠ mathematical validation ≠ engineering approval. "
                           "Approval signature: ____________________   Date: ____________", st["body"]))

    p = Path(path)

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT, 6.5)
        canvas.drawString(15 * mm, 8 * mm, f"{project.project_id} rev {project.revision} · chain {meta['chain_id']} · "
                                           f"fingerprint {meta['fingerprint'][:16]} · seed {meta['seed']}")
        canvas.drawRightString(195 * mm, 8 * mm, f"page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(p), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"Stack-up report {project.project_id}")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return p
