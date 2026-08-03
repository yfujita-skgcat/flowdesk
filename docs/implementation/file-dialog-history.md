# File dialog directory history

## Scope

File-menu dialogs remember the last usable directory for their own operation. The
history is application-level UI state, not analysis state, and is stored with `QSettings`.

## Operation keys

Use separate keys for FCS directory selection, FCS file selection, opening a project,
saving a project, saving/loading analysis settings, and selecting a recovery-copy
destination. A dialog cancellation must not overwrite its key. A successful selection
stores the selected directory, or the parent directory for a file returned by a save/open
file dialog.

## Initial-directory resolution

1. Use the operation's stored directory when it still exists.
2. Otherwise use the operation-specific project-path fallback when available.
3. Otherwise use the current working directory.

The implementation must pass a directory, never a stale file path, to Qt file dialogs.
Invalid or missing stored paths are ignored without raising an exception.

## Acceptance criteria

- FCS, project, settings, and recovery dialogs do not overwrite one another's history.
- Cancelled dialogs preserve the previous directory.
- Save dialogs remember the parent directory of the selected output path.
- Existing projects/settings continue to provide a useful first-launch fallback.
- GUI tests isolate and restore `QSettings` values.
