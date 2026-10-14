"""Command-line interface.

  tolstack check   project.json [--chain ID]
  tolstack analyze project.json [--chain ID] [--pdf out.pdf] [--xlsx out.xlsx] [--csv DIR] [--n N] [--seed S]
  tolstack extract drawing.pdf  [--json out.json] [--overlay out.png]
"""

from __future__ import annotations

import argparse
import json
import sys

from .errors import AnalysisBlocked, TolstackError


def _print_diag(d):
    print(f"Chain {d.chain_id}: {d.status}")
    print(f"  {d.equation}")
    for c in d.checks:
        mark = {"passed": "✓", "failed": "✗", "warning": "!", "not_evaluable": "·"}[c.outcome]
        print(f"  {mark} [{c.id}] {c.title}" + (f" — {'; '.join(c.details)}" if c.details and c.outcome != "passed" else ""))
    if d.missing_information:
        print("  Missing information:")
        for m in d.missing_information:
            print("   -", m)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tolstack", description="Tolerance stack-up analyzer (Phase 1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("check"); a.add_argument("project"); a.add_argument("--chain")
    b = sub.add_parser("analyze"); b.add_argument("project"); b.add_argument("--chain")
    b.add_argument("--pdf"); b.add_argument("--xlsx"); b.add_argument("--csv")
    b.add_argument("--n", type=int); b.add_argument("--seed", type=int); b.add_argument("--json")
    c = sub.add_parser("extract"); c.add_argument("drawing"); c.add_argument("--json"); c.add_argument("--overlay")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            from .io.project_json import load_project
            from .validation.chain_checks import diagnose
            p = load_project(args.project)
            chains = [p.chain(args.chain)] if args.chain else p.chains
            for ch in chains:
                _print_diag(diagnose(p, ch))
            return 0
        if args.cmd == "analyze":
            from .analysis import run_analysis
            from .io.project_json import load_project
            p = load_project(args.project)
            try:
                res = run_analysis(p, args.chain, mc_samples=args.n, seed=args.seed)
            except AnalysisBlocked as e:
                print("ANALYSIS BLOCKED:", e, file=sys.stderr)
                if getattr(e, "diagnosis", None):
                    _print_diag(e.diagnosis)
                return 2
            _print_diag(res.diagnosis)
            for w in res.warnings:
                print("WARNING:", w)
            print()
            for line in res.conclusions:
                print(line)
            print("\nSensitivity ranking:")
            for r in res.sensitivity:
                vs = f"{r.variance_share * 100:6.1f} %" if r.variance_share is not None else "   n/a"
                print(f"  {r.rank}. {r.contributor_id:12s} s={r.sensitivity:+g}  WC share {r.wc_share * 100:5.1f} %  "
                      f"variance share {vs}")
            if args.pdf:
                from .reporting.pdf import export_pdf
                print("PDF:", export_pdf(p, res, args.pdf))
            if args.xlsx:
                from .reporting.tabular import export_excel
                print("Excel:", export_excel(p, res, args.xlsx))
            if args.csv:
                from .reporting.tabular import export_csv
                print("CSV:", ", ".join(str(x) for x in export_csv(p, res, args.csv)))
            if args.json:
                with open(args.json, "w", encoding="utf-8") as fh:
                    json.dump(res.as_dict(), fh, indent=2, default=str, ensure_ascii=False)
            return 0
        if args.cmd == "extract":
            from .drawing.pdf_extract import extract_drawing
            rec = extract_drawing(args.drawing)
            for m in rec.messages:
                print("NOTE:", m)
            for t in rec.title_block:
                print(f"  title  {t.field:18s} {t.value:14s} ← '{t.raw_text}'")
            for co in rec.callouts:
                pc = co.parsed
                val = ""
                if pc is not None and pc.kind != "geometric":
                    val = f"{pc.kind} {pc.nominal} [{pc.lower}, {pc.upper}] {pc.unit or '?'} ({pc.tolerance_origin})"
                elif pc is not None:
                    val = f"{pc.geometric_type or '?type'} {pc.geometric_value} {' '.join(pc.datums)}"
                print(f"  {co.id:22s} {co.status:11s} '{co.raw_text}' → {val}" + (f"  !! {'; '.join(co.issues)}" if co.issues else ""))
            if args.json:
                with open(args.json, "w", encoding="utf-8") as fh:
                    fh.write(rec.model_dump_json(indent=2))
            if args.overlay:
                from .drawing.render import render_overlay
                render_overlay(args.drawing, rec).save(args.overlay)
                print("overlay:", args.overlay)
            return 0
    except TolstackError as e:
        print(f"ERROR ({type(e).__name__}): {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
