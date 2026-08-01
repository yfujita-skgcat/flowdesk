# Cross-platform Runtime and Packaging Hardening

## Purpose

Flowdesk is developed and manually exercised primarily on Linux, while the
Windows and macOS packages are currently checked mainly by native CI build and
shallow smoke tests. This guide defines the work required to make Windows and
macOS support evidence-based rather than inferred from Linux success.

The work covers rendering, filesystem paths, persistence, Qt lifecycle,
parallel execution, locale, packaging resources, and release validation. It
must not change scientific formulas or silently accept OS-dependent scientific
results.

Implement exactly one numbered increment per LLM run. Begin each increment by
reporting its purpose, expected files, and acceptance criteria. Finish it with
tests, limitations, the next small task, user-manual updates for user-visible
changes, and the required commit-message format.

## Required reading

Read completely before production edits:

1. `AGENTS.md`
2. `docs/implementation/llm-task-protocol.md`
3. this guide
4. `docs/implementation/packaging-and-release.md`
5. `docs/implementation/qt-gui-debugging.md` for Qt work
6. `docs/implementation/project-storage.md` for path/storage work
7. `docs/implementation/windows-gui-export-font-parity.md` for font work
8. `docs/implementation/parallel-execution-and-progress.md` for worker work
9. `.codex/skills/qt-plot-widget/SKILL.md` for Qt/rendering work
10. `.codex/skills/scientific-review/SKILL.md` for parity work

## Current evidence and gaps

### Implemented safeguards

- Core and storage modules are independent of Qt.
- Project JSON and text exports generally use explicit UTF-8; CSV/TSV writers
  use `newline=""`.
- Project-relative FCS paths are stored with POSIX separators and resolved from
  the bundle directory.
- JSON manifest writes use a same-directory temporary file, `fsync`, and
  `os.replace`; directory `fsync` is intentionally skipped on Windows.
- User cache, recovery, and debug paths normally use `QStandardPaths`.
- Windows, macOS, and Linux packages are built on native GitHub-hosted runners;
  PyInstaller is not used as a cross-compiler.
- Current production parallelism uses bounded threads rather than an unproven
  process backend, avoiding immediate Windows `spawn`/pickle problems.

These properties reduce risk but do not prove native GUI behavior or complete
package correctness.

### Confirmed defect

The packaged Windows PNG exporter does not contain DejaVu Sans. Its name-only
Pillow lookup fails and silently selects `ImageFont.load_default()`, which does
not honor the requested DPI-scaled size. This produces extremely small text
while lines, ticks, and points scale normally. The immediate correction belongs
to `windows-gui-export-font-parity.md` Increment 2A and must precede claims of
Windows rendering parity.

### High-risk gaps found in the current tree

| Area | Evidence in current implementation | Risk on Windows/macOS |
|---|---|---|
| Native GUI tests | Package workflows run `pytest -m "not gui"`; packaged smoke only creates a `MainWindow` and checks non-empty CLI outputs | Native fonts, Retina/Windows scaling, dialogs, clipboard, QThread teardown, and actual plots are not exercised |
| Font/resources | PNG uses name-only DejaVu lookup; PyInstaller specs bundle no application font | Missing or substituted fonts change text size and layout |
| Filename planning | `_safe_slug()` limits characters but does not reject DOS device names, bound component/path length, normalize Unicode, or use a portable case-insensitive collision key | `CON.png`, case-only names, NFC/NFD equivalents, or long titles may fail or collide differently by OS |
| Project paths | Foreign absolute POSIX/Windows paths are preserved, even when unusable on the current OS | A project can appear loaded but later fail FCS access without a clear reconnect state |
| Sample duplicate identity | Existing paths are tracked through native `Path.resolve()` equality | macOS default case-insensitive volumes, Unicode aliases, network shares, and case-sensitive volumes can behave differently |
| Temporary fallback | `app_paths.py` falls back to the literal `/tmp` if Qt does not return a temporary path | This is not a native Windows fallback and may select an unexpected drive-root path |
| Bundle saving | Individual JSON files are atomic, but a multi-file project update is not one transaction; Windows replacement can fail while a target is open | Partial bundle generations and sharing-violation errors need recovery semantics |
| Recovery ordering | Recovery freshness uses filesystem `st_mtime_ns` across separate directories | Timestamp resolution or copied/network files can misclassify the newest copy |
| Qt plugins | Collection relies largely on PyInstaller/PySide6 hooks and only checks window creation | JPEG/SVG/PDF/image-format availability and `qwindows`/`qcocoa` behavior are not asserted from the artifact |
| Qt lifecycle | Linux offscreen tests are the main behavioral evidence | Native close/cancel, clipboard ownership, modal dialogs, screen removal, sleep/resume, and thread-pool shutdown may differ |
| Settings | `QSettings` is global platform storage and tests do not uniformly isolate its backend | Registry/plist timing, stale values, and test/user-state leakage can be platform-specific |
| macOS distribution | CI produces zipped onedir folders, not a signed/notarized `.app`/DMG | Gatekeeper, bundle resources, Finder launch, quarantine, and app identity remain untested |
| Architecture | macOS CI is arm64 only; Windows is x64 | Intel macOS and Windows ARM64 are unsupported unless explicitly added |
| Scientific numerics | NumPy/BLAS implementations can differ across native runners; smoke checks non-empty output, not values | Compensation near singularity and events on gate boundaries can diverge without parity fixtures |

