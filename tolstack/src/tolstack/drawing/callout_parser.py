"""Deterministic parser for dimension and geometric-tolerance callouts as text.

Recognised forms (decimal point or comma):
  25 ±0.1        25±0,1        Ø20 H7        Ø20 H7/g6        Ø20 g6 Ⓔ        Ø20 H7 (+0.021/0)
  10 +0.05/-0    10 +0.05 -0.02 15 0/-0.12   25.1/24.9 (limits)   [25] (basic)   2x Ø6 ±0.05
  R5 ±0.2        30° ±0.5°      30° ±0°30'   ⌭ 0.005      ⌖ Ø0.1 Ⓜ A B C      CYLINDRICITY 0.005
Anything else is reported as unparsed or unsupported with the reason. Nothing is guessed: an
untoleranced dimension takes the general tolerance only when a general-tolerance note exists, and the
result stays subject to the engineer's confirmation of that note.
"""

from __future__ import annotations

import re
from typing import Optional

from ..errors import UnsupportedFeature
from ..model.geometric import KEYWORDS, SYMBOLS
from ..standards import iso286, iso2768
from .review import ParsedCallout

NUM = r"(?:\d+(?:\.\d+)?|\.\d+)"
SNUM = r"(?:[+-]\s*" + NUM + r"|0(?:\.0+)?)"
CLS = r"(?:JS|js|[A-Za-z])\d{1,2}"

_MAIN = re.compile(
    r"^(?:(?P<count>\d+)\s*[xX×]\s*)?(?P<prefix>SØ|SR|Ø|R|M)?\s*(?P<nom>" + NUM + r")\s*"
    r"(?P<tol>"
    r"±\s*(?P<pm>" + NUM + r")"
    r"|(?P<cls>" + CLS + r")(?:\s*/\s*(?P<cls2>" + CLS + r"))?(?:\s*\(\s*(?P<cup>" + SNUM + r")\s*/\s*(?P<clo>" + SNUM + r")\s*\))?"
    r"|(?P<up>" + SNUM + r")\s*(?:/|\s)\s*(?P<lo>" + SNUM + r")"
    r"|/\s*(?P<lim>" + NUM + r")"
    r")?\s*(?P<env>Ⓔ|ⓔ|\(E\))?$"
)
_BASIC = re.compile(r"^\[\s*(?P<prefix>Ø|R)?\s*(?P<nom>" + NUM + r")\s*\]$")
_ANGLE = re.compile(
    r"^(?P<nom>" + NUM + r")\s*°\s*(?:±\s*(?:(?P<td>" + NUM + r")\s*°)?\s*(?:(?P<tm>\d+)\s*['′])?)?$")
_GEO_VAL = re.compile(
    r"^(?P<dia>Ø)?\s*(?P<val>" + NUM + r")\s*(?P<mod>Ⓜ|Ⓛ|\(M\)|\(L\))?\s*(?P<datums>(?:[|\s]*[A-Z](?:-[A-Z])?)*)\s*\|?\s*$")


def normalize(text: str) -> str:
    t = text.strip()
    for a, b in (("−", "-"), ("–", "-"), ("—", "-"), ("⌀", "Ø"), ("ø", "Ø"), ("Φ", "Ø"), ("φ", "Ø"),
                 ("+/-", "±"), ("+-", "±"), ("º", "°")):
        t = t.replace(a, b)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"([+-])\s+(\d)", r"\1\2", t)
    return t


def _f(x: str) -> float:
    return float(x.replace(" ", ""))


