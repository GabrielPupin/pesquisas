"""tolstack — Streamlit interface (Phase 1). Thin layer: every calculation lives in the tolstack package.

Run:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tolstack.analysis import run_analysis, what_if
from tolstack.drawing.pdf_extract import extract_drawing
from tolstack.drawing.render import render_overlay
from tolstack.drawing.review import ParsedCallout
from tolstack.drawing.workflow import confirm_callout, confirm_title, link_dimension, link_geometric
from tolstack.errors import AnalysisBlocked, TolstackError
from tolstack.io.project_json import project_from_dict, project_to_json
from tolstack.model import (
    Approval, Chain, Component, Contact, Contributor, Correlation, Feature, FunctionalCharacteristic,
    GeometricTolerance, Project, StatisticalAssumption, ToleranceSpec,
)
from tolstack.model.characteristic import CharacteristicType
from tolstack.model.distributions import Empirical, Normal, Triangular, TruncatedNormal, Uniform
from tolstack.reporting.pdf import export_pdf
from tolstack.reporting.tabular import export_csv, export_excel
from tolstack.validation.chain_checks import diagnose

ROOT = Path(__file__).resolve().parents[1]
DEMOS = {"Axial end play (bearings + spacer)": ROOT / "examples" / "axial_clearance_demo.json",
         "Ø20 H7/g6 fit with cylindricity": ROOT / "examples" / "fit_cylindricity_demo.json"}
STATUS_COLOR = {"Conditionally Valid": "orange", "Validated": "green", "Invalid": "red",
                "Insufficient Information": "violet"}

st.set_page_config(page_title="tolstack — stack-up analyzer", layout="wide")


# ------------------------------------------------------------------------------------------- state
def P() -> Project:
    return st.session_state["project"]


def set_project(p: Project):
    st.session_state["project"] = p
    st.session_state.pop("result", None)


if "project" not in st.session_state:
    set_project(project_from_dict(json.loads(next(iter(DEMOS.values())).read_text(encoding="utf-8"))))
st.session_state.setdefault("pdf_bytes", {})


def guarded(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (TolstackError, ValueError, KeyError) as e:
        st.error(f"{type(e).__name__}: {e}")
        return None


# ------------------------------------------------------------------- distribution <-> flat columns
def dist_to_cols(d):
    if d is None:
        return "none", None, None, None, None
    if isinstance(d, Normal):
        return "normal", d.mu, d.sigma, None, None
    if isinstance(d, Uniform):
        return "uniform", d.low, d.high, None, None
    if isinstance(d, Triangular):
        return "triangular", d.low, d.mode, d.high, None
    if isinstance(d, TruncatedNormal):
        return "truncated_normal", d.mu, d.sigma, d.low, d.high
    if isinstance(d, Empirical):
        return "empirical", None, None, None, None
    return "none", None, None, None, None


def cols_to_dist(kind, a, b, c, d, old=None):
    kind = kind or "none"
    if kind == "none":
        return None
    if kind == "normal":
        return Normal(mu=float(a), sigma=float(b))
    if kind == "uniform":
        return Uniform(low=float(a), high=float(b))
    if kind == "triangular":
        return Triangular(low=float(a), mode=float(b), high=float(c))
    if kind == "truncated_normal":
        return TruncatedNormal(mu=float(a), sigma=float(b), low=float(c), high=float(d))
    if kind == "empirical":
        return old  # empirical data is edited through the JSON file
    raise ValueError(f"unknown distribution '{kind}'")


def _n(x):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) or x == "" else x


# ------------------------------------------------------------------------------------------ sidebar
st.sidebar.title("tolstack")
st.sidebar.caption("Tolerance stack-up analyzer — Phase 1 (1D)")
PAGES = ["1 · Project", "2 · Drawing import (PDF)", "3 · Components & features", "4 · Dimensions & tolerances",
         "5 · Functional characteristic", "6 · Stack-up paths", "7 · Path validation & review",
         "8 · Analysis configuration", "9 · Results & sensitivity", "10 · Report"]
page = st.sidebar.radio("Module", PAGES)
p = P()
st.sidebar.markdown(f"**{p.name}**  \n`{p.project_id}` rev {p.revision}")
st.sidebar.caption(f"fingerprint {p.fingerprint()[:16]}")

# ------------------------------------------------------------------------------------------ pages
if page.startswith("1"):
    st.header("Project and assembly")
    c1, c2 = st.columns(2)
    with c1:
        demo = st.selectbox("Load demonstration model", list(DEMOS))
        if st.button("Load demo"):
            set_project(project_from_dict(json.loads(DEMOS[demo].read_text(encoding="utf-8"))))
            st.rerun()
        up = st.file_uploader("Open project (.json)", type=["json"])
        if up is not None and st.button("Open uploaded project"):
            pr = guarded(project_from_dict, json.loads(up.getvalue()))
            if pr:
                set_project(pr); st.rerun()
        if st.button("New empty project"):
            set_project(Project(project_id="NEW-001", name="New project")); st.rerun()
    with c2:
        with st.form("meta"):
            pid = st.text_input("Project id", p.project_id)
            name = st.text_input("Name", p.name)
            rev = st.text_input("Model revision", p.revision)
            author = st.text_input("Author", p.author)
            unit = st.selectbox("Project unit", ["mm", "um", "in"], index=["mm", "um", "in"].index(p.base_unit)
                                if p.base_unit in ("mm", "um", "in") else 0)
            std = st.selectbox("Interpretation standard", ["ISO_GPS", "ASME_Y14.5", "(not set)"],
                               index=["ISO_GPS", "ASME_Y14.5"].index(p.standard) if p.standard else 2)
            desc = st.text_area("Description", p.description)
            if st.form_submit_button("Apply"):
                p.project_id, p.name, p.revision, p.author, p.base_unit, p.description = pid, name, rev, author, unit, desc
                p.standard = None if std == "(not set)" else std
                st.success("Updated.")
    st.download_button("Download project JSON", project_to_json(p), file_name=f"{p.project_id}.json",
                       mime="application/json")

elif page.startswith("2"):
    st.header("Drawing-assisted input (vector PDF)")
    st.info("Values read from a drawing are proposals. They enter the model only after you confirm each one; "
            "edits keep the original reading for traceability. Scanned PDFs are not read (no OCR).")
    up = st.file_uploader("Drawing PDF", type=["pdf"])
    if up is not None and st.button("Extract"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(up.getvalue())
        rec = guarded(extract_drawing, fh.name, Path(up.name).stem)
        if rec:
            rec.file_name = up.name
            p.drawings = [d for d in p.drawings if d.id != rec.id] + [rec]
            st.session_state["pdf_bytes"][rec.id] = up.getvalue()
            p.log("extract_drawing", drawing=rec.id, sha256=rec.sha256)
    if not p.drawings:
        st.stop()
    did = st.selectbox("Drawing", [d.id for d in p.drawings])
    rec = p.drawing(did)
    for m in rec.messages:
        st.warning(m)
    left, right = st.columns([3, 2])
    with left:
        pdfb = st.session_state["pdf_bytes"].get(did)
        if pdfb:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
                fh.write(pdfb)
            st.image(render_overlay(fh.name, rec), caption="green = parsed · orange = ambiguous · red = unsupported · "
                     "blue = confirmed · purple = title block", use_container_width=True)
        else:
            st.caption("Upload the PDF again to see the overlay (the file itself is not stored in the project).")
    with right:
        st.subheader("Title block")
        for i, t in enumerate(rec.title_block):
            cols = st.columns([3, 2, 1])
            cols[0].write(f"**{t.field}** — `{t.raw_text}`")
            cols[1].write(t.value)
            if not t.confirmed and cols[2].button("Confirm", key=f"tb{did}{i}"):
                confirm_title(rec, t.field, t.value); st.rerun()
            elif t.confirmed:
                cols[2].write("✓")
    rows = []
    for c in rec.callouts:
        conf = rec.confirmation_for(c.id)
        pc = c.parsed
        rows.append({"id": c.id, "text": c.raw_text, "status": c.status, "category": c.category,
                     "kind": pc.kind if pc else None, "nominal": pc.nominal if pc else None,
                     "upper": pc.upper if pc else None, "lower": pc.lower if pc else None,
                     "origin": pc.tolerance_origin if pc else None,
                     "geometric": pc.geometric_type if pc else None,
                     "decision": conf.decision if conf else "pending", "issues": "; ".join(c.issues)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    if rec.callouts:
        st.subheader("Review a callout")
        cid = st.selectbox("Callout", [c.id for c in rec.callouts])
        c = rec.callout(cid)
        pc = c.parsed or ParsedCallout(kind="linear")
        with st.form("confirm"):
            st.write(f"Text on drawing: `{c.raw_text}` — status **{c.status}** {('— ' + '; '.join(c.issues)) if c.issues else ''}")
            kinds = ["linear", "diameter", "radius", "angle", "geometric"]
            kind = st.selectbox("Kind", kinds, index=kinds.index(pc.kind))
            a, b, cc, d = st.columns(4)
            nom = a.number_input("Nominal", value=float(pc.nominal or 0.0), format="%.5f")
            upv = b.number_input("Upper dev.", value=float(pc.upper or 0.0), format="%.5f")
            lov = cc.number_input("Lower dev.", value=float(pc.lower or 0.0), format="%.5f")
            unit = d.selectbox("Unit", ["mm", "in", "um", "deg"],
                               index=["mm", "in", "um", "deg"].index(pc.unit) if pc.unit in ("mm", "in", "um", "deg") else 0)
            gtypes = ["", "straightness", "flatness", "circularity", "cylindricity", "parallelism", "perpendicularity",
                      "angularity", "position", "circular_runout", "total_runout"]
            g1, g2 = st.columns(2)
            gtype = g1.selectbox("Geometric type", gtypes, index=gtypes.index(pc.geometric_type or ""))
            gval = g2.number_input("Geometric value", value=float(pc.geometric_value or 0.0), format="%.5f")
            reviewer = st.text_input("Reviewer (required)")
            comment = st.text_input("Comment")
            decision = st.radio("Decision", ["confirmed", "rejected"], horizontal=True)
            if st.form_submit_button("Record decision"):
                vals = pc.model_copy(update={"kind": kind, "nominal": nom, "upper": upv, "lower": lov, "unit": unit,
                                             "geometric_type": gtype or None, "geometric_value": gval
                                             if kind == "geometric" else None})
                changed = c.parsed is None or vals != c.parsed
                r = guarded(confirm_callout, rec, cid, reviewer, values=vals if changed else None,
                            decision=decision, comment=comment)
                if r:
                    st.success(f"Recorded ({'edited' if r.edited else 'as extracted'}).")
        conf = rec.confirmation_for(cid)
        if conf and conf.decision == "confirmed":
            st.subheader("Use the confirmed value in the model")
            if conf.values.kind == "geometric":
                with st.form("linkg"):
                    gid = st.text_input("Geometric tolerance id", f"G_{cid.split('-')[-1]}")
                    fid = st.selectbox("Controlled feature", [f.id for f in p.features] or ["(define features first)"])
                    sp = st.selectbox("Size principle", ["(from confirmed drawing note)", "independency", "envelope"])
                    if st.form_submit_button("Link geometric tolerance"):
                        g = guarded(link_geometric, p, did, cid, gid, fid,
                                    size_principle=None if sp.startswith("(") else sp)
                        if g:
                            st.success(f"{g.id}: {g.zone_description()} (principle: {g.size_principle})")
            else:
                with st.form("linkd"):
                    a, b = st.columns(2)
                    kid = a.text_input("Contributor id", f"D_{cid.split('-')[-1]}")
                    comp = b.selectbox("Component", [""] + [x.id for x in p.components])
                    feats = [""] + [f.id for f in p.features]
                    f1, f2, f3 = st.columns(3)
                    ff = f1.selectbox("From feature", feats)
                    tf = f2.selectbox("To feature (blank for a size)", feats)
                    dr = f3.selectbox("Direction (+axis)", [None, 1, -1])
                    if st.form_submit_button("Link as contributor"):
                        k = guarded(link_dimension, p, did, cid, kid, component=comp, from_feature=ff or None,
                                    to_feature=tf or None, direction=dr)
                        if k:
                            st.success(f"Contributor {k.id} created from {k.source.document} rev {k.source.revision}.")

elif page.startswith("3"):
    st.header("Components, functional features and contacts")
    comp = st.data_editor(pd.DataFrame([c.model_dump() for c in p.components] or [{"id": "", "name": "", "part_number": "",
                          "drawing": "", "revision": ""}]), num_rows="dynamic", use_container_width=True, key="comp")
    feat = st.data_editor(pd.DataFrame([f.model_dump() for f in p.features] or [{"id": "", "component": "", "name": "",
                          "kind": "plane", "role": "none"}]), num_rows="dynamic", use_container_width=True, key="feat",
                          column_config={"kind": st.column_config.SelectboxColumn(options=["plane", "cylinder", "axis", "point", "other"]),
                                         "role": st.column_config.SelectboxColumn(options=["none", "hole", "shaft"])})
    cont = st.data_editor(pd.DataFrame([k.model_dump() for k in p.contacts] or [{"id": "", "feature_a": "", "feature_b": "",
                          "assumption": ""}]), num_rows="dynamic", use_container_width=True, key="cont")
    if st.button("Apply"):
        try:
            p.components = [Component(**{k: (v or "") for k, v in r.items()}) for r in comp.to_dict("records") if r.get("id")]
            p.features = [Feature(**{k: v for k, v in r.items() if _n(v) is not None}) for r in feat.to_dict("records") if r.get("id")]
            p.contacts = [Contact(**{k: (v or "") for k, v in r.items()}) for r in cont.to_dict("records") if r.get("id")]
            st.success("Applied.")
        except Exception as e:  # noqa: BLE001 - shown to the user
            st.error(str(e))

elif page.startswith("4"):
    st.header("Dimensions and geometric tolerances")
    rows = []
    for c in p.contributors:
        t = c.tolerance
        dk, a, b, cc, d = dist_to_cols(c.distribution)
        rows.append({"id": c.id, "name": c.name, "component": c.component, "kind": c.kind,
                     "from_feature": c.from_feature, "to_feature": c.to_feature, "direction": c.direction,
                     "nominal": t.nominal if t else None, "upper": t.upper if t else None,
                     "lower": t.lower if t else None, "unit": t.unit if t else "mm",
                     "origin": t.origin if t else "deviations", "designation": t.designation if t else "",
                     "geometric_id": c.geometric_id, "sensitivity": c.sensitivity, "dist": dk, "p1": a, "p2": b,
                     "p3": cc, "p4": d, "justification": c.justification})
    st.caption("Distribution columns describe the deviation (value − nominal): normal p1=μ p2=σ · uniform p1=low "
               "p2=high · triangular p1=low p2=mode p3=high · truncated_normal p1=μ p2=σ p3=low p4=high.")
    ed = st.data_editor(pd.DataFrame(rows), num_rows="dynamic", use_container_width=True, key="contrib",
                        column_config={
                            "kind": st.column_config.SelectboxColumn(options=["dimension", "size", "geometric", "user_declared_equivalent"]),
                            "dist": st.column_config.SelectboxColumn(options=["none", "normal", "uniform", "triangular", "truncated_normal", "empirical"]),
                            "origin": st.column_config.SelectboxColumn(options=["bilateral", "unilateral", "limits", "deviations", "basic", "iso286", "iso2768", "declared"]),
                            "direction": st.column_config.SelectboxColumn(options=[1, -1])})
    st.subheader("Geometric tolerances")
    grows = []
    for g in p.geometric_tolerances:
        dk, a, b, cc, d = dist_to_cols(g.effect_distribution)
        grows.append({"id": g.id, "type": g.type, "feature_id": g.feature_id, "value": g.value, "unit": g.unit,
                      "diameter_zone": g.diameter_zone, "datums": " ".join(g.datums), "material_modifier": g.material_modifier,
                      "size_principle": g.size_principle, "dist": dk, "p1": a, "p2": b, "notes": g.notes})
    ged = st.data_editor(pd.DataFrame(grows or [{"id": "", "type": "cylindricity", "feature_id": "", "value": 0.0, "unit": "mm",
                         "diameter_zone": False, "datums": "", "material_modifier": None, "size_principle": None,
                         "dist": "none", "p1": None, "p2": None, "notes": ""}]),
                         num_rows="dynamic", use_container_width=True, key="geo",
                         column_config={"size_principle": st.column_config.SelectboxColumn(options=["independency", "envelope"]),
                                        "dist": st.column_config.SelectboxColumn(options=["none", "uniform", "triangular", "truncated_normal"])})
    if st.button("Apply"):
        try:
            old = {c.id: c for c in p.contributors}
            new = []
            for r in ed.to_dict("records"):
                if not r.get("id"):
                    continue
                r = {k: _n(v) for k, v in r.items()}
                tol = None
                if r["kind"] != "geometric" and r.get("nominal") is not None:
                    tol = ToleranceSpec(nominal=float(r["nominal"]), upper=float(r["upper"] or 0), lower=float(r["lower"] or 0),
                                        unit=r["unit"] or "mm", origin=r["origin"] or "deviations", designation=r["designation"] or "")
                o = old.get(r["id"])
                new.append(Contributor(
                    id=r["id"], name=r["name"] or "", component=r["component"] or "", kind=r["kind"] or "dimension",
                    from_feature=r["from_feature"], to_feature=r["to_feature"],
                    direction=int(r["direction"]) if r["direction"] is not None else None, tolerance=tol,
                    geometric_id=r["geometric_id"], sensitivity=float(r["sensitivity"]) if r["sensitivity"] is not None else None,
                    distribution=cols_to_dist(r["dist"], r["p1"], r["p2"], r["p3"], r["p4"], o.distribution if o else None),
                    justification=r["justification"] or "", source=o.source if o else None, notes=o.notes if o else ""))
            gnew = []
            gold = {g.id: g for g in p.geometric_tolerances}
            for r in ged.to_dict("records"):
                if not r.get("id"):
                    continue
                r = {k: _n(v) for k, v in r.items()}
                o = gold.get(r["id"])
                gnew.append(GeometricTolerance(
                    id=r["id"], type=r["type"], feature_id=r["feature_id"] or "", value=float(r["value"] or 0), unit=r["unit"] or "mm",
                    diameter_zone=bool(r["diameter_zone"]), datums=(r["datums"] or "").split(),
                    material_modifier=r["material_modifier"], size_principle=r["size_principle"],
                    effect_distribution=cols_to_dist(r["dist"], r["p1"], r["p2"], None, None),
                    standard=o.standard if o else p.standard, source_callout=o.source_callout if o else None,
                    notes=r["notes"] or ""))
            p.contributors, p.geometric_tolerances = new, gnew
            p.log("edit_contributors")
            st.success("Applied.")
        except Exception as e:  # noqa: BLE001
            st.error(str(e))

elif page.startswith("5"):
    st.header("Functional characteristic")
    ch = p.characteristic or FunctionalCharacteristic(id="Y", name="", type="axial_clearance")
    types = list(CharacteristicType.__args__)
    feats = [""] + [f.id for f in p.features]
    with st.form("char"):
        a, b = st.columns(2)
        cid = a.text_input("Id", ch.id)
        name = b.text_input("Name", ch.name)
        ctype = st.selectbox("Type", types, index=types.index(ch.type),
                             help="Loop types: y = pos(end) − pos(start). Fit types: start = hole, end = shaft.")
        a, b, c = st.columns(3)
        sf = a.selectbox("Start boundary feature", feats, index=feats.index(ch.start_feature) if ch.start_feature in feats else 0)
        ef = b.selectbox("End boundary feature", feats, index=feats.index(ch.end_feature) if ch.end_feature in feats else 0)
        unit = c.selectbox("Unit", ["mm", "um", "in"], index=["mm", "um", "in"].index(ch.unit) if ch.unit in ("mm", "um", "in") else 0)
        a, b, c = st.columns(3)
        lsl = a.text_input("LSL (blank = none)", "" if ch.lsl is None else str(ch.lsl))
        usl = b.text_input("USL (blank = none)", "" if ch.usl is None else str(ch.usl))
        nomd = c.text_input("Declared nominal (closure check)", "" if ch.nominal_declared is None else str(ch.nominal_declared))
        axis = st.text_input("Axis / coordinate system", ch.axis)
        conf = st.text_area("Assembly configuration", ch.configuration)
        if st.form_submit_button("Apply"):
            try:
                f = lambda s: float(s.replace(",", ".")) if s.strip() else None  # noqa: E731
                p.characteristic = FunctionalCharacteristic(id=cid, name=name, type=ctype, start_feature=sf or None,
                                                            end_feature=ef or None, unit=unit, lsl=f(lsl), usl=f(usl),
                                                            nominal_declared=f(nomd), axis=axis, configuration=conf)
                st.success("Applied.")
            except Exception as e:  # noqa: BLE001
                st.error(str(e))

elif page.startswith("6"):
    st.header("Stack-up paths")
    st.info("Phase 1: paths are entered by the engineer (automatic generation is Phase 2). The order must follow "
            "the loop from the start boundary to the end boundary.")
    for chn in p.chains:
        st.write(f"**{chn.id}** — {chn.name}: {' → '.join(chn.contributor_ids)}  ·  approval: {chn.approval.state}")
    with st.form("chain"):
        ids = [c.id for c in p.contributors]
        cid = st.text_input("Chain id", "NEW")
        name = st.text_input("Name")
        seq = st.multiselect("Contributors in path order", ids)
        rat = st.text_area("Engineering rationale")
        if st.form_submit_button("Add / replace chain"):
            if not seq:
                st.error("Select at least one contributor.")
            else:
                p.chains = [c for c in p.chains if c.id != cid] + [Chain(id=cid, name=name, contributor_ids=seq, rationale=rat)]
                st.success("Saved.")

elif page.startswith("7"):
    st.header("Path validation and review")
    if not p.chains:
        st.warning("No chain defined."); st.stop()
    cid = st.selectbox("Chain", [c.id for c in p.chains])
    chn = p.chain(cid)
    d = guarded(diagnose, p, chn)
    if d:
        st.markdown(f"### Status: :{STATUS_COLOR[d.status]}[{d.status}]")
        st.code(d.equation)
        if chn.rationale:
            st.caption("Rationale: " + chn.rationale)
        st.subheader("Path")
        for line in d.path_explanation:
            st.markdown("• " + str(line))
        st.subheader("Checks")
        st.dataframe(pd.DataFrame([c.as_dict() for c in d.checks]), use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        c1.subheader("Assumptions")
        for a in d.assumptions:
            c1.markdown("• " + str(a))
        c2.subheader("Missing information")
        for m in d.missing_information or ["—"]:
            c2.markdown("• " + str(m))
        if d.actions:
            st.subheader("Recommended actions")
            for a in d.actions:
                st.markdown("• " + str(a))
        st.subheader("Engineer review")
        st.write(f"Current: **{chn.approval.state}** {chn.approval.reviewer} {chn.approval.timestamp} {chn.approval.comment}")
        with st.form("approve"):
            rev = st.text_input("Reviewer")
            com = st.text_area("Comment")
            dec = st.radio("Decision", ["approved", "rejected"], horizontal=True)
            if st.form_submit_button("Record"):
                if not rev.strip():
                    st.error("Reviewer required.")
                elif dec == "approved" and not d.analysable:
                    st.error(f"A path with status '{d.status}' cannot be approved.")
                else:
                    import datetime as _dt
                    chn.approval = Approval(state=dec, reviewer=rev, comment=com,
                                            timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                                            status_at_review=d.status, diagnostics_snapshot=[c.as_dict() for c in d.checks])
                    p.log("review_chain", chain=cid, decision=dec, reviewer=rev)
                    st.success("Recorded."); st.rerun()

elif page.startswith("8"):
    st.header("Analysis configuration")
    with st.form("cfg"):
        sa = p.statistical_assumption
        rule = st.selectbox("Statistical assumption for contributors without declared distribution",
                            ["none", "normal_k_sigma", "uniform_over_tolerance"],
                            index=["none", "normal_k_sigma", "uniform_over_tolerance"].index(sa.rule),
                            help="Never applied silently: it is listed as an assumption in every result.")
        k = st.number_input("k (half tolerance = k·σ)", value=float(sa.k), min_value=0.5)
        a, b, c = st.columns(3)
        n = a.number_input("Monte Carlo samples", value=int(p.settings.mc_samples), min_value=1000, step=10000)
        seed = b.number_input("Seed", value=int(p.settings.seed), step=1)
        kk = c.number_input("RSS report range ± k·σ", value=float(p.settings.rss_k))
        corr = st.data_editor(pd.DataFrame([x.model_dump() for x in p.correlations] or [{"a": "", "b": "", "rho": 0.0, "source": ""}]),
                              num_rows="dynamic", use_container_width=True, key="corr")
        if st.form_submit_button("Apply"):
            try:
                p.statistical_assumption = StatisticalAssumption(rule=rule, k=k)
                p.settings.mc_samples, p.settings.seed, p.settings.rss_k = int(n), int(seed), float(kk)
                p.correlations = [Correlation(**{kk_: (v if v is not None else "") for kk_, v in r.items()})
                                  for r in corr.to_dict("records") if r.get("a") and r.get("b")]
                st.success("Applied.")
            except Exception as e:  # noqa: BLE001
                st.error(str(e))

elif page.startswith("9"):
    st.header("Results and sensitivity")
    if not p.chains:
        st.warning("No chain defined."); st.stop()
    cid = st.selectbox("Chain", [c.id for c in p.chains])
    if st.button("Run Worst-Case, RSS and Monte Carlo", type="primary"):
        try:
            st.session_state["result"] = run_analysis(p, cid)
        except AnalysisBlocked as e:
            st.session_state.pop("result", None)
            st.error(f"Analysis blocked: {e}")
    res = st.session_state.get("result")
    if res is not None and res.meta["chain_id"] == cid:
        for w in res.warnings:
            st.warning(w)
        u = p.base_unit
        cols = st.columns(3)
        if res.worst_case:
            cols[0].metric("Worst-Case min / max", f"{res.worst_case.minimum:.4f} / {res.worst_case.maximum:.4f} {u}",
                           "exact" if res.worst_case.exact else "conservative bound", delta_color="off")
        if res.rss:
            cols[1].metric("RSS mean ± σ", f"{res.rss.mean:.4f} ± {res.rss.sigma:.4g} {u}",
                           f"P(nc) ≈ {res.rss.p_total:.3g}" if res.rss.p_total is not None else "", delta_color="off")
        if res.monte_carlo:
            m = res.monte_carlo
            cols[2].metric("Monte Carlo P(nonconforming)", f"{m.p_total:.4g}" if m.p_total is not None else "n/a",
                           f"CI [{m.ci_total[0]:.3g}, {m.ci_total[1]:.3g}]" if m.ci_total else "", delta_color="off")
        for k_, v in res.skipped.items():
            st.info(f"{k_.upper()} not computed — {v}")
        for c in res.conclusions:
            st.markdown("• " + str(c))
        if res.monte_carlo is not None and res.monte_carlo.samples is not None:
            fig = go.Figure(go.Histogram(x=res.monte_carlo.samples, nbinsx=80, name="Monte Carlo"))
            for v, lab, col in ((res.lsl, "LSL", "red"), (res.usl, "USL", "red")):
                if v is not None:
                    fig.add_vline(x=v, line_color=col, annotation_text=lab)
            if res.worst_case:
                for v in (res.worst_case.minimum, res.worst_case.maximum):
                    fig.add_vline(x=v, line_dash="dash", line_color="gray", annotation_text="WC")
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), xaxis_title=f"output [{u}]")
            st.plotly_chart(fig, use_container_width=True)
        sens = pd.DataFrame([r.as_dict() for r in res.sensitivity])
        st.subheader("Sensitivity ranking")
        st.caption("sensitivity = physical response; WC share = share of worst-case range; variance share = statistical contribution.")
        st.dataframe(sens, use_container_width=True, hide_index=True)
        fig2 = go.Figure()
        fig2.add_bar(y=sens["contributor_id"], x=sens["wc_share"], orientation="h", name="WC share")
        if sens["variance_share"].notna().any():
            fig2.add_bar(y=sens["contributor_id"], x=sens["variance_share"], orientation="h", name="variance share")
        fig2.update_layout(barmode="group", height=60 + 40 * len(sens), margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)
        st.subheader("What-if: change one tolerance")
        with st.form("whatif"):
            a, b, c = st.columns(3)
            wid = a.selectbox("Contributor", [t.contributor_id for t in res.diagnosis.terms
                                              if p.contributor(t.contributor_id).tolerance is not None])
            t0 = p.contributor(wid).tolerance
            nu = b.number_input("New upper deviation", value=float(t0.upper), format="%.5f")
            nl = c.number_input("New lower deviation", value=float(t0.lower), format="%.5f")
            if st.form_submit_button("Evaluate"):
                w = guarded(what_if, p, wid, upper=nu, lower=nl, chain_id=cid, mc_samples=min(p.settings.mc_samples, 100_000))
                if w:
                    st.dataframe(pd.DataFrame({"baseline": w["baseline"], "modified": w["modified"]}), use_container_width=True)

elif page.startswith("10"):
    st.header("Report")
    res = st.session_state.get("result")
    if res is None:
        st.warning("Run the analysis first (module 9)."); st.stop()
    tmp = Path(tempfile.mkdtemp())
    pdf = export_pdf(p, res, tmp / "report.pdf")
    xl = export_excel(p, res, tmp / "report.xlsx")
    paths = export_csv(p, res, tmp / "csv")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for x in paths:
            z.write(x, x.name)
    st.download_button("PDF report", pdf.read_bytes(), file_name=f"{p.project_id}_{res.meta['chain_id']}.pdf")
    st.download_button("Excel workbook", xl.read_bytes(), file_name=f"{p.project_id}_{res.meta['chain_id']}.xlsx")
    st.download_button("CSV (zip)", buf.getvalue(), file_name=f"{p.project_id}_{res.meta['chain_id']}_csv.zip")
    st.download_button("Result JSON", json.dumps(res.as_dict(), indent=2, default=str, ensure_ascii=False),
                       file_name=f"{p.project_id}_{res.meta['chain_id']}_result.json")
    st.caption(f"Model fingerprint {res.meta['fingerprint']} · seed {res.meta['seed']} · {res.meta['software']}")
