# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""QPM Audit Ledger.

Writes and reads QPM run audit entries to disk as JSON files.
Each run gets its own directory under the audit root.
"""

from __future__ import annotations

from pathlib import Path

from merge_planner.models import ModelQPMAuditEntry

DEFAULT_AUDIT_ROOT = Path.home() / ".claude" / "qpm-audit" / "runs"


def write_audit(entry: ModelQPMAuditEntry, *, root: Path | None = None) -> Path:
    """Write audit entry to disk. Returns path to written file."""
    audit_root = root or DEFAULT_AUDIT_ROOT
    run_dir = audit_root / entry.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    audit_path = run_dir / "audit.json"
    audit_path.write_text(entry.model_dump_json(indent=2))
    return audit_path


def read_audit(run_id: str, *, root: Path | None = None) -> ModelQPMAuditEntry | None:
    """Read audit entry. Returns None if not found."""
    audit_root = root or DEFAULT_AUDIT_ROOT
    audit_path = audit_root / run_id / "audit.json"
    if not audit_path.exists():
        return None
    return ModelQPMAuditEntry.model_validate_json(audit_path.read_text())


def list_recent_audits(
    *, limit: int = 20, root: Path | None = None
) -> list[ModelQPMAuditEntry]:
    """List recent audit entries sorted by directory mtime, newest first."""
    audit_root = root or DEFAULT_AUDIT_ROOT
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
