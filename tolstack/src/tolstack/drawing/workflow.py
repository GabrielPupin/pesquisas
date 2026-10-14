"""Engineer confirmation of extracted values and linking of confirmed values into the model."""

from __future__ import annotations

from typing import Optional

from ..errors import InsufficientInformation, ModelError, UnitError
from ..model.contributor import Contributor, SourceRef
from ..model.geometric import GeometricTolerance
from ..model.project import Project
from ..model.tolerance import ToleranceSpec
from .review import Confirmation, DrawingRecord, ParsedCallout


def confirm_title(record: DrawingRecord, field: str, value: Optional[str] = None) -> None:
    cands = [c for c in record.title_block if c.field == field]
    if not cands and value is None:
        raise ModelError(f"No '{field}' candidate on drawing {record.id}; supply the value.")
    if cands:
        c = cands[0]
        if value is not None:
            c.value = value
        c.confirmed = True
    else:
        from .review import TitleBlockCandidate
        record.title_block.append(TitleBlockCandidate(field=field, value=value, raw_text="(entered by reviewer)",
                                                      page=0, bbox=(0, 0, 0, 0), confirmed=True))


def confirm_callout(record: DrawingRecord, callout_id: str, reviewer: str, *,
                    values: Optional[ParsedCallout] = None, decision: str = "confirmed",
                    comment: str = "") -> Confirmation:
    """Record the reviewer's decision. ``values`` (optional) replaces the extracted interpretation."""
    if not reviewer.strip():
        raise ModelError("A reviewer name is required for traceability.")
    c = record.callout(callout_id)
    if decision == "confirmed":
        final = values or c.parsed
        if final is None:
            raise InsufficientInformation(f"{callout_id}: nothing was interpreted from '{c.raw_text}'; enter the "
                                          "values to confirm it.")
        if c.status in ("ambiguous", "unparsed", "unsupported") and values is None:
            raise InsufficientInformation(f"{callout_id} is '{c.status}' ({'; '.join(c.issues)}); confirm with "
                                          "explicit values.")
        if final.kind == "geometric" and not final.geometric_type:
            raise InsufficientInformation(f"{callout_id}: the geometric tolerance type must be selected.")
        if final.unit is None:
            raise InsufficientInformation(f"{callout_id}: unit not known; set it in the confirmed values.")
    else:
        final = None
    conf = Confirmation(callout_id=callout_id, decision=decision, values=final,
                        edited=values is not None and values != c.parsed,
                        original=c.parsed, reviewer=reviewer, comment=comment)
    record.confirmations.append(conf)
    return conf


def _source(record: DrawingRecord, c, conf: Confirmation) -> SourceRef:
    return SourceRef(document=record.confirmed_title("drawing_number") or record.file_name,
                     revision=record.confirmed_title("revision") or "", page=c.page, bbox=c.bbox,
                     callout_id=c.id, raw_text=c.raw_text, entered_by=conf.reviewer)


def link_dimension(project: Project, drawing_id: str, callout_id: str, contributor_id: str, *,
                   name: str = "", component: str = "", from_feature: Optional[str] = None,
                   to_feature: Optional[str] = None, direction: Optional[int] = None) -> Contributor:
    record = project.drawing(drawing_id)
    c = record.callout(callout_id)
    conf = record.confirmation_for(callout_id)
    if conf is None or conf.decision != "confirmed":
        raise InsufficientInformation(f"{callout_id} has not been confirmed by a reviewer; it cannot be used.")
    v = conf.values
    if v.kind == "geometric":
        raise ModelError(f"{callout_id} is a geometric tolerance; use link_geometric.")
    if v.kind == "angle":
        raise UnitError(f"{callout_id} is angular; Phase 1 linear chains accept length dimensions only.")
    if v.tolerance_origin == "general" and record.confirmed_title("general_tolerance") is None:
        raise InsufficientInformation(f"{callout_id} relies on the general-tolerance note, which is not confirmed.")
    if v.nominal is None or (not v.basic and (v.upper is None or v.lower is None)):
        raise InsufficientInformation(f"{callout_id}: nominal/deviations incomplete in the confirmed values.")
    if v.basic:
        tol = ToleranceSpec.basic(v.nominal, v.unit)
    else:
        origin = {"bilateral": "bilateral", "deviations": "deviations", "limits": "limits", "iso286": "iso286",
                  "general": "iso2768"}.get(v.tolerance_origin or "", "declared")
        tol = ToleranceSpec(nominal=v.nominal, upper=v.upper, lower=v.lower, unit=v.unit, origin=origin,
                            designation=v.designation)
    kind = "size" if v.kind == "diameter" else "dimension"
    contrib = Contributor(id=contributor_id, name=name or c.raw_text, component=component, kind=kind,
                          from_feature=from_feature, to_feature=to_feature, direction=direction, tolerance=tol,
                          source=_source(record, c, conf))
    if v.count > 1:
        contrib.notes = f"Callout applies to {v.count} features; this contributor represents one of them."
    project.contributors = [x for x in project.contributors if x.id != contributor_id] + [contrib]
    project.log("link_dimension", drawing=drawing_id, callout=callout_id, contributor=contributor_id)
    return contrib


def link_geometric(project: Project, drawing_id: str, callout_id: str, geometric_id: str, feature_id: str, *,
                   size_principle: Optional[str] = None, effect_distribution=None) -> GeometricTolerance:
    record = project.drawing(drawing_id)
    conf = record.confirmation_for(callout_id)
    if conf is None or conf.decision != "confirmed":
        raise InsufficientInformation(f"{callout_id} has not been confirmed by a reviewer; it cannot be used.")
    v = conf.values
    if v.kind != "geometric":
        raise ModelError(f"{callout_id} is not a geometric tolerance.")
    notes = ""
    if size_principle is None:
        sp = record.confirmed_title("size_principle")
        if sp:
            size_principle = sp
            notes = f"Size principle '{sp}' taken from the confirmed drawing note."
    gt = GeometricTolerance(id=geometric_id, type=v.geometric_type, feature_id=feature_id, value=v.geometric_value,
                            unit=v.unit, diameter_zone=v.diameter_zone, datums=v.datums,
                            material_modifier=v.material_modifier, size_principle=size_principle,
                            effect_distribution=effect_distribution, source_callout=callout_id, notes=notes)
    project.geometric_tolerances = [g for g in project.geometric_tolerances if g.id != geometric_id] + [gt]
    project.log("link_geometric", drawing=drawing_id, callout=callout_id, geometric=geometric_id)
    return gt