Treat rows marked as gaps as risks to verify, not as confirmed user-facing
failures unless a reproducer demonstrates them.

## Cross-platform contracts

### Rendering contract

- `PlotScene` content and logical geometry are platform-independent.
- Monitor DPI and device pixel ratio affect physical GUI display only. They do
  not change scientific bounds, gate coordinates, sampling, event colors, or
  export logical geometry.
- Raster adapters apply exactly one logical-to-raster scale. All fonts, lines,
  markers, tick lengths, and margins scale together.
- Required scalable fonts and licenses are package resources. Successful
  export must never depend on a font installed on the runner or user machine.
- Qt GUI and PNG/SVG/PDF adapters may rasterize differently, but must consume
  the same scene, text, style, anchors, and gate geometry. Tolerances must be
  declared per backend; missing/clipped text is never within tolerance.

### Path and filename contract

- Persist stable IDs separately from display names and filesystem paths.
- Store portable relative project references with `/`; retain foreign absolute
  paths only as unresolved metadata and expose a structured reconnect state.
- Never reinterpret `C:\\...`, UNC paths, `/Volumes/...`, or `/home/...` as a
  valid local path on a different OS.
- Before writing output, derive a portable collision key from Unicode NFC,
  case folding, trimmed trailing dots/spaces, and the final extension.
- Reject or deterministically escape Windows device names such as `CON`, `PRN`,
  `AUX`, `NUL`, `COM1` through `COM9`, and `LPT1` through `LPT9`, including
  names with extensions.
- Bound each component and the complete output path. Preserve uniqueness with a
  stable ID/hash suffix after truncation. Do not truncate by raw UTF-8 bytes in
  the middle of a code point.
- Detect collisions before workers start. Collision behavior and final names
  must be identical on case-sensitive and case-insensitive filesystems.
- Existing-file identity should use a reviewed helper that handles symlinks,
  `samefile()` where available, Unicode normalization, missing paths, and OS
  errors without changing persisted sample IDs.

### Storage and settings contract

- A failed save never changes the active project path or leaves a new bundle
  looking complete.
- Define a bundle generation/commit marker or staging-directory transaction so
  `manifest.json` and referenced gate files belong to the same generation.
- Handle Windows sharing violations as a structured, retryable error; never
  delete the previous valid file first.
- Use `tempfile.gettempdir()` or a Qt-provided native temporary directory, not a
  literal Unix path.
- Set application/organization identity before every `QSettings` access.
  Persisted settings require schema/version validation, explicit `sync()` at
  user-initiated save boundaries, and `status()` diagnostics.
- Tests must use an isolated temporary QSettings scope and must not read or
  modify the developer's registry, plist, or desktop settings.
- Recovery freshness should prefer persisted UTC generation metadata and a
  monotonic sequence within the application; filesystem mtime is supporting
  evidence only.

### Runtime and lifecycle contract

- Qt objects, `QPixmap`, widgets, dialogs, and painter operations remain on the
  GUI thread. Workers return immutable Python/NumPy data.
