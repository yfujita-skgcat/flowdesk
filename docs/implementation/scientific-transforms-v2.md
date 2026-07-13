# Scientific Transforms v2

Spec: `S05`
ToDo: `Phase A3`

## Goal

Replace the approximate transform ambiguity with explicit, invertible transform
definitions used consistently by the runner, gates, axes, and serialization.

## Inspect first

- `src/flowdesk_core/transforms.py`
- `src/flowdesk_core/gating_strategy.py`
- `src/flowdesk_core/models.py`
- `src/flowdesk_qt/channel_selector.py`
- `src/flowdesk_qt/plot_widget.py`
- `schemas/project.schema.json`
- `tests/test_transforms.py`
- transform-related tests in `tests/test_gates.py` and `tests/test_qt_plot_widget.py`

Read `transforms.md`, `qt-interactive-plot-controls.md`, `gate-engine.md`, and
`.codex/skills/scientific-review/SKILL.md`.

## Scientific contract

Each transform definition has a stable ID, type, parameter ID, complete numeric
settings, forward function, inverse function, domain policy, and implementation
version. The same definition converts events, gate coordinates, and axis ticks.

Rename existing `logicle_like` through migration to an honest legacy type. Do not
claim FlowJo Biex compatibility without versioned reference fixtures.

## Selected Logicle definition and references

