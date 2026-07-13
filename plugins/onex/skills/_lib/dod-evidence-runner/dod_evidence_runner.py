# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""DoD Evidence Runner — execute checks and produce structured results.

Shared utility that all DoD enforcement layers call. Runs checks defined
in dod_evidence[] items, produces structured results, and writes evidence
receipts to .evidence/<ticket_id>/dod_report.json.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from omnibase_core.enums.ticket.enum_receipt_status import EnumReceiptStatus
    from omnibase_core.models.contracts.ticket.model_dod_receipt import ModelDodReceipt

    _CORE_AVAILABLE = True
except ImportError:
    _CORE_AVAILABLE = False

# Canonical OMNI_HOME-derived evidence-root resolver (<TICKET>). This replaces
# the legacy ONEX_EVIDENCE_ROOT env-var read: the resolver reads ``OMNI_HOME``
# fail-fast and returns ``$OMNI_HOME/onex_change_control/evidence`` — the same
# path the legacy ONEX_EVIDENCE_ROOT env var pointed at. The
# import is guarded because omnibase_core < 0.46 predates ``util_omni_home_paths``;
# when the resolver is unavailable, ``resolve_evidence_output_dir`` uses the
# local-run ``.evidence/<ticket_id>`` default. Once core is bumped the resolver
# is the primary path with no further change here.
try:
    from omnibase_core.utils.util_omni_home_paths import resolve_evidence_root
except ImportError:
    resolve_evidence_root = None  # type: ignore[assignment]

# <TICKET>: import the inert-check detector from the hosted Contract
# Compliance engine instead of forking a second copy of the regex patterns.
# Before this, a check_value that only reads ``drift/dod_receipts/`` or
# ``contracts/OMN-*`` (structurally incapable of observing the product) would
# locally report whatever its raw glob/grep/exit code happened to be -- often
# a false "verified" -- while the hosted CI gate demoted the identical check
# to WARN. That divergence is exactly what let OCC PRs look valid locally and
# fail remotely. Guarded because an omniclaude build pinned to an
# onex-change-control release that predates <TICKET> (no
# ``contract_compliance_check`` module yet) must not crash -- it degrades to
# "no demotion" rather than reintroducing a duplicate.
try:
    from onex_change_control.scripts.contract_compliance_check import (
        _is_inert_check as _occ_is_inert_check,
    )

    _OCC_COMPLIANCE_ENGINE_AVAILABLE = True
except ImportError:
    _occ_is_inert_check = None  # type: ignore[assignment]
    _OCC_COMPLIANCE_ENGINE_AVAILABLE = False

_DEFAULT_TIMEOUT_SECONDS = 30

logger = logging.getLogger(__name__)


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


def is_inert_check(check_value: str | dict[str, str]) -> bool:
    """True if check_value can only observe the OCC receipt/contract store.

    Delegates to the same ``_is_inert_check`` the hosted Contract Compliance
    gate enforces (onex_change_control.scripts.contract_compliance_check),
    so a check that is inert is treated identically local vs hosted rather
    than maintained as a second copy of the pattern list. When the shared
    engine is unavailable (stale onex-change-control pin), degrades to "not
    inert" -- i.e. no local demotion -- rather than reimplementing the
    regex, so the hosted gate remains the single source of truth for what
    counts as inert.
    """
    if not _OCC_COMPLIANCE_ENGINE_AVAILABLE:
        logger.debug(
            "onex_change_control.scripts.contract_compliance_check unavailable; "
            "inert-check demotion skipped locally (hosted gate still enforces it)"
        )
        return False
    return bool(_occ_is_inert_check(check_value))


def _run_check_test_exists(
    check_value: str | dict[str, str], workspace: Path
) -> CheckResult:
    """Check if test files exist matching the pattern."""
    pattern = str(check_value)
    # Ensure we look for test files
    if not pattern.endswith("*"):
        search = f"{pattern.rstrip('/')}/**/test_*.py"
    else:
        search = pattern

    matches = (
        list(workspace.glob(search))
        if not Path(search).is_absolute()
        else list(Path("/").glob(search.lstrip("/")))
    )
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


