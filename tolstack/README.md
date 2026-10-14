# tolstack — Mechanical tolerance stack-up analyzer

Phase 1 of an engineering application for dimensional/geometric tolerance stack-up analysis with path
validation, Worst-Case, RSS and Monte Carlo methods, and traceable reports.

**Phase 1 scope**

- Manual 1D model: components, features, contacts, dimensions (bilateral, unilateral, limits, basic,
  ISO 286 classes, ISO 2768 general tolerances), functional characteristic, stack-up paths.
- Path validation engine with explicit status (Conditionally Valid / Invalid / Insufficient Information —
  *Validated* is never claimed in Phase 1), checks, assumptions, missing information, recommended actions,
  engineer approval/rejection with retained diagnostics.
- Worst-Case (exact for linear chains), RSS with covariance, Monte Carlo (seeded, Gaussian copula,
  Wilson confidence intervals, convergence), sensitivity and contribution ranking, what-if.
- Cylindricity in diametral fits under the envelope or independency principle (conservative bound,
  derivation in `docs/formulation.md` §5).
- Assisted reading of **vector PDF drawings**: dimensions, stacked deviations, ISO fits, basic boxes,
  feature control frames, title block; every value must be confirmed before use; overlay image for
  visual verification.
- Reports: PDF, Excel, CSV, JSON — each with model fingerprint, seed and source traceability.
- Streamlit GUI (10 modules) and CLI.

Not in Phase 1: automatic path generation (Phase 2), 2D/3D geometric models and propagation of other GD&T
(Phase 3), STEP import (Phase 4), OCR of scanned drawings.

## Install

```bash
cd tolstack
pip install -e ".[gui,dev]"
```

## Use

```bash
python examples/build_demo_projects.py      # demo projects (JSON)
python examples/make_demo_drawings.py       # demo PDF drawings + ground truth

tolstack check   examples/axial_clearance_demo.json
tolstack analyze examples/axial_clearance_demo.json --chain A --pdf report.pdf --xlsx report.xlsx
tolstack analyze examples/fit_cylindricity_demo.json --pdf fit.pdf
tolstack extract examples/drawings/TS-100_housing.pdf --overlay overlay.png

streamlit run app/streamlit_app.py
pytest -q
```

## Demonstration models

1. **Axial end play** (`examples/axial_clearance_demo.json`): housing, two bearings and a spacer under
   preload. Chain A is valid; chain B omits the spacer and is kept as a rejected path. Worst-Case
   [0.05, 0.59] mm exceeds USL 0.45 mm; RSS/Monte Carlo estimate ≈0.33 % nonconformity, so the result
   depends on accepting a statistical assumption — which the report states explicitly.
2. **Ø20 H7/g6 with cylindricity 0.005** (`examples/fit_cylindricity_demo.json`): size-only clearance
   [0.007, 0.041] mm; under ISO 8015 independency the minimum mating clearance bound drops to −0.003 mm.

## Architecture

```
src/tolstack/
  model/        data model (pydantic): tolerances, distributions, geometric tolerances, project
  validation/   path checks and term resolution (signs from topology)
  engines/      worst_case, rss, monte_carlo, sensitivity
  standards/    ISO 286, ISO 2768-1
  drawing/      PDF extraction, clustering, callout grammar, title block, review/confirmation, overlay
  io/           JSON persistence
  reporting/    PDF, Excel, CSV
  analysis.py   orchestration and traceability
  cli.py
app/            Streamlit GUI (no calculation logic)
docs/           formulation.md, verification.md
```

The calculation code has no dependency on the GUI; the geometry solver, CAD import and further
statistical engines of later phases plug in behind `validation` (term resolution) and `engines`.
