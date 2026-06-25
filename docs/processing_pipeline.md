# Processing Pipeline

Flowdesk uses this canonical order:

```text
raw events
  -> compensation
  -> derived parameters
  -> transforms
  -> gates
  -> population statistics
  -> export
```

Raw FCS events are immutable. Compensation produces compensated values for selected fluorescence channels. Derived parameters are computed after compensation by default.

Derived parameters must declare a source stage: `raw`, `compensated`, or `transformed`.

The MVP default is `compensated`, using untransformed numeric values. Division by zero should produce `NaN`. `NaN` and infinite values must be handled explicitly during export. Arbitrary Python `eval` is forbidden; expression evaluation must use a safe parser/evaluator.