- Closing a window, cancelling work, or replacing a project must stop new work,
  ignore obsolete results, and wait for owned Qt thread pools at safe
  boundaries. Do not use `terminate()`.
- Thread-worker count must respect memory limits and numeric-library inner
  threads. Record effective workers and limiting factors.
- Do not add a process backend until a top-level picklable entry point,
  `spawn` behavior, `multiprocessing.freeze_support()`, frozen executable child
  startup, shared-memory ownership, cancellation, and cleanup pass all three
  native package tests.
- Native clipboard and file-dialog tests must use widget object names or
  programmatic APIs in CI. Keep a separate signed/manual test for OS dialogs;
  do not drive them by coordinates.

### Scientific parity contract

- The same project, FCS bytes, pipeline profile, and definitions produce exact
  event counts, membership masks, source ordering, and diagnostic codes on all
  supported OSes.
- Floating values have metric-specific tolerances justified in tests. Do not
  require byte-identical BLAS intermediates, and do not loosen gate membership
  assertions to hide boundary instability.
- Add explicit fixtures for big/little-endian FCS, Unicode metadata, spillover
  matrices, compensation near the documented condition threshold, derived
  non-finite values, transformed gate boundaries, and empty populations.
- Record Python, NumPy, BLAS/runtime, Qt, Pillow, architecture, and Flowdesk
  version with native parity artifacts.

## Numbered implementation increments

### Increment 1: Native CI observability and capability inventory

Target files:

- `.github/workflows/package-windows.yml`
- `.github/workflows/package-macos.yml`
- `.github/workflows/package-linux.yml`
- `packaging/smoke_test.py`
- `src/flowdesk_qt/diagnostics.py`
- `tests/packaging/`
- `tests/gui/`

Steps:

1. Produce one machine-readable environment report per OS containing OS/build,
   architecture, Python, NumPy/BLAS, Pillow, PySide6/Qt, pyqtgraph, filesystem
   case-sensitivity probe, preferred encoding, locale, Qt platform plugin,
   logical DPI, device ratio, available screens, and resolved package resources.
2. Add a package capability command/test that loads PNG/JPEG/SVG support,
   bundled fonts, CLI entry point, Qt platform plugin, and writable app/cache/temp
   locations from the built artifact.
3. Run a small native GUI test subset on Windows and macOS in addition to core
   tests. Capture a screenshot and structured UI state; window creation alone is
   insufficient.
4. Upload logs, screenshots, scene/sidecar JSON, and test reports on success and
   failure. Do not upload FCS event arrays or sensitive annotations.
5. Keep native-only failures visible. Do not mark an OS artifact successful when
   its capability or GUI subset fails.

Acceptance:

- Every release run states what was actually tested on each OS.
- Absence of a font/plugin/resource is reported before export starts.
- Native Windows/macOS evidence is distinguishable from Linux offscreen evidence.

### Increment 2: Deterministic packaged resources and rendering parity

Prerequisite: complete `windows-gui-export-font-parity.md` Increment 2A.

Target files include `src/flowdesk_core/plot_export.py`, a new GUI-independent
resource helper, `packaging/*.spec`, `THIRD_PARTY_NOTICES.md`, plot/export tests,
and packaged smoke tests.

Steps:

1. Bundle regular/bold scalable fonts and their exact license files in GUI and
   CLI artifacts. Resolve them with a source/frozen-safe resource API.
2. Inventory every runtime asset and remove CWD/system-install assumptions.
3. Verify Qt platform and image-format plugins required by actual workflows.
4. Render the same canonical scene at 96/300 DPI on Windows 100/125/150/200%
   scale and macOS Retina/non-Retina where runners permit.
5. Compare scene hashes exactly and normalized plot/font/gate geometry within
   declared tolerances. Store diagnostic overlays/difference images.
6. Test light/dark system themes without letting palette colors leak into the
   canonical plot background or export foreground.

Acceptance:

- No successful renderer silently substitutes a fixed-size or missing glyph
  font.
- DPI changes sharpness/pixel count while preserving normalized proportions.
- GUI, PNG, SVG, and PDF share scene content and no label/title is missing,
  clipped, or overlapped.