def _run_check_test_passes(
    check_value: str | dict[str, str], workspace: Path
) -> CheckResult:
    """Run the check_value as a command and check exit code.

    <TICKET>: investigated unifying this with the hosted ``test_passes``
    semantics (poll ``gh pr checks`` for CI green, ignoring check_value) and
    found the real corpus contradicts that: many onex_change_control
    contracts author ``test_passes`` with a real command (``npm run test``,
    ``uv run pytest ...``) expecting it to EXECUTE. Hosted's gh-poll
    semantics only make sense post-PR, once CI has already run; locally
    (pre-PR, no CI yet) running the command directly is the only thing that
    can be checked. This divergence is intentional and lifecycle-driven, not
    a defect -- left unchanged.
    """
    cmd = str(check_value)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            check=False,
            cwd=workspace,
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


def _run_check_file_exists(
    check_value: str | dict[str, str], workspace: Path
) -> CheckResult:
    """Check if files matching a glob pattern exist."""
    pattern = str(check_value)
    p = Path(pattern)
    base = workspace / p.parent if p.parent != Path() else workspace
    matches = (
        list(base.glob(p.name))
        if "*" not in str(p.parent)
        else list(workspace.glob(pattern))
    )
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


def _run_check_grep(check_value: str | dict[str, str], workspace: Path) -> CheckResult:
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
            check=False,
            cwd=workspace,
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


def _run_check_command(
    check_value: str | dict[str, str], workspace: Path
) -> CheckResult:
    """Run an arbitrary command and check exit code."""
    cmd = str(check_value)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            check=False,
            cwd=workspace,
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


def _run_check_endpoint(
    check_value: str | dict[str, str], _workspace: Path
) -> CheckResult:
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
    workspace: Path | str | None = None,
) -> EvidenceRunResult:
    """Run all DoD evidence checks and produce structured results.

    Args:
        evidence_items: List of dod_evidence item dicts from the contract,
            each with keys: id, description, checks (list of {check_type, check_value}),
            and optionally status.
        workspace: Product checkout the checks run against. Defaults to CWD
            (matching the hosted Contract Compliance gate's own
            ``Path.cwd()`` fallback when ``--workspace`` is omitted) --
            callers that know the real product root (e.g. dod_sweep,
            epic_team) should pass it explicitly rather than rely on
            whatever directory the caller happened to be in when it
            invoked this function. <TICKET>: previously every check ran
            with no cwd binding at all (ambient-CWD execution) -- the same
            class of defect a prior fix closed on the hosted side.

    Returns:
        EvidenceRunResult with aggregate counts and per-item details.

    """
    resolved_workspace = Path(workspace).resolve() if workspace else Path.cwd()
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
            cr = runner(check_value, resolved_workspace)
            cr.duration_ms = (time.monotonic() - start) * 1000

            if is_inert_check(check_value):
                # <TICKET> parity with the hosted demotion rule: a check
                # that can only observe the OCC receipt/contract store
                # proves nothing about this product, whatever its raw result
                # was. Never let it launder as "verified".
                cr.status = "skipped"
                cr.message = f"INERT (reads OCC store, not the product): {cr.message}"

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
            check=False,
        )
        if sha_result.returncode == 0:
            sha = sha_result.stdout.strip()

        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=5,
            check=False,
        )
        if branch_result.returncode == 0:
            branch = branch_result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return sha, branch


def resolve_evidence_output_dir(ticket_id: str, working_dir: str) -> Path:
    """Resolve the directory the DoD receipt is written to.

    This is the single source of truth for the receipt's default location so
    the writer (``write_evidence_receipt``) and the reader
    (``pre_tool_use_dod_completion_guard.sh``) agree on one absolute path
    (Enforcement Map F7 round-trip, <TICKET>).

    Precedence mirrors the canonical ``node_dod_verify`` resolver:

    1. ``resolve_evidence_root()`` (<TICKET>) → ``$OMNI_HOME/onex_change_control/
       evidence/<ticket_id>``. This is the primary path: the core resolver reads
       ``OMNI_HOME`` fail-fast and returns the same location the legacy
       ``ONEX_EVIDENCE_ROOT`` env var pointed at, so the receipt still lands
       exactly where the completion guard reads
       (``$ONEX_EVIDENCE_ROOT/<ticket>/dod_report.json``).
    2. ``OMNI_HOME`` unset (resolver raises ``KeyError``) — or the resolver is
       unavailable on an older core — → ``<working_dir>/.evidence/<ticket_id>``
       (local-run default; the guard is fail-open / INACTIVE in that case).

    Args:
        ticket_id: The ticket identifier (e.g., "<TICKET>").
        working_dir: Working directory used for the local-run ``.evidence`` default.

    Returns:
        The directory (not the file) the ``dod_report.json`` receipt is written to.
    """
    if resolve_evidence_root is not None:
        try:
            return resolve_evidence_root() / ticket_id
        except KeyError:
            # OMNI_HOME unset → local-run fallback under the working directory.
            pass
    return Path(working_dir) / ".evidence" / ticket_id


