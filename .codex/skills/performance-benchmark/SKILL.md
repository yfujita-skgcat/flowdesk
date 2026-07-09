---
name: performance-benchmark
description: Guidance for benchmarking and reviewing Flowdesk high-volume event rendering and processing performance while preserving analytical correctness. Use when changing scatter rendering, display downsampling, density rendering, cache invalidation, memory use, runtime, or performance-sensitive event processing.
---

# Performance Benchmark Skill

Use this skill when changing high-volume event rendering or processing performance.

- Avoid relying on all-point scatter rendering for large event sets.
- Prefer downsampling for display or density rendering with Datashader-like approaches.
- Keep display downsampling separate from analytical gate membership.
- Benchmark memory use, runtime, and result consistency.
- Document cache invalidation and reproducibility implications.