### Increment 3: Portable filename and collision policy

Target files:

- `src/flowdesk_core/batch_plot_export.py`
- a GUI-independent portable-path helper
- `src/flowdesk_core/export.py`
- batch/CLI/export tests

Steps:

1. Replace direct `Path` membership as the only collision rule with a portable
   filename key as defined above.
2. Handle DOS device names, trailing dots/spaces, NFC/NFD equivalents,
   case-only differences, empty slugs, long titles, multi-source prefixes, and
   suffix collisions before rendering begins.
3. Establish component/path limits conservatively and append a stable identity
   suffix after truncation.
4. Keep the original title and template in sidecar metadata; sanitization must
   affect filenames only.
5. Test `fail`, `replace`, and deterministic `suffix` policies against an
   emulated portable collision set on every host OS.

Acceptance:

- A plan created on Linux cannot produce invalid or aliased output names on
  Windows or default macOS filesystems.
- Sequential/thread execution and all output formats choose identical names.

### Increment 4: Project path portability and reconnect behavior

Target files:

- `src/flowdesk_storage/project.py`
- `src/flowdesk_qt/sample_browser.py`
- `src/flowdesk_qt/main_window.py`
- project schema/migration only if the state contract changes
- storage, GUI, headless, and CLI tests

Steps:

1. Introduce a typed path-resolution result: resolved, missing, foreign
   absolute, permission denied, ambiguous alias, or unsupported scheme.
2. Preserve foreign path text for provenance but never treat it as locally
   usable. Show Reconnect without discarding stable sample ID/fingerprint.
3. Test portable relatives, `..`, spaces, Japanese text, NFC/NFD, case-only
   names, Windows drive paths, UNC paths, long paths, macOS `/Volumes`, Linux
   absolute paths, symlinks, and missing files.
4. Audit duplicate detection with existing-file identity while preserving raw
   metadata and stable sample IDs.
5. Ensure Save As rebases only locally resolvable paths and cannot overwrite the
   opened source project accidentally.

Acceptance:

- Load/save/load never silently retargets an FCS file.
- A project moved between OSes either resolves the same relative sample or
  presents an explicit reconnect state before analysis.
- GUI and CLI report the same resolution status and fingerprint decision.

### Increment 5: Transactional bundle save, recovery, and QSettings

Target files:

- `src/flowdesk_storage/serialization.py`
- `src/flowdesk_storage/project.py`
- `src/flowdesk_storage/recovery.py`
- `src/flowdesk_qt/app_paths.py`
- QSettings callers and related tests

Steps:

1. Replace the literal `/tmp` fallback with a native temporary-directory API.
2. Define a bundle generation contract so a crash between gate and manifest
   writes cannot expose mixed generations as valid.
3. Preserve the previous valid generation on permission, disk-full, sharing,
   antivirus, or rename failure. Clean only owned staging files.
4. Use persisted UTC generation metadata/sequence for recovery ordering and
   test coarse timestamp filesystems.
5. Centralize QSettings construction/identity/schema, isolate tests, call
   `sync()` at explicit persistence boundaries, and surface non-success status.
6. Test read-only folders, locked targets (native Windows), network-style
   rename failure, abrupt failure injection, and filenames containing Unicode.

Acceptance:

- Failed save/recovery/settings writes do not change the active project or
  destroy the previous valid state.
- No runtime state is written into the installation directory.

### Increment 6: Native Qt interaction and lifecycle

Target files:

- `src/flowdesk_qt/*scheduler.py`
- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/sample_sheet.py`
- dialogs and GUI diagnostics/tests

Steps:

1. Exercise sample switching, density calculation, Pipeline, Batch Export,
   cancel, project replacement, and close on native Windows/macOS Qt plugins.
2. Assert that all GUI mutations occur on the GUI thread and that owned
   QThreads/QThreadPools have no active work after close.
3. Test clipboard paste using Unicode TSV, CRLF/LF, empty cells, and large
   selections through programmatic clipboard MIME data. Preserve the existing
   no-segmentation-fault contract.
4. Test resize/scroll behavior at 100–200% Windows scaling and macOS Retina,
   including Batch Export and Plot Presentation dialogs.
5. Test native file-dialog results through thin programmatic seams; retain a
   manual/signed-app checklist for behavior CI cannot automate.
6. Test display connect/disconnect and DPI-change events without altering
   canonical scene state.

Acceptance:

- Cancel/close/project replacement produces no crash, late adoption, or worker
  leak on native packages.
- Clipboard, dialogs, shortcuts, focus, and resizable content remain usable at
  supported display scales.

### Increment 7: Parallel runtime and scientific parity matrix

Target files:

- core runner/execution-control modules
- batch/density runtime modules
- native benchmark/parity tools and workflows

Steps:

1. Compare sequential and bounded threads on all supported OSes for result
   order, counts, masks, diagnostics, scene hashes, filenames, cancellation,
   cleanup, peak RSS, and effective worker provenance.
2. Record BLAS/OpenMP runtime and inner-thread settings; prevent accidental
   worker × BLAS oversubscription from being mistaken for an application bug.
3. Add scientific parity fixtures described above. Use exact assertions for
   discrete results and documented tolerances for continuous outputs.
4. Keep process execution deferred unless every process-backend gate in the
   runtime contract is implemented and measured in frozen applications.
5. Do not make a faster platform's worker count the universal default without
   native memory and lifecycle evidence.

Acceptance:

- Scientific output and deterministic ordering are OS-independent.
- Performance controls never weaken correctness, cancellation, or memory
  limits; unsupported process behavior is not exposed.

### Increment 8: Installers, signing, and clean-machine acceptance

Target files:

- packaging scripts/specs
- native workflows
- release documentation and user manual

Steps:

1. Build a Windows per-user installer and test install, upgrade, uninstall,
   Start Menu launch, writable locations, optional file association, and
   SmartScreen documentation.
2. Build a proper macOS `.app` and DMG. Verify Finder launch, bundle resources,
   Developer ID signing, Hardened Runtime, notarization, ticket stapling, and
   Gatekeeper. Unsigned artifacts must be labeled development-only.
3. State supported architectures explicitly. Do not label Intel macOS or
   Windows ARM64 supported without native artifacts/tests.
4. Run the complete acceptance project from paths containing Japanese text,
   spaces, long components, and a case-collision probe on clean machines
   without a development Python installation.
5. Attach checksums, build manifest, dependency/license inventory, test report,
   and known limitations to the release.

Acceptance:

- Each advertised OS/architecture has a native, installable, tested artifact.
- A failed platform job prevents that platform artifact from being published
  as supported.

## Required test matrix

At minimum, native evidence must cover:

| Contract | Windows x64 | macOS arm64 | Linux x86_64 |
|---|---:|---:|---:|
| Source core/CLI tests | required | required | required |
| Source GUI subset | required | required | required |
| Frozen capability/resource test | required | required | required |
| Frozen GUI screenshot/state | required | required | required |
| FCS inspect + Pipeline + save/reload | required | required | required |
| PNG/JPEG/SVG/PDF export content checks | required | required | required |
| Unicode/space/long/portable path suite | required | required | required |
| Sequential/thread parity and cleanup | required | required | required |
| Installer/Finder/Start Menu launch | required before installer claim | required before DMG claim | per chosen package |

Visual comparison must use the same logical canvas. Image-viewer zoom is
recorded but never used to excuse a mismatch between text and other elements.

## Prohibited shortcuts

- Do not claim Windows/macOS support from Linux offscreen tests.
- Do not add OS-name branches to scientific calculations.
- Do not use the current working directory or a system-installed font/resource.
- Do not weaken assertions, skip native failures, or accept merely non-empty
  images as renderer parity.
- Do not lowercase or Unicode-normalize scientific/sample metadata in place.
- Do not use display names or row positions as persisted identity.
- Do not delete an existing project/output before a replacement is safely
  staged.
- Do not introduce process workers merely to increase CPU utilization.

## Verification commands

Run locally where applicable:

```bash
python -m pytest -m "not gui" -q
./tools/run-gui-tests.sh -q
python -m pytest tests/packaging -q
python -m ruff check src tests packaging tools
git diff --check
```

Native workflow commands and artifact identifiers must be recorded in the
implementation report. If a native OS or signed installer is unavailable,
leave its checkbox incomplete and state exactly which contract remains
unverified.