def write_evidence_receipt(
    ticket_id: str,
    contract_path: str,
    run_result: EvidenceRunResult,
    working_dir: str | None = None,
    output_dir: str | None = None,
    *,
    policy_mode: str = "advisory",
    emit: bool = True,
) -> Path:
    """Write an evidence receipt JSON file and emit a dod.verify.completed event.

    Args:
        ticket_id: The ticket identifier (e.g., "<TICKET>").
        contract_path: Path to the contract YAML that was checked.
        run_result: The results from run_dod_evidence().
        working_dir: Working directory for git info (defaults to cwd).
        output_dir: Base directory for evidence output. When omitted, the
            default is resolved by ``resolve_evidence_output_dir`` so the
            receipt lands where ``pre_tool_use_dod_completion_guard.sh`` reads
            it (round-trip alignment, <TICKET> / Enforcement Map F7):
            ``$OMNI_HOME/onex_change_control/evidence/<ticket_id>`` via the
            ``resolve_evidence_root`` core resolver (<TICKET>), else
            ``<working_dir>/.evidence/<ticket_id>`` when ``OMNI_HOME`` is unset.
        policy_mode: DoD enforcement policy (advisory/soft/hard). Forwarded
            to the emitted event. Defaults to "advisory".
        emit: Whether to emit a dod.verify.completed Kafka event after writing
            the receipt. Defaults to True. Set to False in tests or offline
            scenarios where the emit daemon is unavailable.

    Returns:
        Path to the written receipt file.

    """
    if working_dir is None:
        working_dir = str(Path.cwd())

    if output_dir is None:
        output_dir = str(resolve_evidence_output_dir(ticket_id, working_dir))

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    git_sha, branch = _get_git_info(working_dir)

    overall_status = "verified" if run_result.failed == 0 else "failed"
    run_timestamp = datetime.now(tz=UTC)

    _used_model = False
    if _CORE_AVAILABLE and git_sha and len(git_sha) >= 7:
        status_enum = (
            EnumReceiptStatus.PASS
            if overall_status == "verified"
            else EnumReceiptStatus.FAIL
        )
        try:
            receipt_obj = ModelDodReceipt(
                schema_version="1.0.0",
                ticket_id=ticket_id,
                evidence_item_id="dod-run",
                check_type="command",
                check_value=contract_path,
                status=status_enum,
                run_timestamp=run_timestamp,
                commit_sha=git_sha[:40],
                runner="dod-evidence-runner",
                verifier="dod-evidence-runner-ci",
                probe_command=f"run_dod_evidence({contract_path!r})",
                probe_stdout=json.dumps(asdict(run_result), default=str)[:4096],
                branch=branch or None,
                working_dir=working_dir,
            )
            receipt_data = receipt_obj.model_dump(mode="json")
            _used_model = True
        except Exception:  # noqa: BLE001
            pass  # Fall through to dict path when core lacks new fields (pre-<TICKET> release)
    if not _used_model:
        # Fallback when omnibase_core unavailable or no valid git SHA
        receipt_data = {
            "schema_version": "1.0.0",
            "ticket_id": ticket_id,
            "evidence_item_id": "dod-run",
            "check_type": "command",
            "check_value": contract_path,
            "status": "PASS" if overall_status == "verified" else "FAIL",
            "run_timestamp": run_timestamp.isoformat(),
            "commit_sha": (
                git_sha[:40] if git_sha and len(git_sha) >= 7 else "0000000"
            ),
            "runner": "dod-evidence-runner",
            "verifier": "dod-evidence-runner-ci",
            "probe_command": f"run_dod_evidence({contract_path!r})",
            "probe_stdout": json.dumps(asdict(run_result), default=str)[:4096],
            "branch": branch or None,
            "working_dir": working_dir,
        }

    receipt_path = Path(output_dir) / "dod_report.json"
    receipt_path.write_text(json.dumps(receipt_data, indent=2, default=str))

    # Emit Kafka event after writing the local receipt. Non-blocking: emission
    # failures do not affect the receipt file or the return value.
    if emit:
        try:
            emit_dod_verify_completed(ticket_id, run_result, policy_mode=policy_mode)
        except Exception as e:
            logger.warning("Emission error in write_evidence_receipt (ignored): %s", e)

    return receipt_path


