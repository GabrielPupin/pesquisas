"""Validation of a 1D stack-up chain and resolution of its terms.

The checker answers four distinct questions and reports them separately:
  topological  – does the path connect the start boundary to the end boundary through declared
                 dimensions and contacts?
  mathematical – does the signed sum close (nominal check, units, duplicates, correlation matrix)?
  geometric    – are the dimensions/features/tolerances geometrically meaningful in a 1D model?
  functional   – does the chain represent the characteristic (completeness, unmodelled effects)?

A closed loop is never sufficient on its own. Phase 1 never assigns "Validated": the software cannot
verify the physical behaviour of the assembly, so the best status is "Conditionally Valid" with the
assumptions listed explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from ..errors import ModelError, UnitError
from ..model.characteristic import FIT_TYPES, LOOP_TYPES, UNSUPPORTED_TYPES
from ..model.correlation import correlation_matrix
from ..model.distributions import Empirical, Normal, Triangular, TruncatedNormal, Uniform
from ..model.geometric import FORM_TYPES
from ..model.project import Chain, Project
from ..units import factor as unit_factor

Status = Literal["Validated", "Conditionally Valid", "Invalid", "Insufficient Information"]
Outcome = Literal["passed", "failed", "not_evaluable", "warning"]
Category = Literal["topological", "mathematical", "geometric", "functional", "data"]


@dataclass
class CheckResult:
    id: str
    title: str
    category: Category
    outcome: Outcome
    severity: Optional[Literal["invalid", "insufficient", "warning"]] = None
    details: list[str] = field(default_factory=list)
    action: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "category": self.category, "outcome": self.outcome,
                "severity": self.severity, "details": list(self.details), "action": self.action}


@dataclass
class ResolvedTerm:
    contributor_id: str
    name: str
    component: str
    kind: str
    sensitivity: float
    nominal: float  # base unit
    lower: float  # deviation, base unit
    upper: float  # deviation, base unit
    distribution: object = None  # distribution of the deviation in base unit (or None)
    distribution_origin: str = ""  # "declared", "assumed: ..." or ""
    original_unit: str = ""
    tolerance_text: str = ""
    source_text: str = ""
    sign_origin: str = ""

    @property
    def width(self) -> float:
        return self.upper - self.lower


@dataclass
class ChainDiagnosis:
    chain_id: str
    status: Status
    checks: list[CheckResult]
    terms: list[ResolvedTerm]
    assumptions: list[str]
    missing_information: list[str]
    problems: list[str]
    actions: list[str]
    path_explanation: list[str]
    equation: str
    model_dimension: str
    statistical_ready: bool
    statistical_reason: str
    correlation: object = None  # numpy matrix over terms, or None

    @property
    def analysable(self) -> bool:
        return self.status in ("Validated", "Conditionally Valid")

    def as_dict(self) -> dict:
        return {
            "chain_id": self.chain_id, "status": self.status,
            "checks": [c.as_dict() for c in self.checks],
            "assumptions": self.assumptions, "missing_information": self.missing_information,
            "problems": self.problems, "actions": self.actions, "path_explanation": self.path_explanation,
            "equation": self.equation, "model_dimension": self.model_dimension,
            "statistical_ready": self.statistical_ready, "statistical_reason": self.statistical_reason,
        }


def scale_distribution(d, f: float):
    """Express a deviation distribution in another unit (f = multiplicative factor)."""
    if d is None:
        return None
    if isinstance(d, Normal):
        return Normal(mu=d.mu * f, sigma=d.sigma * f)
    if isinstance(d, Uniform):
        return Uniform(low=d.low * f, high=d.high * f)
    if isinstance(d, Triangular):
        return Triangular(low=d.low * f, mode=d.mode * f, high=d.high * f)
    if isinstance(d, TruncatedNormal):
        return TruncatedNormal(mu=d.mu * f, sigma=d.sigma * f, low=d.low * f, high=d.high * f)
    if isinstance(d, Empirical):
        return Empirical(samples=[s * f for s in d.samples], source=d.source)
    raise ModelError(f"Unknown distribution {type(d).__name__}")


class _Ctx:
    def __init__(self):
        self.checks: list[CheckResult] = []
        self.assumptions: list[str] = []
        self.missing: list[str] = []

    def add(self, cid, title, category, outcome, severity=None, details=None, action=""):
        if severity not in (None, "invalid", "insufficient", "warning"):
            raise ValueError(f"check {cid}: bad severity {severity!r}")
        if (outcome == "failed") != (severity in ("invalid", "insufficient")) and not (
                outcome == "failed" and severity == "warning"):
            raise ValueError(f"check {cid}: outcome {outcome!r} inconsistent with severity {severity!r}")
        r = CheckResult(cid, title, category, outcome, severity, list(details or []), action)
        self.checks.append(r)
        return r

    def assume(self, text: str):
        if text not in self.assumptions:
            self.assumptions.append(text)

    def need(self, text: str):
        if text not in self.missing:
            self.missing.append(text)


def _fmt(x: float) -> str:
    return f"{x:+.6g}"


def diagnose(project: Project, chain: Chain | str | None = None) -> ChainDiagnosis:
    if not isinstance(chain, Chain):
        chain = project.chain(chain)
    ctx = _Ctx()
    base = project.base_unit
    ch = project.characteristic

    # ---------------------------------------------------------------- characteristic
    if ch is None:
        ctx.add("CHAR", "Functional characteristic defined", "functional", "failed", "insufficient",
                ["No functional characteristic defined."], "Define the characteristic and its limits.")
    else:
        det, sev = [], None
        if ch.type in UNSUPPORTED_TYPES:
            det.append(f"Characteristic type '{ch.type}' needs a 2D/3D geometric model (Phase 3+).")
            sev = "insufficient"
        try:
            unit_factor(ch.unit, base)
        except UnitError as e:
            det.append(str(e))
            sev = "invalid"
        if ch.lsl is not None and ch.usl is not None and ch.lsl > ch.usl:
            det.append(f"LSL ({ch.lsl}) is above USL ({ch.usl}).")
            sev = "invalid"
        if sev:
            ctx.add("CHAR", "Functional characteristic consistent and supported", "functional", "failed",
                    sev, det, "Correct the characteristic definition.")
        else:
            ctx.add("CHAR", "Functional characteristic consistent and supported", "functional", "passed",
                    details=[f"{ch.name} ({ch.type}), axis {ch.axis}"])
        if ch.lsl is None and ch.usl is None:
            ctx.add("LIMITS", "Acceptance limits defined", "functional", "warning", "warning",
                    ["No LSL/USL: conformity and failure probability cannot be evaluated."],
                    "Enter the allowable minimum and/or maximum of the characteristic.")
            ctx.need("Acceptance limits (LSL/USL) of the functional characteristic.")
        else:
            ctx.add("LIMITS", "Acceptance limits defined", "functional", "passed",
                    details=[f"LSL={ch.lsl}, USL={ch.usl} {ch.unit}"])
        if ch.configuration:
            ctx.assume(f"Assembly configuration: {ch.configuration}")

    # ---------------------------------------------------------------- references and duplicates
    contributors = []
    bad_refs = []
    for cid in chain.contributor_ids:
        try:
            contributors.append(project.contributor(cid))
        except ModelError:
            bad_refs.append(cid)
    if not chain.contributor_ids:
        ctx.add("REF", "Chain references existing contributors", "data", "failed", "invalid",
                ["Chain is empty."], "Add contributors to the chain.")
    elif bad_refs:
        ctx.add("REF", "Chain references existing contributors", "data", "failed", "invalid",
                [f"Unknown contributor id(s): {bad_refs}"], "Fix the contributor ids in the chain.")
    else:
        ctx.add("REF", "Chain references existing contributors", "data", "passed")

    dup_ids = sorted({c for c in chain.contributor_ids if chain.contributor_ids.count(c) > 1})
    pair_dups = []
    seen_pairs = {}
    for c in contributors:
        if c.kind == "dimension" and c.from_feature and c.to_feature:
            key = frozenset((c.from_feature, c.to_feature))
            if key in seen_pairs and seen_pairs[key] != c.id:
                pair_dups.append(f"'{seen_pairs[key]}' and '{c.id}' both span {sorted(key)}")
            seen_pairs.setdefault(key, c.id)
        if c.kind == "geometric" and c.geometric_id:
            key = ("geo", c.geometric_id)
            if key in seen_pairs and seen_pairs[key] != c.id:
                pair_dups.append(f"'{seen_pairs[key]}' and '{c.id}' both use geometric tolerance {c.geometric_id}")
            seen_pairs.setdefault(key, c.id)
    if dup_ids or pair_dups:
        det = [f"Contributor used more than once: {dup_ids}"] if dup_ids else []
        ctx.add("DUP", "No duplicated contributions", "mathematical", "failed", "invalid", det + pair_dups,
                "Remove the duplicated term; each physical variation must enter the equation once.")
    else:
        ctx.add("DUP", "No duplicated contributions", "mathematical", "passed")

    # ---------------------------------------------------------------- units and tolerances
    unit_err, tol_missing, basic_terms, equiv_missing = [], [], [], []
    for c in contributors:
        if c.kind == "geometric":
            continue
        if c.tolerance is None:
            tol_missing.append(c.id)
            continue
        try:
            unit_factor(c.tolerance.unit, base)
        except UnitError as e:
            unit_err.append(f"{c.id}: {e}")
        if c.tolerance.origin == "basic":
            basic_terms.append(c.id)
        if c.kind == "user_declared_equivalent" and not c.justification.strip():
            equiv_missing.append(c.id)
    if unit_err:
        ctx.add("UNIT", "Units valid and convertible to the project unit", "mathematical", "failed", "invalid",
                unit_err, "Use mm, µm or in for linear contributors.")
    else:
        ctx.add("UNIT", "Units valid and convertible to the project unit", "mathematical", "passed",
                details=[f"Project unit: {base}"])
    if tol_missing:
        ctx.add("TOL", "Every contributor has nominal and deviations", "data", "failed", "insufficient",
                [f"No tolerance for: {tol_missing}"], "Enter nominal and deviations (or confirm the drawing value).")
        for t in tol_missing:
            ctx.need(f"Tolerance of contributor '{t}'.")
    else:
        ctx.add("TOL", "Every contributor has nominal and deviations", "data", "passed")
    if basic_terms:
        ctx.add("BASIC", "Basic dimensions have their variation modelled", "geometric", "failed", "insufficient",
                [f"{b}: theoretically exact dimension — its variation is set by a geometric tolerance "
                 "(position/profile/angularity) that Phase 1 does not propagate." for b in basic_terms],
                "Model the controlling geometric tolerance (Phase 3) or replace with a toleranced dimension "
                "only if the drawing actually specifies one.")
        for b in basic_terms:
            ctx.need(f"Propagation of the geometric tolerance controlling basic dimension '{b}'.")
    if equiv_missing:
        ctx.add("EQUIV", "User-declared equivalents are justified", "functional", "failed", "insufficient",
                [f"{e}: no justification given" for e in equiv_missing],
                "Document why the linear equivalent represents the geometric effect.")
    for c in contributors:
        if c.kind == "user_declared_equivalent" and c.justification.strip():
            ctx.assume(f"User-declared linear equivalent '{c.id}' (not verified by the software): {c.justification}")

    # ---------------------------------------------------------------- sign / topology
    signs: dict[str, float] = {}
    sign_origin: dict[str, str] = {}
    path_expl: list[str] = []
    geo_terms: dict[str, tuple[float, float, str]] = {}  # id -> (lower, upper, unit)

    ctype = ch.type if ch else None
    if ch is not None and ctype in LOOP_TYPES:
        _loop_topology(project, ch, contributors, ctx, signs, sign_origin, path_expl)
    elif ch is not None and ctype in FIT_TYPES:
        _fit_topology(project, ch, contributors, ctx, signs, sign_origin, path_expl, geo_terms)
    elif ch is not None and ctype == "user_defined_scalar":
        missing = [c.id for c in contributors if c.sensitivity is None]
        ctx.add("TOPO", "Path topology", "topological", "not_evaluable",
                details=["User-defined scalar: the equation is defined by the engineer; topology is not checked."])
        if missing:
            ctx.add("SIGN", "Sensitivities defined", "mathematical", "failed", "insufficient",
                    [f"No sensitivity for: {missing}"], "Declare each sensitivity coefficient.")
        else:
            ctx.add("SIGN", "Sensitivities defined", "mathematical", "passed")
        for c in contributors:
            if c.sensitivity is not None:
                signs[c.id] = float(c.sensitivity)
                sign_origin[c.id] = "declared by user (not verified)"
        ctx.assume("Output equation and sensitivity signs declared by the user; not derived from geometry.")
        for c in contributors:
            if c.kind == "geometric":
                ctx.add("GEO-" + c.id, f"Geometric contributor {c.id}", "geometric", "failed", "invalid",
                        ["Geometric tolerances are propagated only for diametral fits in Phase 1; use a "
                         "user_declared_equivalent with justification if an equivalent is intended."],
                        "Change the contributor kind or the characteristic type.")

    # geometric tolerances on features of the chain that are not represented
    _unmodelled_geometric(project, contributors, ctx, ch)

    # ---------------------------------------------------------------- nominal closure
    terms: list[ResolvedTerm] = []
    if ch is not None and not unit_err:
        for c in contributors:
            if c.id not in signs:
                continue
            if c.kind == "geometric":
                if c.id not in geo_terms:
                    continue
                lo, up, u = geo_terms[c.id]
                f = unit_factor(u, base)
                gt = project.geometric(c.geometric_id)
                terms.append(ResolvedTerm(
                    c.id, c.name or gt.type, c.component, c.kind, signs[c.id], 0.0, lo * f, up * f,
                    original_unit=u, tolerance_text=gt.zone_description(),
                    source_text=_source_text(c), sign_origin=sign_origin.get(c.id, "")))
                continue
            if c.tolerance is None:
                continue
            f = unit_factor(c.tolerance.unit, base)
            t = c.tolerance
            terms.append(ResolvedTerm(
                c.id, c.name or c.id, c.component, c.kind, signs[c.id], t.nominal * f, t.lower * f, t.upper * f,
                original_unit=t.unit,
                tolerance_text=f"{t.nominal:g} {t.designation or (_fmt(t.upper) + '/' + _fmt(t.lower))} {t.unit}",
                source_text=_source_text(c), sign_origin=sign_origin.get(c.id, "")))
        y0 = sum(t.sensitivity * t.nominal for t in terms)
        if ch.nominal_declared is not None and len(terms) == len(contributors):
            decl = ch.nominal_declared * unit_factor(ch.unit, base)
            if abs(y0 - decl) > 1e-9 * max(1.0, abs(decl)):
                ctx.add("CLOSURE", "Nominal closure", "mathematical", "failed", "invalid",
                        [f"Σ s·nominal = {y0:.6g} {base} but the declared nominal is {decl:.6g} {base}. "
                         "A sign, a dimension or the boundary definition is wrong."],
                        "Check signs/directions and the declared nominal.")
            else:
                ctx.add("CLOSURE", "Nominal closure", "mathematical", "passed",
                        details=[f"Σ s·nominal = {y0:.6g} {base} matches the declared nominal."])
        else:
            ctx.add("CLOSURE", "Nominal closure", "mathematical", "not_evaluable",
                    details=[f"No declared nominal to compare (computed nominal {y0:.6g} {base})."])

    # ---------------------------------------------------------------- distributions
    stat_missing = []
    sa = project.statistical_assumption
    for t in terms:
        c = project.contributor(t.contributor_id)
        if t.kind == "geometric":
            gt = project.geometric(c.geometric_id)
            d = c.distribution or gt.effect_distribution
            if d is not None:
                t.distribution = scale_distribution(d, unit_factor(gt.unit, base))
                t.distribution_origin = "declared"
            else:
                stat_missing.append(t.contributor_id)
            continue
        if c.distribution is not None:
            t.distribution = scale_distribution(c.distribution, unit_factor(c.tolerance.unit, base))
            t.distribution_origin = "declared"
        elif t.width == 0:
            t.distribution = None
            t.distribution_origin = "fixed (zero tolerance)"
        else:
            d = sa.apply(t.lower, t.upper)
            if d is None:
                stat_missing.append(t.contributor_id)
            else:
                t.distribution = d
                t.distribution_origin = f"assumed ({sa.rule})"
                ctx.assume(sa.describe())
    for t in terms:
        if t.distribution is not None and t.distribution_origin == "declared":
            lo, hi = t.distribution.support()
            m = t.distribution.mean()
            if not (t.lower - 1e-12 <= m <= t.upper + 1e-12):
                ctx.add("DIST-" + t.contributor_id, f"Distribution of {t.contributor_id} within tolerance",
                        "data", "warning", "warning",
                        [f"Declared mean deviation {m:.4g} lies outside [{t.lower:.4g}, {t.upper:.4g}]."],
                        "Check the process data or the tolerance.")
    if stat_missing:
        ctx.add("STAT", "Statistical description available", "data", "warning", "warning",
                [f"No distribution for: {stat_missing}. RSS and Monte Carlo are unavailable; Worst-Case is "
                 "unaffected."],
                "Declare distributions from process data, or configure an explicit statistical assumption.")
        for s in stat_missing:
            ctx.need(f"Distribution (process capability) of '{s}'.")
        stat_ready, stat_reason = False, f"missing distributions: {stat_missing}"
    else:
        ctx.add("STAT", "Statistical description available", "data", "passed")
        stat_ready, stat_reason = True, ""

    # ---------------------------------------------------------------- correlation
    R = None
    try:
        R = correlation_matrix([t.contributor_id for t in terms], project.correlations)
        n_corr = int(((abs(R) > 0).sum() - len(terms)) / 2) if len(terms) else 0
        ctx.add("CORR", "Correlation matrix consistent", "mathematical", "passed",
                details=[f"{n_corr} correlated pair(s)" if n_corr else "Contributors treated as independent."])
        if not n_corr and len(terms) > 1:
            ctx.assume("Contributors are statistically independent (no correlation declared).")
    except ModelError as e:
        ctx.add("CORR", "Correlation matrix consistent", "mathematical", "failed", "invalid", [str(e)],
                "Correct the declared correlations.")

    # ---------------------------------------------------------------- model dimension
    if ch is not None and ctype in LOOP_TYPES:
        ctx.add("DIM", "1D representation adequate", "geometric", "warning", "warning",
                ["1D loop: features assumed perpendicular to the stack axis; form/orientation deviations of "
                 "contact faces and tilt of parts are not represented."],
                "If parts can tilt or faces carry orientation tolerances, a 2D model is required (Phase 3).")
        ctx.assume("1D model: all loop features perpendicular to the stack axis; contact faces ideal planes.")
    elif ch is not None and ctype in FIT_TYPES:
        ctx.add("DIM", "1D representation adequate", "geometric", "warning", "warning",
                ["Diametral fit of one hole–shaft pair: axis offset/tilt between hole and shaft not represented."],
                "For alignment or radial clearance at a given location, a 2D/3D model is required.")
        ctx.assume("1D diametral model: clearance = mating hole size − mating shaft size; misalignment ignored.")

    # ---------------------------------------------------------------- status
    sev = {c.severity for c in ctx.checks if c.outcome == "failed"}
    if "invalid" in sev:
        status: Status = "Invalid"
    elif "insufficient" in sev:
        status = "Insufficient Information"
    else:
        status = "Conditionally Valid"
    problems = [f"[{c.id}] " + "; ".join(c.details) for c in ctx.checks if c.outcome in ("failed", "warning")]
    actions = sorted({c.action for c in ctx.checks if c.outcome in ("failed", "warning") and c.action})
    eq = "y = " + " ".join(f"{'+' if t.sensitivity >= 0 else '−'}{abs(t.sensitivity):g}·{t.contributor_id}"
                           for t in terms) if terms else "y = (undetermined)"
    return ChainDiagnosis(chain.id, status, ctx.checks, terms, ctx.assumptions, ctx.missing, problems, actions,
                          path_expl, eq, "1D", stat_ready, stat_reason, R)


def _source_text(c) -> str:
    s = c.source
    if s is None:
        return "manual entry"
    parts = [p for p in (s.document, f"rev {s.revision}" if s.revision else "",
                         f"p.{s.page}" if s.page else "", f"callout {s.callout_id}" if s.callout_id else "") if p]
    return ", ".join(parts) or "manual entry"


def _linked(project: Project, a: str, b: str) -> Optional[str]:
    """Return '' if a == b, the contact id if a and b are joined by a declared contact, else None."""
    if a == b:
        return ""
    for k in project.contacts:
        if {k.feature_a, k.feature_b} == {a, b}:
            return k.id
    return None


def _loop_topology(project, ch, contributors, ctx: _Ctx, signs, sign_origin, path_expl):
    det, fails = [], []
    if not ch.start_feature or not ch.end_feature:
        ctx.add("TOPO", "Path connects start and end boundaries", "topological", "failed", "insufficient",
                ["Characteristic has no start/end boundary features."],
                "Select the two features that bound the characteristic.")
        ctx.need("Start and end boundary features of the characteristic.")
        return
    for fid in (ch.start_feature, ch.end_feature):
        if project.feature(fid) is None:
            fails.append(f"Boundary feature '{fid}' is not defined.")
    incomplete = [c.id for c in contributors
                  if c.kind in ("dimension", "user_declared_equivalent")
                  and (not c.from_feature or not c.to_feature or c.direction is None)]
    wrong_kind = [c.id for c in contributors if c.kind in ("size", "geometric")]
    if wrong_kind:
        ctx.add("KIND", "Contributor kinds compatible with an axial loop", "geometric", "failed", "invalid",
                [f"{w}: a feature size or a form tolerance is not a distance along the stack axis." for w in wrong_kind],
                "Remove these terms, or model their effect explicitly as a justified equivalent.")
    if incomplete:
        declared = all(project.contributor(i).sensitivity is not None for i in incomplete)
        if declared:
            ctx.add("TOPO", "Path connects start and end boundaries", "topological", "not_evaluable",
                    details=[f"No feature/direction data for {incomplete}; declared signs used without verification."])
            for c in contributors:
                if c.sensitivity is not None:
                    signs[c.id] = float(c.sensitivity)
                    sign_origin[c.id] = "declared by user (not verified)"
            ctx.assume("Signs of contributors without topology data are user-declared and not verified.")
        else:
            ctx.add("TOPO", "Path connects start and end boundaries", "topological", "failed", "insufficient",
                    [f"No from/to features and direction (or declared sensitivity) for {incomplete}."],
                    "Enter from/to features and direction for each dimension.")
            ctx.need(f"Feature/direction data for contributors {incomplete}.")
        return

    current = ch.start_feature
    path_expl.append(f"Start at boundary {current}.")
    visited = [current]
    contacts_used = []
    for c in contributors:
        if c.kind not in ("dimension", "user_declared_equivalent"):
            continue
        fa, fb = project.feature(c.from_feature), project.feature(c.to_feature)
        if fa is None or fb is None:
            fails.append(f"{c.id}: unknown feature(s) {c.from_feature}/{c.to_feature}.")
            break
        if fa.component != fb.component:
            fails.append(f"{c.id}: a single dimension spans two components ({fa.component}, {fb.component}); "
                         "assembly interfaces must be modelled as contacts.")
        if c.component and c.component != fa.component:
            fails.append(f"{c.id}: contributor component '{c.component}' differs from its features' component "
                         f"'{fa.component}'.")
        lf, lt = _linked(project, current, c.from_feature), _linked(project, current, c.to_feature)
        if lf is not None and lt is not None:
            fails.append(f"{c.id}: ambiguous traversal — both ends connect to {current}.")
            break
        if lf is not None:
            sign, nxt, via, enter = float(c.direction), c.to_feature, lf, c.from_feature
            how = "forward"
        elif lt is not None:
            sign, nxt, via, enter = -float(c.direction), c.from_feature, lt, c.to_feature
            how = "reversed"
        else:
            fails.append(f"Discontinuity: {c.id} ({c.from_feature}→{c.to_feature}) does not connect to "
                         f"{current}, directly or through a declared contact.")
            break
        if via:
            k = next(k for k in project.contacts if k.id == via)
            contacts_used.append(k)
            path_expl.append(f"Cross contact {via}: {current} ≡ {enter}"
                             + (f" ({k.assumption})" if k.assumption else " (no justification recorded)"))
        if c.sensitivity is not None and c.sensitivity * sign <= 0:
            fails.append(f"{c.id}: declared sensitivity {c.sensitivity:+g} contradicts the sign derived from "
                         f"topology ({sign:+g}).")
        mag = abs(c.sensitivity) if c.sensitivity is not None else 1.0
        if mag != 1.0:
            ctx.assume(f"{c.id}: non-unit coefficient {mag:g} declared by user in a 1D loop.")
        signs[c.id] = sign * mag
        sign_origin[c.id] = f"derived from topology ({how}, direction {c.direction:+d})"
        path_expl.append(f"{c.id} {how}: {enter} → {nxt}  ⇒ contributes {sign * mag:+g}·{c.id}")
        current = nxt
        if current in visited:
            det.append(f"Feature {current} visited twice — the path contains a sub-loop.")
        visited.append(current)
    else:
        end_link = _linked(project, current, ch.end_feature)
        if end_link is None:
            fails.append(f"Path ends at {current}, not at the end boundary {ch.end_feature}: the loop is open.")
        else:
            if end_link:
                k = next(k for k in project.contacts if k.id == end_link)
                contacts_used.append(k)
                path_expl.append(f"Cross contact {end_link}: {current} ≡ {ch.end_feature}")
            path_expl.append(f"Reach end boundary {ch.end_feature}. y = pos({ch.end_feature}) − "
                             f"pos({ch.start_feature}) along {ch.axis}.")
    if fails:
        ctx.add("TOPO", "Path connects start and end boundaries", "topological", "failed", "invalid", fails + det,
                "Correct the path order, feature references, directions or missing contacts.")
        return
    ctx.add("TOPO", "Path connects start and end boundaries", "topological",
            "warning" if det else "passed", "warning" if det else None,
            det or [f"Closed path through {len(contributors)} contributor(s) and {len(contacts_used)} contact(s)."])
    bad_contacts = []
    for k in contacts_used:
        fa, fb = project.feature(k.feature_a), project.feature(k.feature_b)
        if fa and fb and fa.component == fb.component:
            bad_contacts.append(f"{k.id} joins two features of the same component ({fa.component}).")
        ctx.assume(f"Contact {k.id} ({k.feature_a} ≡ {k.feature_b}) is maintained"
                   + (f": {k.assumption}" if k.assumption else " — NO justification recorded."))
    unjust = [k.id for k in contacts_used if not k.assumption.strip()]
    if bad_contacts or unjust:
        ctx.add("CONTACT", "Contacts are physical interfaces and justified", "functional", "warning", "warning",
                bad_contacts + ([f"No justification for contact(s) {unjust}"] if unjust else []),
                "State why each contact is maintained (preload, gravity, fastener, assembly procedure).")
    else:
        ctx.add("CONTACT", "Contacts are physical interfaces and justified", "functional", "passed")


def _fit_topology(project, ch, contributors, ctx: _Ctx, signs, sign_origin, path_expl, geo_terms):
    fails, insuff = [], []
    hole, shaft = ch.start_feature, ch.end_feature
    hf, sf = project.feature(hole) if hole else None, project.feature(shaft) if shaft else None
    if hf is None or sf is None:
        ctx.add("TOPO", "Fit features defined", "topological", "failed", "insufficient",
                ["Diametral fit requires start_feature = hole and end_feature = shaft (both defined)."],
                "Select the hole and shaft features.")
        return
    if hf.role == "shaft" or sf.role == "hole":
        fails.append("Feature roles contradict the fit definition (start must be the hole, end the shaft).")
    k = 1.0 if ch.type == "diametral_clearance" else -1.0
    sizes = {hole: [], shaft: []}
    for c in contributors:
        if c.kind == "size":
            if c.from_feature in sizes:
                sign = k if c.from_feature == hole else -k
                if c.sensitivity is not None and c.sensitivity * sign <= 0:
                    fails.append(f"{c.id}: declared sensitivity contradicts the fit equation sign ({sign:+g}).")
                signs[c.id] = sign
                sign_origin[c.id] = f"fit equation ({'hole' if c.from_feature == hole else 'shaft'} size)"
                sizes[c.from_feature].append(c.id)
                path_expl.append(f"{c.id}: size of {'hole' if c.from_feature == hole else 'shaft'} "
                                 f"{c.from_feature} ⇒ {sign:+g}·{c.id}")
            else:
                fails.append(f"{c.id}: size of feature '{c.from_feature}', which is not part of this fit.")
        elif c.kind == "geometric":
            _cylindricity_term(project, ch, c, k, hole, shaft, ctx, fails, insuff, signs, sign_origin,
                               path_expl, geo_terms)
        elif c.kind == "user_declared_equivalent":
            if c.sensitivity is None:
                insuff.append(f"{c.id}: declared equivalent needs an explicit sensitivity.")
            else:
                signs[c.id] = float(c.sensitivity)
                sign_origin[c.id] = "declared by user (not verified)"
                path_expl.append(f"{c.id}: user-declared equivalent ⇒ {c.sensitivity:+g}·{c.id}")
        else:
            fails.append(f"{c.id}: a distance dimension does not enter a 1D diametral fit "
                         "(coaxiality/position effects need a 2D model).")
    for f, ids in sizes.items():
        role = "hole" if f == hole else "shaft"
        if not ids:
            insuff.append(f"Missing contributor: size of the {role} {f}.")
            ctx.need(f"Size tolerance of the {role} '{f}'.")
        elif len(ids) > 1:
            fails.append(f"Size of the {role} {f} entered {len(ids)} times: {ids}.")
    if fails:
        ctx.add("TOPO", "Fit equation complete and consistent", "topological", "failed", "invalid", fails + insuff,
                "Correct the fit contributors.")
    elif insuff:
        ctx.add("TOPO", "Fit equation complete and consistent", "topological", "failed", "insufficient", insuff,
                "Supply the missing information.")
    else:
        ctx.add("TOPO", "Fit equation complete and consistent", "topological", "passed",
                details=[f"{'C' if k > 0 else 'I'} = {'D_hole − d_shaft' if k > 0 else 'd_shaft − D_hole'} "
                 "(mating sizes)"])


def _cylindricity_term(project, ch, c, k, hole, shaft, ctx, fails, insuff, signs, sign_origin, path_expl,
                       geo_terms):
    gt = project.geometric(c.geometric_id) if c.geometric_id else None
    if gt is None:
        fails.append(f"{c.id}: geometric tolerance '{c.geometric_id}' not found.")
        return
    if gt.type != "cylindricity":
        insuff.append(f"{c.id}: propagation of {gt.type} is not implemented in Phase 1.")
        ctx.need(f"Propagation model for {gt.type} ({gt.id}) — Phase 3.")
        return
    if gt.feature_id not in (hole, shaft):
        fails.append(f"{c.id}: cylindricity {gt.id} controls '{gt.feature_id}', which is not part of this fit.")
        return
    try:
        unit_factor(gt.unit, project.base_unit)
    except UnitError as e:
        fails.append(f"{c.id}: {e}")
        return
    role = "hole" if gt.feature_id == hole else "shaft"
    if gt.size_principle is None:
        insuff.append(f"{c.id}: size principle (envelope Ⓔ / Rule #1, or independency ISO 8015) not declared "
                      f"for {gt.feature_id}; the effect of cylindricity on the fit cannot be decided.")
        ctx.need(f"Size principle (envelope or independency) for feature '{gt.feature_id}'.")
        return
    if gt.size_principle == "envelope":
        fails.append(f"{c.id}: {gt.feature_id} is under the envelope requirement — form deviation is already "
                     "contained within the size limits (maximum material boundary). Adding cylindricity "
                     "double-counts it.")
        return
    # independency: conservative bound on mating size, effect in [0, t] reducing the clearance
    sign = -k
    signs[c.id] = sign
    sign_origin[c.id] = f"cylindricity of {role}, independency principle (conservative bound)"
    geo_terms[c.id] = (0.0, gt.value, gt.unit)
    path_expl.append(f"{c.id}: cylindricity {gt.value:g} {gt.unit} on {role} {gt.feature_id} "
                     f"(independency) ⇒ {sign:+g}·e, e ∈ [0, {gt.value:g}] (conservative bound)")
    ctx.assume(f"{c.id}: conservative bound — form deviation within cylindricity t changes the {role}'s mating "
               f"size by at most t relative to its extreme two-point size (docs/formulation.md §5). "
               "Worst-Case including this term is a bound, not an attained value.")


def _unmodelled_geometric(project: Project, contributors, ctx: _Ctx, ch):
    feats = set()
    for c in contributors:
        for f in (c.from_feature, c.to_feature):
            if f:
                feats.add(f)
    if ch is not None:
        for f in (ch.start_feature, ch.end_feature):
            if f:
                feats.add(f)
    used_geo = {c.geometric_id for c in contributors if c.kind == "geometric"}
    incomplete, undecided, neglected = [], [], []
    for gt in project.geometric_tolerances:
        if gt.feature_id not in feats or gt.id in used_geo:
            continue
        if ch is not None and ch.type in FIT_TYPES and gt.type == "cylindricity":
            if gt.size_principle == "envelope":
                continue  # correctly excluded: form is contained in the size limits
            if gt.size_principle == "independency":
                incomplete.append(f"{gt.id} ({gt.zone_description()}) on {gt.feature_id} is not in the chain; "
                                  "under the independency principle it reduces the mating fit.")
            else:
                undecided.append(f"{gt.id} on {gt.feature_id}: size principle undeclared, so it is unknown "
                                 "whether this cylindricity must enter the fit.")
                ctx.need(f"Size principle (envelope or independency) for feature '{gt.feature_id}'.")
        else:
            neglected.append(f"{gt.id} ({gt.zone_description()}) on {gt.feature_id} is not propagated in "
                             "Phase 1; its effect on the output is neglected.")
    title = "Geometric tolerances on chain features represented"
    if incomplete:
        ctx.add("MISSING", title, "functional", "failed", "invalid", incomplete + undecided + neglected,
                "Add the missing geometric contributor to the chain.")
    elif undecided:
        ctx.add("MISSING", title, "functional", "failed", "insufficient", undecided + neglected,
                "Declare the size principle of the feature (drawing indication or default standard).")
    elif neglected:
        ctx.add("MISSING", title, "functional", "warning", "warning", neglected,
                "Assess each neglected effect; a 2D/3D model is needed to propagate it (Phase 3+).")
    else:
        ctx.add("MISSING", title, "functional", "passed")
    for n in neglected:
        ctx.assume("Neglected: " + n)
