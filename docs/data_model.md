# Data Model

`SampleSpec` references an FCS path and metadata. `ChannelSpec` describes FCS channels or derived parameters usable for plotting, gating, and export.

`CompensationMatrixSpec` stores an id, name, source, channels, matrix values, creation metadata, and notes. Raw events are immutable; compensated values are derived views or cache outputs.

`DerivedParameterSpec` stores an id, name, expression, source stage, input parameters, output label, invalid value policy, and notes. Derived parameters should behave like regular channels after computation.

`TransformSpec` stores a transform id, type, parameter, and parameters for linear, log, asinh, or logicle-like transforms.

`GateSpec` is an analysis object in data coordinates or transformed data coordinates. It is not a screen-pixel shape. `GatingStrategySpec` stores a collection of gates and a population hierarchy.

`PopulationResult` stores event count, frequency of parent, and frequency of total for a population.