def _get_emit_event() -> Callable[..., bool] | None:
    """Lazily import emit_event from the emit client wrapper.

    The emit client wrapper lives in the hooks/lib directory. Since the
    evidence runner is a standalone library under skills/_lib/, we need
    to locate the wrapper via known relative paths or PYTHONPATH.

    Returns:
        The emit_event callable, or None if import fails.
    """
    try:
        # Try direct import first (works when PYTHONPATH includes hooks/lib)
        from emit_client_wrapper import emit_event

        return emit_event
    except ImportError:
        pass

    # Fallback: resolve via known directory structure
    # dod_evidence_runner.py -> skills/_lib/dod-evidence-runner/
    # emit_client_wrapper.py -> hooks/lib/
    try:
        runner_dir = Path(__file__).resolve().parent
        hooks_lib = runner_dir.parent.parent.parent / "hooks" / "lib"
        if hooks_lib.is_dir():
            hooks_lib_str = str(hooks_lib)
            sys.path.insert(0, hooks_lib_str)
            try:
                from emit_client_wrapper import emit_event

                return emit_event
            finally:
                try:
                    sys.path.remove(hooks_lib_str)
                except ValueError:
                    pass
    except Exception as e:
        logger.debug("Failed to import emit_client_wrapper: %s", e)

    return None


def emit_dod_verify_completed(
    ticket_id: str,
    run_result: EvidenceRunResult,
    *,
    policy_mode: str = "advisory",
    run_id: str | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
) -> bool:
    """Emit a dod.verify.completed event to Kafka.

    Non-blocking and failure-tolerant. Returns True on success, False on
    failure. Local JSON receipt writing is NOT affected by emission failures.

    Args:
        ticket_id: Linear ticket identifier (e.g. "<TICKET>").
        run_result: The EvidenceRunResult from run_dod_evidence().
        policy_mode: DoD enforcement policy (advisory/soft/hard).
        run_id: Unique run identifier. Generated if not provided.
        session_id: Claude Code session ID. Read from env if not provided.
        correlation_id: Correlation ID. Read from env if not provided.

    Returns:
        True if event was successfully emitted, False otherwise.
    """
    emit_event = _get_emit_event()
    if emit_event is None:
        logger.debug("emit_event not available, skipping dod.verify.completed emission")
        return False

    if run_id is None:
        run_id = str(uuid.uuid4())
    if session_id is None:
        from plugins.onex.hooks.lib.session_id import (
            resolve_session_id,  # noqa: PLC0415
        )

        session_id = resolve_session_id(default="")
    if correlation_id is None:
        correlation_id = os.environ.get("OMNICLAUDE_CORRELATION_ID", "")

    overall_pass = run_result.failed == 0

    payload: dict[str, object] = {
        "ticket_id": ticket_id,
        "run_id": run_id,
        "session_id": session_id,
        "correlation_id": correlation_id,
        "total_checks": run_result.total,
        "passed_checks": run_result.verified,
        "failed_checks": run_result.failed,
        "skipped_checks": run_result.skipped,
        "overall_pass": overall_pass,
        "policy_mode": policy_mode,
        "evidence_items": [asdict(d) for d in run_result.details],
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }

    try:
        return bool(emit_event("dod.verify.completed", payload))
    except Exception as e:
        logger.warning("Failed to emit dod.verify.completed: %s", e)
        return False
