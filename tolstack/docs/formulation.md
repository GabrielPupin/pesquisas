# Engineering formulation — Phase 1

This document states, for every implemented feature, the mathematical formulation, the required inputs,
the limitations and the validation strategy. Code references are to `src/tolstack/`.

## 1. One-dimensional model

### 1.1 Loop characteristics (`axial_clearance`, `axial_gap`, `axial_stack_height`)

The output is the signed distance between two boundary features along a declared axis:

    y = pos(end_feature) − pos(start_feature)

Each `dimension` contributor is a vector from `from_feature` to `to_feature` with `direction = +1` if
`to_feature` lies on the +axis side. The path is walked from the start boundary; a contributor entered at its
`from_feature` is traversed forward (sign `+direction`), one entered at its `to_feature` is traversed in
reverse (sign `−direction`). Assembly interfaces are zero-length `contacts` between features of different
components. The sign of every term is therefore **derived from topology**, never typed in (a declared
sensitivity is only cross-checked).

    y = Σ sᵢ·xᵢ ,   xᵢ = nomᵢ + δᵢ ,   δᵢ ∈ [lowerᵢ, upperᵢ]

Inputs: features, contacts (with the reason contact is maintained), dimensions with direction, start/end
boundaries. Limitation: all features are treated as planes perpendicular to the axis (no tilt, no form or
orientation deviation of contact faces).

### 1.2 Fit characteristics (`diametral_clearance`, `diametral_interference`)

For one hole–shaft pair (start_feature = hole, end_feature = shaft):

    C = D_hole,mating − d_shaft,mating        (interference I = −C)

`size` contributors of the hole enter with +1, those of the shaft with −1 (signs flip for interference).
Limitation: coaxiality/offset between hole and shaft is not represented (radial clearance at a location,
alignment and tilt need the 2D model of Phase 3).

### 1.3 User-defined scalar

The engineer declares each sensitivity. Topology is not checked and the status records that the equation is
user-declared.

## 2. Worst-Case (`engines/worst_case.py`)

For a linear function on a box the extrema are attained at vertices:

    y_max = Σ sᵢ·nomᵢ + Σ max(sᵢ·upperᵢ, sᵢ·lowerᵢ)
    y_min = Σ sᵢ·nomᵢ + Σ min(sᵢ·upperᵢ, sᵢ·lowerᵢ)

The governing limit of each contributor is reported. The result is labelled **exact** for purely
dimensional chains, and **conservative bound** when a term is itself a bound (cylindricity, §5).

## 3. RSS / first-order statistical propagation (`engines/rss.py`)

    mean_y = Σ sᵢ·(nomᵢ + μᵢ)
    σ_y²   = sᵀ Σ s ,   Σ = D R D ,   D = diag(σᵢ)

μᵢ is the mean deviation, so asymmetric tolerances and process offsets shift the mean. For independent
contributors this is `σ_y = sqrt(Σ (sᵢσᵢ)²)`. Mean and variance are exact for a linear chain; the
nonconformity probability uses a normal approximation of y and is flagged when any input is not normal.

**σᵢ is never inferred from a tolerance.** It comes from (a) a distribution declared per contributor
(process data), or (b) a project-level `StatisticalAssumption` explicitly selected by the engineer
(`normal_k_sigma` with a chosen k, or `uniform_over_tolerance`). Option (b) is printed as an assumption in
every result. Without either, RSS and Monte Carlo are reported as *not computed — insufficient information*;
Worst-Case is unaffected. Geometric effects never receive option (b).

## 4. Monte Carlo (`engines/monte_carlo.py`)

    z ~ N(0, R)  (z = L·u, L Lᵀ = R; eigen-factor if R is singular)
    δᵢ = Fᵢ⁻¹(Φ(zᵢ))      (Gaussian copula)
    y  = Σ sᵢ·(nomᵢ + δᵢ)

- For normal marginals the Pearson correlation equals R; for other marginals R is the correlation of the
  normal scores. The achieved correlation is reported.
- Reported: mean, standard deviation, median, percentiles (0.135 … 99.865 %), histogram, P(y<LSL),
  P(y>USL), Wilson score intervals, standard error of the mean and running estimates at doubling sample
  sizes (convergence). Sample min/max are labelled *observed*, never worst-case.
- Non-finite samples are counted and diagnosed, not discarded silently.
- Reproducibility: `numpy.random.default_rng(seed)`; the seed and sample size are in every result.
- Φ⁻¹ uses Acklam's rational approximation with one Halley step (|error| < 1e-9, verified in tests).

## 5. Cylindricity in a diametral fit (`validation/chain_checks.py::_cylindricity_term`)

Cylindricity t: the surface lies between two coaxial cylinders whose radii differ by t. It has no datum and
does not control location or orientation.

