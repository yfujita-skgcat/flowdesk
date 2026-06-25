# Architecture

Flowdesk separates scientific logic from presentation.

```text
flowdesk_qt
  -> flowdesk_core
  -> flowdesk_storage

flowdesk_cli
  -> flowdesk_core
  -> flowdesk_storage
```

`flowdesk_core` must not import `flowdesk_qt`, PySide6, or Qt. Core owns models, compensation, derived parameters, transforms, gates, population statistics, export records, and the pipeline runner.

`flowdesk_storage` owns project bundle loading, manifests, cache metadata, and serialization.

`flowdesk_cli` provides command-line access to the same pipeline used by the GUI.

`flowdesk_qt` owns widgets and user interaction. It may update project state and call the core pipeline runner, but it must not implement scientific execution logic.
