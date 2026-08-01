# Sample Sheet spreadsheet copy

## Purpose

Allow selected Sample Sheet rows to be copied with `Ctrl+C` and pasted into
Google Sheets, Excel, or another tabular editor with one value per cell.

## Rules

- Copy selected rows from the proxy view in their current visual order.
- Include every Sample Sheet column, including workspace annotation columns.
- Emit tab-separated text with one row per line; quote cells containing tabs or
  newlines so their contents remain in one spreadsheet cell.
- Copying is read-only and must not modify annotations, sorting, filtering, or
  project state.
- Keep the existing Paste button workflow unchanged.

## Target files and tests

- `src/flowdesk_qt/sample_sheet.py`: table view copy handling and TSV encoder.
- `tests/gui/test_sample_sheet.py`: selected-row clipboard regression test.
- `docs/user-manual/user_manual.md`: document the shortcut and output format.

## Acceptance criteria

1. Selecting one or more rows and pressing `Ctrl+C` places TSV text on the Qt
   clipboard.
2. Pasting that text into a spreadsheet creates separate rows and columns.
3. No annotation or project data changes as a side effect.
