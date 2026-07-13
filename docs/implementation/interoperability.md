# Interoperability, Archive, FCS Export, WSP Import, and De-identification

Spec: `S15`, `S16`
ToDo: `Phase C4`, `C5`, `C6`, `C8`

## Goal

Exchange definitions/data without silent loss and create verifiable portable archives.
Each format is a separate increment and must produce a compatibility report.

## Inspect first

- `src/flowdesk_core/fcs_io.py`, `export.py`, all gate/transform models
- `src/flowdesk_storage/project.py`, `serialization.py`, schemas
- CLI command routing and tests
- `examples/` and fixture licensing notes

Read `fcs-io.md`, `export-and-cli.md`, `project-storage.md`, and scientific transform guides.

## Shared contract

`CompatibilityReport` records imported/exported, approximated, unsupported, and failed
objects by stable ID and reason. Unsupported objects are never silently omitted. Original
input files are never overwritten.

## Increments

### C4: Portable archive

1. Specify archive manifest, relative paths, checksums, media types, and size limits.
2. Add create/list/verify commands.
3. Add safe extraction rejecting absolute paths, `..`, symlink escape, duplicates, and
   checksum mismatch.
4. Verify extracted project and headless results against source.
5. Add GUI progress/contents preview after CLI/core passes.

### C5: GatingML and FCS export

1. Publish a support matrix for each gate/transform type.
2. Implement rectangle/range/polygon import/export with namespace/version fixtures.
3. Add ellipse/quadrant/hierarchy, one type per increment.
4. Emit compatibility report for Boolean/custom transforms.
5. Export selected Population events to a new FCS with explicit metadata-source policy.
6. Validate round trip using an independent parser/validator where available.

### C6: WSP read-only import

1. Record supported WSP versions and licensed/synthetic fixtures.
2. Parse sample references only; then compensation; then basic gates/hierarchy.
3. Preserve unknown XML/plugin/platform nodes as opaque metadata plus warnings.
4. Write a new `.flowdesk` project; never modify WSP.
5. Compare any claimed FlowJo parity using recorded FlowJo version/settings/input hash.

### C8: De-identification

1. Define remove/replace/hash policy schema and required-key protection.
2. Add dry-run preview and audit report.
3. Write a new FCS/archive and verify removed values are absent.
4. Record input/output hashes without logging original sensitive values.

## Required tests

- Malicious archive paths and checksum failures are rejected.
- GatingML round trip retains supported geometry/transform references.
- Unsupported nodes appear in the compatibility report.
- Exported FCS event count equals selected full membership.
- De-identification keeps required FCS structure and never changes source bytes.

## Stop conditions

Stop if a fixture's license/provenance is unknown, a proprietary transform cannot be
reproduced, or import would require guessing a reference. Preserve opaque data and report.

## Verification

```bash
pytest -q tests/test_fcs_io.py tests/test_export.py tests/test_project_storage.py tests/test_cli.py
ruff check src tests
```
