# Headless Execution

Flowdesk projects created in the GUI must be executable without the GUI.

Headless execution supports batch processing, server runs, cron jobs, and future integration with Snakemake, Nextflow, or HPC environments.

The same `.flowdesk` bundle should drive GUI, CLI, and Python API execution. Population counts shown in the GUI must match CLI/headless results.

GUI display downsampling must never be used for analytical results. Gates are evaluated against full event data in data coordinates or transformed data coordinates.