def parse_callout(text: str, unit: Optional[str] = None, general_tolerance: Optional[str] = None,
                  boxed: bool = False):
    """Return (status, ParsedCallout | None, issues, category)."""
    t = normalize(text)
    issues: list[str] = []
    if not t:
        return "unparsed", None, ["empty text"], "note"

    # geometric tolerance -------------------------------------------------------------------
    gtype, rest = None, None
    if t[0] in SYMBOLS:
        gtype, rest = SYMBOLS[t[0]], t[1:].strip(" |")
    else:
        up = t.upper()
        for kw in sorted(KEYWORDS, key=len, reverse=True):
            if up.startswith(kw):
                gtype, rest = KEYWORDS[kw], t[len(kw):].strip(" |:")
                break
    if gtype:
        m = _GEO_VAL.match(rest)
        if not m:
            return "ambiguous", None, [f"geometric tolerance '{gtype}' recognised but value/datums unreadable"], "geometric"
        datums = re.findall(r"[A-Z](?:-[A-Z])?", m.group("datums") or "")
        mod = m.group("mod")
        pc = ParsedCallout(kind="geometric", geometric_type=gtype, geometric_value=_f(m.group("val")),
                           diameter_zone=bool(m.group("dia")), datums=datums, unit=unit,
                           material_modifier={"Ⓜ": "MMC", "(M)": "MMC", "Ⓛ": "LMC", "(L)": "LMC"}.get(mod))
        if unit is None:
            issues.append("drawing unit not declared")
            return "ambiguous", pc, issues, "geometric"
        return "parsed", pc, issues, "geometric"

    # basic dimension --------------------------------------------------------------------------
    m = _BASIC.match(t)
    if m or boxed:
        if not m:
            m = re.match(r"^(?P<prefix>Ø|R)?\s*(?P<nom>" + NUM + r")$", t)
        if m:
            kind = {"Ø": "diameter", "R": "radius"}.get(m.group("prefix") or "", "linear")
            pc = ParsedCallout(kind=kind, nominal=_f(m.group("nom")), upper=0.0, lower=0.0, unit=unit,
                               tolerance_origin="basic", designation="basic", basic=True)
            return ("parsed" if unit else "ambiguous"), pc, ([] if unit else ["drawing unit not declared"]), "dimension"

    # angle -------------------------------------------------------------------------------------
    m = _ANGLE.match(t)
    if m:
        nom = _f(m.group("nom"))
        if m.group("td") is None and m.group("tm") is None:
            if general_tolerance:
                issues.append("angular general tolerance depends on the shorter leg length — enter it manually")
            return "ambiguous", ParsedCallout(kind="angle", nominal=nom, unit="deg", tolerance_origin="none"), \
                issues or ["no tolerance"], "dimension"
        tol = (_f(m.group("td")) if m.group("td") else 0.0) + (int(m.group("tm")) / 60 if m.group("tm") else 0.0)
        pc = ParsedCallout(kind="angle", nominal=nom, upper=tol, lower=-tol, unit="deg",
                           tolerance_origin="bilateral", designation=f"±{tol:g}°")
        return "parsed", pc, ["angular dimension: not usable in a linear 1D chain"], "dimension"

    # linear / diameter / radius ---------------------------------------------------------------
    m = _MAIN.match(t)
    if not m:
        return "unparsed", None, [f"text '{t}' does not match a supported callout form"], \
            ("dimension" if re.match(r"^[\dØR\[]", t) else "note")
    prefix = m.group("prefix")
    if prefix == "M":
        return "unsupported", None, ["thread designation: not modelled in Phase 1"], "dimension"
    if prefix in ("SØ", "SR"):
        return "unsupported", None, ["spherical size: not modelled in Phase 1"], "dimension"
    kind = {"Ø": "diameter", "R": "radius"}.get(prefix or "", "linear")
    nom = _f(m.group("nom"))
    count = int(m.group("count")) if m.group("count") else 1
    pc = ParsedCallout(kind=kind, nominal=nom, count=count, unit=unit, envelope=bool(m.group("env")))
    status = "parsed"
    if m.group("pm") is not None:
        tol = _f(m.group("pm"))
        pc.upper, pc.lower, pc.tolerance_origin, pc.designation = tol, -tol, "bilateral", f"±{tol:g}"
    elif m.group("cls"):
        c1, c2 = m.group("cls"), m.group("cls2")
        pc.designation = c1 + (f"/{c2}" if c2 else "")
        pc.tolerance_origin = "iso286"
        if c2:
            pc.fit = (c1, c2)
            issues.append("fit designation: hole and shaft are separate features — split into two contributors")
            status = "ambiguous"
        if unit != "mm":
            issues.append("ISO 286 classes are defined in mm; drawing unit is "
                          + (unit or "undeclared"))
            status = "ambiguous" if unit is None else "unsupported"
        elif not c2:
            try:
                up, lo = iso286.deviations_mm(c1, nom)
                pc.upper, pc.lower = up, lo
            except UnsupportedFeature as e:
                issues.append(str(e))
                status = "unsupported"
        if m.group("cup") is not None:
            cu, cl = _f(m.group("cup")), _f(m.group("clo"))
            if pc.upper is not None and (abs(cu - pc.upper) > 1e-9 or abs(cl - pc.lower) > 1e-9):
                issues.append(f"deviations written on drawing ({cu:+g}/{cl:+g}) differ from ISO 286 "
                              f"{c1} ({pc.upper:+g}/{pc.lower:+g})")
                status = "ambiguous"
            elif pc.upper is None:
                pc.upper, pc.lower = cu, cl
    elif m.group("up") is not None:
        a, b = _f(m.group("up")), _f(m.group("lo"))
        up, lo = max(a, b) + 0.0, min(a, b) + 0.0
        pc.upper, pc.lower, pc.tolerance_origin = up, lo, "deviations"
        pc.designation = f"{up:+g}/{lo:+g}"
    elif m.group("lim") is not None:
        a, b = nom, _f(m.group("lim"))
        if a == b:
            return "ambiguous", None, ["limit dimension with equal limits"], "dimension"
        hi, lo = max(a, b), min(a, b)
        half = round(0.5 * (hi - lo), 9)
        pc.nominal, pc.upper, pc.lower = round(0.5 * (hi + lo), 9), half, -half
        pc.tolerance_origin, pc.designation = "limits", f"{lo:g}/{hi:g}"
    else:
        if general_tolerance:
            g = re.search(r"2768\s*-?\s*([fmcv])", general_tolerance, re.I)
            if g and kind in ("linear", "diameter") and (unit == "mm"):
                try:
                    tol = iso2768.linear_tolerance_mm(g.group(1), nom)
                    pc.upper, pc.lower = tol, -tol
                    pc.tolerance_origin, pc.designation = "general", f"ISO 2768-{g.group(1).lower()} (±{tol:g})"
                    issues.append("tolerance from the general-tolerance note — valid only if that note is confirmed")
                except UnsupportedFeature as e:
                    issues.append(str(e)); status = "ambiguous"
            else:
                issues.append(f"no individual tolerance; general tolerance '{general_tolerance}' not applicable "
                              "automatically")
                pc.tolerance_origin = "none"; status = "ambiguous"
        else:
            issues.append("no individual tolerance and no general-tolerance note found")
            pc.tolerance_origin = "none"; status = "ambiguous"
    if unit is None:
        issues.append("drawing unit not declared")
        status = "ambiguous" if status == "parsed" else status
    return status, pc, issues, "dimension"
