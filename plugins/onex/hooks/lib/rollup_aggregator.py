# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PR Validation Rollup Aggregator -- computes VTS from pipeline state.

Aggregates validation tax fields from pipeline phase checkpoints and state,
computes the Validation Tax Score (VTS) and VTS-per-kLoC, and returns a
rollup dict suitable for emission on the ``pr.validation.rollup`` event type.

The VTS formula and weights are inlined from omnibase_spi to avoid a runtime
dependency on omnibase_spi in the hooks environment.

Related Tickets:
    - OMN-3930: PR validation rollup topic
    - OMN-3932: Build rollup aggregator

.. versionadded:: 0.3.1
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VTS Constants (inlined from omnibase_spi/contracts/measurement/vts.py)
# ---------------------------------------------------------------------------

DEFAULT_VTS_WEIGHTS: dict[str, float] = {
    "blocking_failures": 10.0,
    "warn_findings": 1.0,
    "reruns": 5.0,
    "validator_runtime_s": 0.5,
    "human_escalations": 20.0,
    "autofix_successes": -3.0,
}


def _compute_vts(tax_fields: dict[str, float | int]) -> float:
    """Compute the Validation Tax Score from tax fields.

    VTS = sum(weight_i * field_i) for each field in DEFAULT_VTS_WEIGHTS.
    Lower is better; negative contributions (autofix_successes) reduce cost.

    Args:
        tax_fields: Dict mapping field names to numeric values.

    Returns:
        The computed VTS (floored at 0.0).
    """
    score = 0.0
    for field_name, weight in DEFAULT_VTS_WEIGHTS.items():
        value = tax_fields.get(field_name, 0)
        score += weight * float(value)
    return max(0.0, score)


# ---------------------------------------------------------------------------
# Tax Field Extraction
# ---------------------------------------------------------------------------


def _extract_blocking_failures(state: dict[str, Any]) -> tuple[int, bool]:
    """Extract blocking failure count from local_review artifacts.

    Returns:
        Tuple of (count, was_available).
    """
    local_review = state.get("phases", {}).get("local_review", {})
    artifacts = local_review.get("artifacts", {})

    # Look for hostile_reviewer findings with severity CRITICAL/MAJOR
    findings = artifacts.get("findings", [])
    if isinstance(findings, list):
        count = sum(
            1
            for f in findings
            if isinstance(f, dict)
            and f.get("severity", "").upper() in ("CRITICAL", "MAJOR")
        )
        return (count, True)

    # Fallback: check blocking_issues count from result
    blocking = artifacts.get("blocking_issues", None)
    if blocking is not None:
        return (int(blocking), True)

    return (0, False)


def _extract_warn_findings(state: dict[str, Any]) -> tuple[int, bool]:
    """Extract warning finding count from local_review artifacts."""
    local_review = state.get("phases", {}).get("local_review", {})
    artifacts = local_review.get("artifacts", {})

    findings = artifacts.get("findings", [])
    if isinstance(findings, list):
        count = sum(
            1
            for f in findings
            if isinstance(f, dict) and f.get("severity", "").upper() in ("MINOR", "NIT")
        )
        return (count, True)

    nit_count = artifacts.get("nit_count", None)
    if nit_count is not None:
        return (int(nit_count), True)

    return (0, False)


def _extract_reruns(state: dict[str, Any]) -> int:
    """Extract total rerun count from local_review and ci_watch phases."""
    reruns = 0

    for phase_name in ("local_review", "ci_watch"):
        phase = state.get("phases", {}).get(phase_name, {})
        artifacts = phase.get("artifacts", {})
        iteration_count = artifacts.get(
            "iteration_count", artifacts.get("iterations", 1)
        )
        if isinstance(iteration_count, int) and iteration_count > 1:
            reruns += iteration_count - 1

    ci_watch = state.get("phases", {}).get("ci_watch", {})
    ci_artifacts = ci_watch.get("artifacts", {})
    ci_fix_cycles = ci_artifacts.get("ci_fix_cycles_used", 0)
    if isinstance(ci_fix_cycles, int) and ci_fix_cycles > 0:
        reruns += ci_fix_cycles

    return reruns


def _extract_validator_runtime_ms(state: dict[str, Any]) -> int:
    """Extract total validator runtime from local_review and ci_watch phases."""
    total_ms = 0

    for phase_name in ("local_review", "ci_watch"):
        phase = state.get("phases", {}).get(phase_name, {})
        artifacts = phase.get("artifacts", {})
        elapsed = artifacts.get("phase_elapsed_ms", 0)
        if isinstance(elapsed, (int, float)):
            total_ms += int(elapsed)

    return total_ms


def _extract_human_escalations(
    state: dict[str, Any],
    checkpoints: list[dict[str, Any]],
) -> int:
    """Count phase checkpoints with outcome 'blocked' and block_kind 'blocked_human_gate'."""
    count = 0

    # Check checkpoints list
    for cp in checkpoints:
        if (
            isinstance(cp, dict)
            and cp.get("outcome") == "blocked"
            and cp.get("block_kind") == "blocked_human_gate"
        ):
            count += 1

    # Also check phase data in state
    for phase_data in state.get("phases", {}).values():
        if (
            isinstance(phase_data, dict)
            and phase_data.get("block_kind") == "blocked_human_gate"
        ):
            count += 1

    return count