Flowdesk will implement the normalized Gating-ML 2.0 Logicle definition, not a
product-specific “Biexponential” mode. The normative scientific source is Wayne
A. Moore and David R. Parks, “Update for the logicle data scale including
operational code implementations,” *Cytometry Part A* 81A (2012), 273–277,
[doi:10.1002/cyto.a.22030](https://doi.org/10.1002/cyto.a.22030). The original
display rationale is Parks, Roederer, and Moore (2006),
[doi:10.1002/cyto.a.20258](https://doi.org/10.1002/cyto.a.20258).

The interoperability definition is section 6.5 of
[Gating-ML 2.0](https://sourceforge.net/projects/flowcyt/files/Gating-ML/Gating-ML%202.0/GatingML_2.0_Specification.20130122.pdf/download),
whose standard and cross-implementation rationale are described by
[Spidlen et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC4874733/). Numeric
fixtures will be checked independently against the Moore–Parks C++ reference
implementation distributed under the Revised BSD license with the 2012 paper,
also maintained in Bioconductor flowCore as `Logicle.cpp` and `FastLogicle.cpp`.
No optional binary dependency is selected for the core implementation.

### Equation and coordinate convention

The inverse mapping from normalized display coordinate `y` to event value `x`
is the modified biexponential

```text
B(y) = a exp(b y) - c exp(-d y) + f
```

and the forward Logicle transform is the unique root `y` satisfying `B(y)=x`.
For parameters `T`, `W`, `M`, and `A`:

```text
w  = W / (M + A)
x2 = A / (M + A)
x1 = x2 + w
x0 = x2 + 2w
b  = (M + A) ln(10)
```

`d` is the positive solution of
`2(ln(d)-ln(b)) + w(d+b) = 0`. Coefficients `a`, `c`, and `f` use the
Moore–Parks/Gating-ML construction so that `B(1)=T`, `B(x1)=0`, and the
linear-region constraint is satisfied. Increment 3 must transcribe and test
those coefficients against the BSD reference code; it must not rederive or
approximate them independently.

The public convention will be:

- `forward(x)` returns normalized Gating-ML coordinates; `forward(T)=1` and
  `forward(0)=x1`.
- `inverse(y)` returns `B(y)` in original event units.
- The mathematical input domain is every finite real event value. Coordinates
  outside `[0, 1]` are mathematically allowed for values outside the nominal
  display interval and are not clipped implicitly.
- Nonfinite input propagation and solver non-convergence will use explicit
  typed outcomes defined in increment 3; they will never be converted to zero.

### Parameter validity and persistence

- `T > 0` and finite: nominal top-of-scale event value.
- `M > 0` and finite: asymptotic positive logarithmic range in decades.
- `0 <= W <= M/2` and finite: width of the approximately linear region.
- `-W <= A <= M - 2W` and finite: additional negative range in decades.
- All four values and an implementation identifier
  `logicle-gml2-moore-parks-2012-v1` must be persisted. Defaults may be offered
  by a UI, but the runner must never estimate them again from current events.

### Reference tolerance

Reference vectors will include negative values, zero, both sides of the linear
region, the transition region, `T`, and values outside the nominal range. For
finite `float64` inputs the acceptance limits are:

- reference forward coordinates: absolute error `<= 1e-12`;
- `inverse(forward(x))`: `rtol <= 1e-12` and
  `atol <= max(1, abs(T)) * 1e-12`;
- exact anchors `forward(0)=x1` and `forward(T)=1` are tested with absolute
  tolerance `8 * numpy.finfo(float64).eps`.

If the independent BSD implementation cannot meet these limits on the same
fixture and platform, the tolerance must be justified from measured error and
recorded before relaxing it. Gate-membership tests additionally place events
on both sides of every boundary so tolerance cannot silently change a count.

### Tick generation

Ticks are defined in event-value space and mapped with the same transform
object used for events and gates. Major candidates are zero plus positive and
negative signed powers of ten within the visible inverse-mapped interval;
duplicate or nonfinite coordinates are removed. `T` may be added as an endpoint
tick when it is not already a decade. Tick generation must not use an
independent approximation or infer different `T/W/M/A` values.

### FlowJo compatibility statement

Flowdesk’s future type will be named `logicle`, meaning the published
Moore–Parks/Gating-ML transform. It will not be named `biex`, `FlowJo Biex`, or
described as numerically equivalent to FlowJo. FlowJo’s product-specific
parameter selection and rendering have not been verified with licensed,
versioned reference fixtures. The current `logicle_like` implementation is an
unrelated legacy approximation and must never be relabeled as formal Logicle.

## Increments

1. **Transform protocol**
   - Introduce typed forward/inverse dispatch and settings validation.
   - Keep linear/log/asinh results backward compatible.
2. **Legacy migration**
   - Map `logicle_like` to `legacy_logicle_approximation` without changing values.
   - Display a warning but preserve old project membership.
3. **Published Logicle**
   - Select and document a primary equation/reference implementation.
   - Implement `T`, `W`, `M`, `A`, convergence limits, and inverse.
   - Add reference vectors before connecting gates or GUI.
4. **Single-application model**
   - Gate axes reference transform IDs rather than applying an independent second scale.
   - Separate analysis transforms from display-only view settings.
   - Detect and reject accidental double application.
5. **GUI and migration UX**
   - Add parameter editor and preview.
   - Keep mismatched gate overlays hidden; offer explicit duplicate/migrate with preview.

## Required tests

- Published/reference forward values and inverse round trips.
- Negative, zero, near-linear, transition, and high-positive regions.
- Invalid parameters and non-convergence return typed errors.
- Legacy projects retain previous gate membership.
- Logicle-drawn rectangle/polygon has identical GUI/headless membership.
- Project transform plus gate reference is applied exactly once.

## Confirmed contract after increment 1

- `TransformImplementation` defines one typed validation, forward, and inverse
  protocol. `apply_transform()` remains the compatibility forward adapter;
  `inverse_transform()` and `validate_transform()` are GUI-independent core APIs.
- Linear, log, and asinh retain their previous forward equations. Their inverse
  equations are `(y-offset)/scale`, `base**y`, and
  `sinh(y/cofactor)*cofactor`, respectively.
- Complete normalized settings are built without mutating persisted settings.
  Zero linear scale and nonfinite numeric settings fail with stable code
  `invalid_transform_settings` because an invertible definition cannot represent
  them.
- Log invalid-value policies still control forward values outside the positive
  domain. The inverse is the coordinate inverse on the valid logarithmic range;
  policies such as `to_zero` are intentionally not claimed to be bijective for
  invalid original values.
- The legacy approximation forward path is unchanged. Its inverse raises
  `transform_inverse_unavailable`; inventing an inverse would falsely imply a
  scientific transform contract.

## Confirmed contract after increment 2

- Project format `1.3.0` renames persisted `logicle_like` definitions to
  `legacy_logicle_approximation`. The migration deep-copies the manifest and
  preserves transform ID, parameter ID, settings, notes, and unknown fields.
- The renamed type is backed by the exact previous numeric function. A
  headless fixture fixes the resulting gate-membership mask so a future formal
  Logicle implementation cannot silently change legacy populations.
- Migration records warning `legacy_logicle_approximation` with the transform
  ID, old/new type names, and `numeric_behavior_preserved=true`. Reloading the
  current project is idempotent and does not duplicate the warning.
- Current manifests reject the ambiguous `logicle_like` name. Formal `logicle`
  remains unavailable until increment 3 supplies independent reference vectors;
  migration never converts a legacy approximation into formal Logicle.
- Linear, log, and asinh names, settings, implementations, and persistence are
  unchanged by this migration.

## Confirmed contract after increment 3

- Core type `logicle` implements the normalized Moore–Parks/Gating-ML forward
  and inverse mapping with required persisted `T`, `W`, `M`, `A`, and
  implementation version `logicle-gml2-moore-parks-2012-v1`.
- Coefficient construction, the 16-term near-zero Taylor expansion, and the
  bounded 20-iteration Halley solver follow the Revised BSD `Logicle.cpp` in
  Bioconductor flowCore commit
  `4935c7bf318697b3128ee50dae81018a6b246ab8`. Two independently generated
  reference vectors cover `A=0` and `A=1`.
- Every finite event value is accepted and may map outside normalized display
  interval `[0, 1]`. Nonfinite input and numeric inverse overflow report stable
  `transform_domain_error`; failure to converge reports
  `transform_non_convergence`. No value is silently clipped or replaced.
- Project format `1.4.0` persists and validates all formal Logicle parameters
  and the implementation identifier. Version `1.3.0` migrates without changing
  existing transform definitions. Formal Logicle uses the same headless
  transform protocol as linear, log, and asinh; gate IDs and Qt display/ticks
  remain increment 4 and 5 work.

## Confirmed contract after increment 4

- `GateSpec.x_transform_id` and `GateSpec.y_transform_id` identify the exact
  versioned analysis coordinate definition for each geometric axis. The old
  single `transform_id` and `x_scale`/`y_scale` fields remain read-compatible;
  combining a transform ID with a non-linear legacy scale is rejected as a
  double transform.
- The pipeline transform stage validates definitions and binds one default
  analysis transform per parameter without mutating event columns. Gate
  evaluation lazily applies the referenced transform to the immutable
  compensated/derived view and caches it by transform ID. Thus project and
  gate references select one transform application instead of composing two.
- `TransformSpec.role="analysis"` is persisted separately from
  `plot_display_settings`. Display-only linear/log10/asinh choices are not
  accepted as gate analysis transform IDs.
- Core tick generation inverse-maps the visible coordinate interval, selects
  zero and signed event-space decades (plus Logicle `T`), then forward-maps
  candidates through the same `TransformSpec`. `PlotWidget` uses that API for
  formal transform coordinates, ticks, and matching gate overlays.
- Project format `1.5.0` adds transform roles and per-axis gate transform IDs.
  Migration binds an old linear gate axis to its unique matching project
  transform. A legacy project transform combined with an additional non-linear
  gate scale records `legacy_double_transform` and is rejected rather than
  silently changing membership.
- Synthetic rectangle and polygon fixtures verify that PlotWidget coordinates
  and GUI-visible overlays produce the same full-event headless membership.
  Existing linear, log, asinh, and legacy scale gate tests remain unchanged.
  Transform parameter editing and explicit legacy gate duplication/migration
  preview remain increment 5 work.

## Stop condition

If no licensed/reference implementation or equation can be verified, stop after the
legacy rename and leave a failing/xfail reference test with an explanation. Do not
invent a Logicle formula.

## Final verification

```bash
pytest -q tests/test_transforms.py tests/test_gates.py tests/test_qt_plot_widget.py
ruff check src tests
mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```
