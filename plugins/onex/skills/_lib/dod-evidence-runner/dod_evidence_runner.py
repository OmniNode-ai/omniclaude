# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""DoD Evidence Runner — execute checks and produce structured results.

Shared utility that all DoD enforcement layers call. Runs checks defined
in dod_evidence[] items, produces structured results, and writes evidence
receipts to .evidence/<ticket_id>/dod_report.json.
"""

from __future__ import annotations

import glob
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class CheckResult:
    """Result of running a single DoD check."""

    check_type: str
    check_value: str | dict[str, str]
    status: str  # "verified" | "failed" | "skipped"
    message: str = ""
    duration_ms: float = 0.0


@dataclass
class EvidenceItemResult:
    """Result for a single DoD evidence item (may have multiple checks)."""

    id: str
    description: str
    status: str  # "verified" | "failed" | "skipped"
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class EvidenceRunResult:
    """Aggregate result of running all DoD evidence items."""

    total: int = 0
    verified: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[EvidenceItemResult] = field(default_factory=list)


@dataclass
class EvidenceReceipt:
    """Full evidence receipt with provenance."""

    ticket_id: str
    timestamp: str
    git_sha: str
    branch: str
    working_dir: str
    contract_path: str
    result: EvidenceRunResult = field(default_factory=EvidenceRunResult)


def _run_check_test_exists(check_value: str | dict[str, str]) -> CheckResult:
    """Check if test files exist matching the pattern."""
    pattern = str(check_value)
    # Ensure we look for test files
    if not pattern.endswith("*"):
        search = f"{pattern.rstrip('/')}/**/test_*.py"
    else:
        search = pattern

    matches = glob.glob(search, recursive=True)
    if matches:
        return CheckResult(
            check_type="test_exists",
            check_value=check_value,
            status="verified",
            message=f"Found {len(matches)} test file(s)",
        )
    return CheckResult(
        check_type="test_exists",
        check_value=check_value,
        status="failed",
        message=f"No test files matching pattern: {search}",
    )


def _run_check_test_passes(check_value: str | dict[str, str]) -> CheckResult:
    """Run pytest and check exit code."""
    cmd = str(check_value)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
        if result.returncode == 0:
            return CheckResult(
                check_type="test_passes",
                check_value=check_value,
                status="verified",
                message="Tests passed",
            )
        return CheckResult(
            check_type="test_passes",
            check_value=check_value,
            status="failed",
            message=f"Exit code {result.returncode}: {result.stderr[:500]}",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            check_type="test_passes",
            check_value=check_value,
            status="failed",
            message=f"Timeout after {_DEFAULT_TIMEOUT_SECONDS}s",
        )


def _run_check_file_exists(check_value: str | dict[str, str]) -> CheckResult:
    """Check if files matching a glob pattern exist."""
    pattern = str(check_value)
    matches = glob.glob(pattern, recursive=True)
    if matches:
        return CheckResult(
            check_type="file_exists",
            check_value=check_value,
            status="verified",
            message=f"Found {len(matches)} file(s)",
        )
    return CheckResult(
        check_type="file_exists",
        check_value=check_value,
        status="failed",
        message=f"No files matching pattern: {pattern}",
    )


def _run_check_grep(check_value: str | dict[str, str]) -> CheckResult:
    """Search for a pattern in files."""
    if isinstance(check_value, dict):
        pattern = check_value.get("pattern", "")
        path = check_value.get("path", ".")
    else:
        pattern = str(check_value)
        path = "."

    try:
        result = subprocess.run(
            ["grep", "-r", "-l", pattern, path],
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = result.stdout.strip().split("\n")
            return CheckResult(
                check_type="grep",
                check_value=check_value,
                status="verified",
                message=f"Pattern found in {len(files)} file(s)",
            )
        return CheckResult(
            check_type="grep",
            check_value=check_value,
            status="failed",
            message=f"Pattern '{pattern}' not found in {path}",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            check_type="grep",
            check_value=check_value,
            status="failed",
            message=f"Timeout after {_DEFAULT_TIMEOUT_SECONDS}s",
        )


def _run_check_command(check_value: str | dict[str, str]) -> CheckResult:
    """Run an arbitrary command and check exit code."""
    cmd = str(check_value)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
        if result.returncode == 0:
            return CheckResult(
                check_type="command",
                check_value=check_value,
                status="verified",
                message="Command succeeded",
            )
        return CheckResult(
            check_type="command",
            check_value=check_value,
            status="failed",
            message=f"Exit code {result.returncode}: {result.stderr[:500]}",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            check_type="command",
            check_value=check_value,
            status="failed",
            message=f"Timeout after {_DEFAULT_TIMEOUT_SECONDS}s",
        )


def _run_check_endpoint(check_value: str | dict[str, str]) -> CheckResult:
    """Check if an endpoint is reachable (skipped — requires live infra)."""
    return CheckResult(
        check_type="endpoint",
        check_value=check_value,
        status="skipped",
        message="Endpoint checks are skipped in offline mode",
    )


_CHECK_RUNNERS = {
    "test_exists": _run_check_test_exists,
    "test_passes": _run_check_test_passes,
    "file_exists": _run_check_file_exists,
    "grep": _run_check_grep,
    "command": _run_check_command,
    "endpoint": _run_check_endpoint,
}


def run_dod_evidence(
    evidence_items: list[dict[str, Any]],
) -> EvidenceRunResult:
    """Run all DoD evidence checks and produce structured results.

    Args:
        evidence_items: List of dod_evidence item dicts from the contract,
            each with keys: id, description, checks (list of {check_type, check_value}),
            and optionally status.

    Returns:
        EvidenceRunResult with aggregate counts and per-item details.

    """
    result = EvidenceRunResult(total=len(evidence_items))

    for item in evidence_items:
        item_id = item.get("id", "unknown")
        description = item.get("description", "")
        checks = item.get("checks", [])

        check_results: list[CheckResult] = []
        item_status = "verified"

        for check in checks:
            check_type = check.get("check_type", "command")
            check_value = check.get("check_value", "")

            runner = _CHECK_RUNNERS.get(check_type, _run_check_command)
            start = time.monotonic()
            cr = runner(check_value)
            cr.duration_ms = (time.monotonic() - start) * 1000

            check_results.append(cr)

            if cr.status == "failed":
                item_status = "failed"
            elif cr.status == "skipped" and item_status == "verified":
                item_status = "skipped"

        item_result = EvidenceItemResult(
            id=item_id,
            description=description,
            status=item_status,
            checks=check_results,
        )
        result.details.append(item_result)

        if item_status == "verified":
            result.verified += 1
        elif item_status == "failed":
            result.failed += 1
        else:
            result.skipped += 1

    return result


def _get_git_info(working_dir: str) -> tuple[str, str]:
    """Get current git SHA and branch name."""
    sha = ""
    branch = ""
    try:
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=5,
        )
        if sha_result.returncode == 0:
            sha = sha_result.stdout.strip()

        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=5,
        )
        if branch_result.returncode == 0:
            branch = branch_result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return sha, branch


def write_evidence_receipt(
    ticket_id: str,
    contract_path: str,
    run_result: EvidenceRunResult,
    working_dir: str | None = None,
    output_dir: str | None = None,
) -> Path:
    """Write an evidence receipt JSON file.

    Args:
        ticket_id: The ticket identifier (e.g., "OMN-5168").
        contract_path: Path to the contract YAML that was checked.
        run_result: The results from run_dod_evidence().
        working_dir: Working directory for git info (defaults to cwd).
        output_dir: Base directory for evidence output (defaults to
            .evidence/<ticket_id>/).

    Returns:
        Path to the written receipt file.

    """
    if working_dir is None:
        working_dir = str(Path.cwd())

    if output_dir is None:
        output_dir = str(Path(working_dir) / ".evidence" / ticket_id)

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    git_sha, branch = _get_git_info(working_dir)

    receipt = EvidenceReceipt(
        ticket_id=ticket_id,
        timestamp=datetime.now(tz=UTC).isoformat(),
        git_sha=git_sha,
        branch=branch,
        working_dir=working_dir,
        contract_path=contract_path,
        result=run_result,
    )

    receipt_path = Path(output_dir) / "dod_report.json"
    receipt_path.write_text(json.dumps(asdict(receipt), indent=2, default=str))

    return receipt_path
