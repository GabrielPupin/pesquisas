# Verification and validation — Phase 1

Three different claims are kept apart:

| claim | meaning | who/what establishes it |
|---|---|---|
| **Software verification** | the code computes what the formulation says | automated tests (`tests/`) |
| **Mathematical validation** | the formulation is a correct model of the stated problem | analytical cases, independent calculations, documented derivations (`docs/formulation.md`) |
| **Engineering approval** | the model, path, assumptions and data represent the real assembly | the reviewing engineer (approval record on the chain, signature on the report) |

The software never reports engineering approval; the best path status it assigns is *Conditionally Valid*.

## Automated tests (`pytest`)

| area | file | reference |
|---|---|---|
| Worst-Case of axial stacks, governing limits, asymmetric tolerances | `test_engines.py` | hand calculation |
| RSS independent / correlated | `test_engines.py` | closed form sᵀΣs computed by hand |
| Monte Carlo vs analytical normal sum, Irwin–Hall uniform sum, correlated sum, seed reproducibility | `test_engines.py` | exact moments; exact probability inside the Wilson interval |
| Truncated normal / triangular sampling, Φ⁻¹ accuracy | `test_engines.py` | analytic moments, Φ(Φ⁻¹(p)) round trip |
| Sensitivity shares, what-if | `test_engines.py` | Σ shares = 1; WC shift equals tolerance change |
| Incorrect paths: discontinuity, wrong direction (closure), sign conflict, dimension across two parts, missing contact, duplicates | `test_validation.py` | expected status Invalid |
| Incomplete data: missing tolerance, basic dimension, unsupported characteristic types (alignment, angular, position, hole patterns), missing justification | `test_validation.py` | expected status Insufficient Information |
| Conflicting constraints: inconsistent correlation matrix, LSL > USL, angular unit in linear chain | `test_validation.py` | expected Invalid |
| Multiple valid paths diagnosed separately | `test_validation.py` | |
| Radial shaft/housing fit H7/g6 | `test_cylindricity.py` | ISO 286 limits: C ∈ [0.007, 0.041] mm |
| Cylindricity + size: envelope vs independency, double counting, omission, undeclared principle, axial misuse, non-propagated types, one-sided MC moments, interference signs | `test_cylindricity.py` | §5 of the formulation; analytic mean/variance |
| ISO 286 (29 published limit pairs), range boundaries, unsupported classes; ISO 2768-1 | `test_standards.py` | ISO 286-2 tables |
| Callout grammar (16 forms + geometric/special) | `test_drawing.py` | expected parse table |
| PDF extraction vs ground truth (3 drawings), PDF without text, overlay, confirmation-before-use, general-tolerance gating, ambiguous frame confirmation, rejected/angular linking refused | `test_drawing.py` | `examples/drawings/ground_truth.json` |
| JSON round trip and fingerprint, schema guard, duplicate ids, PDF/Excel/CSV export, traceability metadata, CLI exit codes | `test_io_reports.py` | |

Run: `pytest -q` (≈2 s).

## Not covered in Phase 1 (by design)

Hole patterns controlled by position, perpendicularity/angular misalignment, runout, nonlinear geometric
chains and contact/interference solving need the 2D/3D models of Phases 3–4. Phase 1 recognises these
cases and returns *Insufficient Information* instead of an approximate number; tests assert that behaviour.