def _extract_autofix_successes(state: dict[str, Any]) -> tuple[int, bool]:
    """Extract autofix success count from ci_watch artifacts."""
    ci_watch = state.get("phases", {}).get("ci_watch", {})
    artifacts = ci_watch.get("artifacts", {})

    fixes = artifacts.get("preexisting_fixes_dispatched", None)
    if fixes is not None and isinstance(fixes, int):
        return (fixes, True)

    return (0, False)


def _extract_files_and_lines(state: dict[str, Any]) -> tuple[int, int]:
    """Extract files_changed and lines_changed from create_pr artifacts."""
    create_pr = state.get("phases", {}).get("create_pr", {})
    artifacts = create_pr.get("artifacts", {})

    files = artifacts.get("files_changed", 0)
    if isinstance(files, list):
        files = len(files)
    elif not isinstance(files, int):
        files = 0

    lines = artifacts.get("lines_changed", 0)
    if not isinstance(lines, int):
        lines = 0

    return (files, lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_pr_validation_rollup(
    state: dict[str, Any],
    checkpoints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a PR validation rollup dict from pipeline state and checkpoints.

    Extracts validation tax fields, computes VTS and VTS-per-kLoC, and
    returns a dict suitable for emission via ``emit_event("pr.validation.rollup", ...)``.

    Args:
        state: The full pipeline state dict (from state.yaml).
        checkpoints: List of phase checkpoint dicts collected during the run.

    Returns:
        Rollup dict with all tax fields, VTS, and metadata.
    """
    missing_fields: list[str] = []

    # Attribution
    attribution = state.get("attribution", {})
    model_id = attribution.get("model_id", "unknown")
    producer_kind = attribution.get("producer_kind", "unknown")

    # PR identity
    pr_url = state.get("pr_url", "")
    pr_number = state.get("pr_number", 0)
    repo_full_name = state.get("repo_full_name", "")
    run_id = state.get("run_id", "")
    ticket_id = state.get("ticket_id", "")

    # Extract tax fields
    blocking_failures, bf_available = _extract_blocking_failures(state)
    if not bf_available:
        missing_fields.append("blocking_failures")

    warn_findings, wf_available = _extract_warn_findings(state)
    if not wf_available:
        missing_fields.append("warn_findings")

    reruns = _extract_reruns(state)

    validator_runtime_ms = _extract_validator_runtime_ms(state)
    # Convert ms to seconds for VTS formula
    validator_runtime_s = validator_runtime_ms / 1000.0

    human_escalations = _extract_human_escalations(state, checkpoints)

    autofix_successes, af_available = _extract_autofix_successes(state)
    if not af_available:
        missing_fields.append("autofix_successes")

    # time_to_green_ms: total_elapsed_ms at terminal phase, 0 for partial
    time_to_green_ms = state.get("total_elapsed_ms", 0)
    if not isinstance(time_to_green_ms, (int, float)):
        time_to_green_ms = 0

    files_changed, lines_changed = _extract_files_and_lines(state)

    # Compute VTS
    tax_fields = {
        "blocking_failures": blocking_failures,
        "warn_findings": warn_findings,
        "reruns": reruns,
        "validator_runtime_s": validator_runtime_s,
        "human_escalations": human_escalations,
        "autofix_successes": autofix_successes,
    }
    vts = _compute_vts(tax_fields)

    # VTS per kLoC
    kloc = max(1, lines_changed) / 1000.0
    vts_per_kloc = vts / kloc

    # Determine rollup status from terminal phase outcome
    auto_merge_phase = state.get("phases", {}).get("auto_merge", {})
    auto_merge_status = auto_merge_phase.get("artifacts", {}).get("status", "")
    if auto_merge_status in ("merged_via_auto", "merged"):
        rollup_status = "final"
    else:
        rollup_status = "partial"

    return {
        "metric_version": "v1",
        "run_id": run_id,
        "ticket_id": ticket_id,
        "model_id": model_id,
        "producer_kind": producer_kind,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "repo_full_name": repo_full_name,
        "rollup_status": rollup_status,
        "tax": {
            "blocking_failures": blocking_failures,
            "warn_findings": warn_findings,
            "reruns": reruns,
            "validator_runtime_ms": validator_runtime_ms,
            "human_escalations": human_escalations,
            "autofix_successes": autofix_successes,
            "time_to_green_ms": int(time_to_green_ms),
            "files_changed": files_changed,
            "lines_changed": lines_changed,
        },
        "vts": round(vts, 4),
        "vts_per_kloc": round(vts_per_kloc, 4),
        "extensions": {
            "missing_fields": missing_fields,
            "vts_weights": DEFAULT_VTS_WEIGHTS,
        },
    }


__all__ = [
    "build_pr_validation_rollup",
    "DEFAULT_VTS_WEIGHTS",
]
