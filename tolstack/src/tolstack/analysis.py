"""Orchestrates validation and the three analysis methods, with full traceability."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

from . import __version__
from .engines.monte_carlo import MonteCarloResult, monte_carlo
from .engines.rss import RSSResult, rss
from .engines.sensitivity import SensitivityRow, sensitivity_table
from .engines.worst_case import WorstCaseResult, worst_case
from .errors import AnalysisBlocked
from .model.project import Project
from .model.tolerance import ToleranceSpec
from .units import factor as unit_factor
from .validation.chain_checks import ChainDiagnosis, diagnose


@dataclass
class AnalysisResult:
    meta: dict
    diagnosis: ChainDiagnosis
    worst_case: Optional[WorstCaseResult]
    rss: Optional[RSSResult]
    monte_carlo: Optional[MonteCarloResult]
    sensitivity: list[SensitivityRow]
    skipped: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    conclusions: list[str] = field(default_factory=list)
    lsl: Optional[float] = None
    usl: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "meta": self.meta, "diagnosis": self.diagnosis.as_dict(),
            "terms": [t.__dict__ | {"distribution": t.distribution.describe() if t.distribution else None}
                      for t in self.diagnosis.terms],
            "worst_case": self.worst_case.as_dict() if self.worst_case else None,
            "rss": self.rss.as_dict() if self.rss else None,
            "monte_carlo": self.monte_carlo.as_dict() if self.monte_carlo else None,
            "sensitivity": [r.as_dict() for r in self.sensitivity],
            "skipped": self.skipped, "warnings": self.warnings, "conclusions": self.conclusions,
            "lsl": self.lsl, "usl": self.usl,
        }


def run_analysis(project: Project, chain_id: Optional[str] = None,
                 methods: tuple[str, ...] = ("wc", "rss", "mc"),
                 mc_samples: Optional[int] = None, seed: Optional[int] = None) -> AnalysisResult:
    chain = project.chain(chain_id)
    diag = diagnose(project, chain)
    if chain.approval.state == "rejected":
        raise AnalysisBlocked(f"Chain '{chain.id}' was rejected by {chain.approval.reviewer or 'the reviewer'}; "
                              "its diagnostics are retained but it cannot be analysed.")
    if not diag.analysable:
        exc = AnalysisBlocked(f"Chain '{chain.id}' status is '{diag.status}'. Resolve: "
                              + " | ".join(diag.problems[:5]))
        exc.diagnosis = diag
        raise exc

    ch = project.characteristic
    base = project.base_unit
    f = unit_factor(ch.unit, base)
    lsl = ch.lsl * f if ch.lsl is not None else None
    usl = ch.usl * f if ch.usl is not None else None
    st = project.settings
    n = mc_samples or st.mc_samples
    sd = st.seed if seed is None else seed

    warnings = []
    if chain.approval.state != "approved":
        warnings.append("The stack-up path has not been approved by an engineer; results are provisional.")
    terms = diag.terms
    wc = worst_case(terms, lsl, usl) if "wc" in methods else None
    skipped = {}
    r = mc = None
    if not diag.statistical_ready:
        for m in ("rss", "mc"):
            if m in methods:
                skipped[m] = "Insufficient information: " + diag.statistical_reason
    else:
        if "rss" in methods:
            r = rss(terms, diag.correlation, st.rss_k, lsl, usl)
        if "mc" in methods:
            mc = monte_carlo(terms, diag.correlation, n, sd, lsl, usl, st.percentiles, st.confidence)
    sens = sensitivity_table(terms, diag.correlation, statistical=diag.statistical_ready)

    meta = {
        "project_id": project.project_id, "project_name": project.name, "revision": project.revision,
        "fingerprint": project.fingerprint(), "chain_id": chain.id, "chain_name": chain.name,
        "approval": chain.approval.model_dump(), "unit": base,
        "characteristic": ch.model_dump(), "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "software": f"tolstack {__version__}", "mc_samples": n if mc else None, "seed": sd if mc else None,
        "statistical_assumption": project.statistical_assumption.describe(),
    }
    res = AnalysisResult(meta, diag, wc, r, mc, sens, skipped, warnings, [], lsl, usl)
    res.conclusions = _conclusions(res, base)
    return res


def _pct(p):
    return "n/a" if p is None else f"{p * 100:.4g} %" if p >= 1e-4 else f"{p * 1e6:.3g} ppm"


def _conclusions(res: AnalysisResult, unit: str) -> list[str]:
    out = []
    lsl, usl = res.lsl, res.usl
    if res.worst_case:
        w = res.worst_case
        verdict = []
        if w.meets_lsl is not None:
            verdict.append("min ≥ LSL" if w.meets_lsl else f"min below LSL by {lsl - w.minimum:.4g} {unit}")
        if w.meets_usl is not None:
            verdict.append("max ≤ USL" if w.meets_usl else f"max above USL by {w.maximum - usl:.4g} {unit}")
        out.append(f"Worst-Case: y ∈ [{w.minimum:.4f}, {w.maximum:.4f}] {unit} "
                   f"({'exact' if w.exact else 'conservative bound'}); " + (", ".join(verdict) or "no limits"))
    if res.rss:
        r = res.rss
        out.append(f"RSS: mean {r.mean:.4f}, σ {r.sigma:.4g} {unit}; ±{r.k:g}σ range [{r.lower_k:.4f}, "
                   f"{r.upper_k:.4f}]; estimated nonconformity {_pct(r.p_total)}"
                   + ("" if r.output_normal_exact else " (normal approximation)"))
    if res.monte_carlo:
        m = res.monte_carlo
        ci = m.ci_total
        out.append(f"Monte Carlo (n={m.n}, seed={m.seed}): mean {m.mean:.4f}, σ {m.std:.4g} {unit}; "
                   f"nonconformity {_pct(m.p_total)}"
                   + (f", {m.confidence * 100:.0f}% CI [{_pct(ci[0])}, {_pct(ci[1])}]" if ci else ""))
    for k, v in res.skipped.items():
        out.append(f"{k.upper()} not computed — {v}")
    out.append(f"Path status: {res.diagnosis.status}. These results verify the calculation under the listed "
               "assumptions; they are not an engineering approval of the design.")
    return out


def what_if(project: Project, contributor_id: str, *, upper: Optional[float] = None, lower: Optional[float] = None,
            distribution=None, chain_id: Optional[str] = None, mc_samples: Optional[int] = None) -> dict:
    """Re-run the analysis with one contributor changed; returns baseline vs modified key figures."""
    base = run_analysis(project, chain_id, mc_samples=mc_samples)
    mod = project.model_copy(deep=True)
    c = mod.contributor(contributor_id)
    if upper is not None or lower is not None:
        t = c.tolerance
        c.tolerance = ToleranceSpec(nominal=t.nominal, upper=t.upper if upper is None else upper,
                                    lower=t.lower if lower is None else lower, unit=t.unit, origin="declared",
                                    designation="what-if")
    if distribution is not None:
        c.distribution = distribution
    new = run_analysis(mod, chain_id, mc_samples=mc_samples)

    def key(r: AnalysisResult):
        return {
            "wc_min": r.worst_case.minimum if r.worst_case else None,
            "wc_max": r.worst_case.maximum if r.worst_case else None,
            "rss_sigma": r.rss.sigma if r.rss else None,
            "rss_p": r.rss.p_total if r.rss else None,
            "mc_p": r.monte_carlo.p_total if r.monte_carlo else None,
        }
    return {"contributor": contributor_id, "baseline": key(base), "modified": key(new)}
