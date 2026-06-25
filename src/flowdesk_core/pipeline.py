"""Pipeline definitions for GUI-independent analysis execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PipelineStep:
  """One named step in the canonical Flowdesk processing order."""

  name: str
  description: str


CANONICAL_PIPELINE: tuple[PipelineStep, ...] = (
  PipelineStep("load_raw_events", "Load immutable raw FCS events."),
  PipelineStep("compensation", "Apply compensation matrix as a derived view."),
  PipelineStep("derived_parameters", "Compute safe derived parameter expressions."),
  PipelineStep("transforms", "Apply plot and gate transforms."),
  PipelineStep("gates", "Evaluate gate membership on full event data."),
  PipelineStep("population_statistics", "Compute counts and frequencies."),
  PipelineStep("export", "Write configured CSV or TSV outputs."),
)


@dataclass(frozen=True)
class PipelineDefinition:
  """Serializable description of the analysis pipeline."""

  version: str = "0.1"
  steps: tuple[PipelineStep, ...] = field(default_factory=lambda: CANONICAL_PIPELINE)
