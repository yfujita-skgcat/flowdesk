# MVP Specification

The first MVP focuses on reproducible analysis objects, not a complete GUI.

## In Scope

- Reference FCS files by path.
- Represent FCS metadata and channel/parameter lists.
- Represent spillover and user-defined compensation matrices.
- Represent derived parameters such as `FL1-A / FL2-A`.
- Represent linear, log, asinh, and logicle-like transform definitions.
- Represent x/y parameter selection for 2D plots.
- Represent rectangle, polygon, range, and boolean gates.
- Represent hierarchical population trees.
- Apply the same gating strategy to sample groups.
- Export population count, frequency of parent, and frequency of total.
- Run saved projects through GUI-independent CLI/Python/headless execution.

## Out of Scope

- Full FlowJo compatibility.
- Full GatingML compatibility.
- Complete FCS parser implementation.
- Complete Qt GUI implementation.
- Production-scale rendering.
