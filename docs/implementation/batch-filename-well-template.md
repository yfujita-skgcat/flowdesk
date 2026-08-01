# Batch filename `{well}` template variable

## Purpose

Provide a stable well component for batch output filenames when the well is
encoded in the resolved Sample Sheet title.

## Rules

- Add `{well}` to the existing filename-template variables.
- Inspect resolved titles for a standalone row letter A–P followed by a
  one-to-three-digit well number, such as `A1` or `C12`.
- Determine numeric padding from the maximum number of digits found across all
  samples supplied to the batch plan, with a minimum width of two digits.
- Format `A1` as `A01` when the width is two and as `A001` when the width is
  three. Preserve the row letter in uppercase.
- If a title has no well token, use `X` followed by zeroes at the same width
  (`X00`, `X000`, ...).
- Keep existing metadata/filename well prefixes and all other template
  variables unchanged. `{well}` is the title-derived component and is not a
  replacement for provenance fields.

## Verification

Test two-digit, three-digit, and missing-title well cases in batch planning.
Confirm that output collision handling and existing filename prefixes remain
unchanged.