**Envelope requirement** (ISO Ⓔ / ISO 14405-1, ASME Y14.5 Rule #1): the feature may not violate the
maximum-material boundary; form deviation is already inside the size limits. Adding cylindricity is double
counting → the path is **Invalid** if the term is included, and the term is correctly omitted otherwise.

**Independency principle** (ISO 8015, default in ISO GPS): size is a two-point local size; form is independent.
Derivation of the bound used for a shaft (hole by symmetry):

1. Let R_o be the outer radius of the minimum zone; some surface point P lies at R_o.
2. The two-point size through P along a diameter of the zone axis is r(P) + r(P′) ≥ R_o + (R_o − t)
   = 2R_o − t, because every point lies at radius ≥ R_o − t.
3. The mating (smallest circumscribed) cylinder is not larger than the outer zone cylinder:
   D_mating ≤ 2R_o ≤ d_two-point,max + t.

So the mating size exceeds the largest two-point size by at most t; for a hole the mating (largest inscribed)
size is below the smallest two-point size by at most t. In the fit equation each cylindricity becomes a
one-sided term e ∈ [0, t] with sensitivity −1 on clearance. The bound is attained by a bent shaft (axis bow
f = t, constant local size) and approached by odd lobing; it is **conservative** for other shapes, so the
Worst-Case result is labelled a bound. Assumptions printed with every result: (i) the two-point size along a
zone diameter is a valid local size inside the size tolerance; (ii) hole and shaft axes are coaxial (no
offset). For statistical methods the distribution of e must be declared (e.g. uniform on [0, t] as an
engineering assumption, or measured form data); it is never inferred.

Size principle undeclared → **Insufficient Information**. Cylindricity in a loop (axial) characteristic →
**Invalid** (it does not change a distance along the axis in the 1D model). A cylindricity on a fit feature
under independency that is missing from the chain → **Invalid** (incomplete chain).

## 6. Path validation (`validation/chain_checks.py`)

| check | category | failure ⇒ |
|---|---|---|
| CHAR characteristic consistent and supported | functional | Invalid / Insufficient (unsupported type) |
| LIMITS acceptance limits defined | functional | warning (conformity not evaluable) |
| REF contributors exist | data | Invalid |
| DUP no duplicated contributions (same id, same feature pair, same geometric tolerance) | mathematical | Invalid |
| UNIT units valid/convertible; no angular unit in a linear chain | mathematical | Invalid |
| TOL nominal and deviations present | data | Insufficient |
| BASIC basic dimension in chain (variation set by an unpropagated geometric tolerance) | geometric | Insufficient |
| EQUIV user-declared equivalent justified | functional | Insufficient |
| KIND contributor kinds compatible with the characteristic | geometric | Invalid |
| TOPO path continuity start→end, one-component dimensions, contacts, declared vs derived signs; fit completeness | topological | Invalid / Insufficient |
| CONTACT contacts join different components and are justified | functional | warning |
| MISSING geometric tolerances on chain features represented or explicitly neglected | functional | Invalid / Insufficient / warning |
| CLOSURE Σ s·nominal equals the declared nominal | mathematical | Invalid |
| STAT distributions available | data | warning (RSS/MC unavailable) |
| CORR correlation matrix symmetric, |ρ| ≤ 1, positive semi-definite | mathematical | Invalid |
| DIM adequacy of the 1D representation | geometric | warning (assumption) |

Status: any Invalid → **Invalid**; else any Insufficient → **Insufficient Information**; else **Conditionally
Valid** with the listed assumptions. **Validated is never assigned in Phase 1** because the software cannot
verify the physical behaviour of the assembly (contact maintenance, part tilt, unpropagated geometric
effects). Invalid and Insufficient paths cannot be analysed; rejected paths cannot be analysed but keep their
diagnostics.

## 7. Sensitivity (`engines/sensitivity.py`)

- physical sensitivity sᵢ = ∂y/∂xᵢ;
- worst-case share |sᵢ|Tᵢ / Σ|sⱼ|Tⱼ;
- variance share sᵢ(Σs)ᵢ / σ_y² (sums to 1; may be negative with negative correlation);
- effect of each contributor on y_min and y_max;
- what-if: re-analysis with one tolerance or distribution changed.

## 8. Standards tables

- ISO 286-1/-2 (`standards/iso286.py`): IT1–IT18 and fundamental deviations d e f g h js k m n p r s /
  D E F G H JS K M N P R S up to 500 mm, Δ rule for K–S holes. Anything else raises `UnsupportedFeature`.
- ISO 2768-1 (`standards/iso2768.py`): linear and angular general tolerances f/m/c/v.

## 9. Drawing-assisted input (`drawing/`)

Text and rectangles of vector PDFs are read with pdfplumber, grouped geometrically (baseline runs, stacked
deviations to the right of a nominal, boxes = basic dimensions, adjacent cells = feature control frames),
and parsed by a deterministic grammar (`callout_parser.py`). Every callout gets a status
(parsed/ambiguous/unparsed/unsupported) and issues. Nothing is used before a reviewer confirms it; an
untoleranced dimension takes ISO 2768 only if the general-tolerance note is confirmed; a frame whose symbol
is drawn as graphics is *ambiguous* until the reviewer selects the type. Limitations: no OCR; layouts of
other CAD systems may group text differently (the overlay image is the verification tool); stacked limit
dimensions (two unsigned numbers) are not merged.
