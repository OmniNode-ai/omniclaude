# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""QPM Audit Ledger.

Writes and reads QPM run audit entries to disk as JSON files.
Each run gets its own directory under the audit root.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from merge_planner.models import ModelQPMAuditEntry


def _default_audit_root() -> Path:
    from omniclaude.hooks.lib.onex_state import ensure_state_dir

    return ensure_state_dir("qpm-audit", "runs")


def _validate_run_id(run_id: str) -> None:
    """Reject run_id values that could cause path traversal."""
    p = PurePosixPath(run_id)
    if ".." in p.parts or p.is_absolute() or "/" in run_id or "\\" in run_id:
        msg = f"Invalid run_id (path traversal attempt): {run_id!r}"
        raise ValueError(msg)


def write_audit(entry: ModelQPMAuditEntry, *, root: Path | None = None) -> Path:
    """Write audit entry to disk. Returns path to written file."""
    _validate_run_id(entry.run_id)
    audit_root = root or _default_audit_root()
    run_dir = audit_root / entry.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    audit_path = run_dir / "audit.json"
    audit_path.write_text(entry.model_dump_json(indent=2))
    return audit_path


def read_audit(run_id: str, *, root: Path | None = None) -> ModelQPMAuditEntry | None:
    """Read audit entry. Returns None if not found."""
    _validate_run_id(run_id)
    audit_root = root or _default_audit_root()
    audit_path = audit_root / run_id / "audit.json"
    if not audit_path.exists():
        return None
    return ModelQPMAuditEntry.model_validate_json(audit_path.read_text())


def list_recent_audits(
    *, limit: int = 20, root: Path | None = None
) -> list[ModelQPMAuditEntry]:
    """List recent audit entries sorted by directory mtime, newest first."""
    audit_root = root or _default_audit_root()
    if not audit_root.exists():
        return []
    dirs = sorted(
        (d for d in audit_root.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    entries: list[ModelQPMAuditEntry] = []
    for d in dirs[:limit]:
        entry = read_audit(d.name, root=audit_root)
        if entry is not None:
            entries.append(entry)
    return entries
