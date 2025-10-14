Violations Logging
==================

This directory stores generated logs and schemas for hook violations.

Guidelines
----------

- Generated JSON summaries (`violations_summary.json`) are ignored by Git.
- Schema files (`*.schema.json`) and this README are committed.
- Producers must write a trailing newline at EOF.
- Timestamps must be UTC ISO-8601 with `Z` suffix.

Schema Overview
---------------

Top-level keys:

- `schema_version`: string, semantic version of this schema (e.g. `1.0.0`).
- `run_id`: string, unique ID for the producing run.
- `commit_sha`: string, git SHA associated with the run.
- `branch`: string, git branch.
- `env`: string, environment (e.g. `local`, `ci`).
- `last_updated`: string, UTC ISO-8601 timestamp.
- `window_start`/`window_end`: string timestamps delimiting the aggregation window.
- `total_violations_today`: integer count within the defined window.
- `files_with_violations`: array of file-level aggregates.

Each file entry:

- `path`: string, repository-relative path.
- `violations`: integer, count.
- `timestamp`: string, last observation time for this file.
- `suggestions`: array of strings (deprecated; prefer `violation_codes`).
- `violation_codes` (optional): array of strings from a canonical enum.
- `severity_breakdown` (optional): object mapping severity to counts.

See `violations_summary.schema.json` for the precise schema.


