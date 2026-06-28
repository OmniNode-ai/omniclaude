# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""docs_dirty_alert check — scans omni_home for untracked docs files.

Alerts when untracked files in docs/{handoffs,evidence,plans,deep-dives}
exceed a count threshold OR any file's mtime is older than age_threshold_seconds.

Run directly:
    uv run python -m omniclaude.nodes.node_skill_docs_dirty_alert_orchestrator.check

Exit 0 = clean.  Exit 1 = alert fired.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Subdirectories of docs/ that are tracked by this alert
_DOCS_SUBDIRS = ("handoffs", "evidence", "plans", "deep-dives")


@dataclass
class UntrackedFile:
    """A single untracked docs file."""

    repo_relative_path: str
    abs_path: Path
    mtime: float  # seconds since epoch
    age_seconds: float  # computed at scan time


@dataclass
class DocsDirtyCheckResult:
    """Result of a single docs-dirty scan."""

    omni_home: Path
    untracked_files: list[UntrackedFile]
    oldest_age_seconds: float | None
    alert_fired: bool
    alert_reasons: list[str] = field(default_factory=list)
    friction_path: Path | None = None


@dataclass
class DocsDirtyAlertConfig:
    """Configuration for the docs-dirty alert check."""

    omni_home: Path
    state_dir: Path
    count_threshold: int = 50
    age_threshold_seconds: float = 14_400.0  # 4 hours
    docs_subdirs: tuple[str, ...] = _DOCS_SUBDIRS


def _run_git_status(omni_home: Path, docs_subdirs: tuple[str, ...]) -> list[str]:
    """Run git status --porcelain on the docs subdirs; return ?? lines."""
    paths = [f"docs/{sub}" for sub in docs_subdirs]
    cmd = ["git", "-C", str(omni_home), "status", "--porcelain", "--"] + paths
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("docs_dirty_alert: git status failed: %s", exc)
        return []

    lines = []
    for line in result.stdout.splitlines():
        # ?? = untracked;  !! = ignored (skip ignored).
        # Also capture modified/added (M, A) uncommitted files.
        # The ticket asks for "untracked" — git shows ?? prefix.
        if line.startswith("??"):
            lines.append(line)
    return lines


def _collect_untracked_files(
    omni_home: Path,
    status_lines: list[str],
    *,
    now_ts: float,
) -> list[UntrackedFile]:
    """Convert git status ?? lines to UntrackedFile entries with mtime."""
    result: list[UntrackedFile] = []
    for line in status_lines:
        # Format: "?? path/to/file" (may end with "/" for directories)
        raw_path = line[3:].strip().rstrip("/")
        abs_path = omni_home / raw_path
        try:
            if abs_path.is_dir():
                # Untracked dir — count each file inside it
                for child in abs_path.rglob("*"):
                    if child.is_file():
                        mtime = child.stat().st_mtime
                        result.append(
                            UntrackedFile(
                                repo_relative_path=str(child.relative_to(omni_home)),
                                abs_path=child,
                                mtime=mtime,
                                age_seconds=now_ts - mtime,
                            )
                        )
            elif abs_path.is_file():
                mtime = abs_path.stat().st_mtime
                result.append(
                    UntrackedFile(
                        repo_relative_path=raw_path,
                        abs_path=abs_path,
                        mtime=mtime,
                        age_seconds=now_ts - mtime,
                    )
                )
        except OSError as exc:
            logger.warning("docs_dirty_alert: stat failed for %s: %s", abs_path, exc)
    return result


def _write_friction_yaml(
    friction_dir: Path,
    data: dict[str, object],
    now: datetime,
) -> Path:
    import yaml  # noqa: PLC0415

    friction_dir.mkdir(parents=True, exist_ok=True)
    ts = now.strftime("%Y-%m-%d-%H-%M-%S")
    path = friction_dir / f"docs-dirty-alert-{ts}.yaml"
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    tmp.rename(path)
    return path


def run_docs_dirty_check(
    config: DocsDirtyAlertConfig,
    *,
    now: datetime | None = None,
) -> DocsDirtyCheckResult:
    """Run the docs-dirty alert check.

    Args:
        config: Alert configuration.
        now: Datetime to use for age calculations (injectable for testing).

    Returns:
        DocsDirtyCheckResult with alert_fired=True if either threshold exceeded.
    """
    if now is None:
        now = datetime.now(UTC)
    now_ts = now.timestamp()

    status_lines = _run_git_status(config.omni_home, config.docs_subdirs)
    untracked = _collect_untracked_files(config.omni_home, status_lines, now_ts=now_ts)

    oldest_age: float | None = max((f.age_seconds for f in untracked), default=None)
    alert_reasons: list[str] = []

    if len(untracked) >= config.count_threshold:
        alert_reasons.append(
            f"{len(untracked)} untracked docs files >= threshold {config.count_threshold}"
        )

    if oldest_age is not None and oldest_age >= config.age_threshold_seconds:
        oldest_file = max(untracked, key=lambda f: f.age_seconds)
        hours = oldest_age / 3600
        alert_reasons.append(
            f"oldest untracked file is {hours:.1f}h old (>{config.age_threshold_seconds / 3600:.0f}h): "
            f"{oldest_file.repo_relative_path}"
        )

    alert_fired = len(alert_reasons) > 0

    if not alert_fired:
        return DocsDirtyCheckResult(
            omni_home=config.omni_home,
            untracked_files=untracked,
            oldest_age_seconds=oldest_age,
            alert_fired=False,
        )

    # Write friction YAML
    summary_paths = [f.repo_relative_path for f in untracked[:10]]
    friction_data: dict[str, object] = {
        "surface": "docs/dirty-canonical",
        "severity": "high",
        "skill": "docs_dirty_alert",
        "description": "; ".join(alert_reasons),
        "untracked_count": len(untracked),
        "oldest_age_hours": round(oldest_age / 3600, 2) if oldest_age else None,
        "sample_paths": summary_paths,
        "timestamp": now.isoformat(),
        "context_ticket_id": "OMN-13046",
    }

    friction_dir = config.state_dir / "friction"
    friction_path = _write_friction_yaml(friction_dir, friction_data, now)
    logger.warning(
        "docs_dirty_alert: alert fired (%s), friction written to %s",
        "; ".join(alert_reasons),
        friction_path,
    )

    return DocsDirtyCheckResult(
        omni_home=config.omni_home,
        untracked_files=untracked,
        oldest_age_seconds=oldest_age,
        alert_fired=True,
        alert_reasons=alert_reasons,
        friction_path=friction_path,
    )


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    raw_omni_home = os.environ.get("OMNI_HOME")
    if not raw_omni_home:
        raise SystemExit(
            "OMNI_HOME env var is required — set it to the omni_home registry root"
        )
    raw_state_dir = os.environ.get("ONEX_STATE_DIR")
    if not raw_state_dir:
        raise SystemExit(
            "ONEX_STATE_DIR env var is required — set it in ~/.omnibase/.env"
        )

    config = DocsDirtyAlertConfig(
        omni_home=Path(raw_omni_home),
        state_dir=Path(raw_state_dir),
    )
    result = run_docs_dirty_check(config)

    if result.alert_fired:
        sys.stdout.write(
            f"ALERT: {len(result.untracked_files)} untracked docs files; "
            f"friction written to {result.friction_path}\n"
        )
        for reason in result.alert_reasons:
            sys.stdout.write(f"  - {reason}\n")
        sys.exit(1)
    else:
        count = len(result.untracked_files)
        sys.stdout.write(f"OK: {count} untracked docs file(s), all within thresholds\n")
        sys.exit(0)
