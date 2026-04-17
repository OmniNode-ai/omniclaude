# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""SubagentStop agent-claim verifier [OMN-9086].

Blocks SubagentStop when the agent's final message is missing a structured
``json-report`` block or when the report's claims fail ground-truth checks
against GitHub (PR state) and Linear (ticket state).

Sub-phases (plan Task 2, mini-epic):
    2a. Schema fallback — local minimal ``ModelWorkerReport`` until OMN-9063
        lands the canonical schema.
    2b. Report extraction — pull the ``json-report`` fenced block out of the
        free-form assistant message and parse it.
    2c. GitHub verification — for ``kind=pr_ship`` reports, compare claimed PR
        state against ``gh pr view --json state,mergedAt``.
    2d. Linear verification — for reports with ``ticket=OMN-XXXX``, compare
        claimed state against the Linear API. Auth failures and unreachable
        endpoints fail-open with warning friction per Task 8 semantics.
    2e. Hook wrapper — see ``scripts/subagent_stop_claim_verifier.sh``.

Refs:
    * OMN-9063 canonical ``ModelWorkerReport`` (fallback until it lands)
    * OMN-9055 ``node_evidence_bundle.resolve()`` integration (inline probes
      until that ticket ships)
    * OMN-9072 ``hookSpecificOutput.hookEventName`` requirement
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EnumWorkerReportKind(StrEnum):
    """Kinds of worker reports this verifier understands.

    TODO(OMN-9063): replace with the canonical enum once ``ModelWorkerReport``
    lands in omnibase_core.
    """

    PR_SHIP = "pr_ship"
    TICKET_UPDATE = "ticket_update"
    DIAGNOSIS = "diagnosis"
    RESEARCH = "research"


class ModelWorkerReportPR(BaseModel):
    """Nested PR claim inside a ``kind=pr_ship`` worker report."""

    model_config = ConfigDict(frozen=True, extra="allow")

    number: int
    state: str
    repo: str | None = None


class ModelWorkerReport(BaseModel):
    """Minimal local fallback for the OMN-9063 canonical schema.

    Covers only the fields Task 2 verification needs. Intentionally permissive
    (``extra='allow'``) so real agent reports with additional keys parse
    cleanly; swap for the canonical type once OMN-9063 ships.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    kind: EnumWorkerReportKind
    ticket: str | None = None
    pr: ModelWorkerReportPR | None = None
    linear: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExtractionResult:
    """Outcome of pulling a json-report block from a free-form message."""

    found: bool
    parsed: ModelWorkerReport | None
    error: str | None


class EnumVerdict(StrEnum):
    """Aggregate verdict produced by the verifier for a SubagentStop body."""

    ALLOW = "allow"
    BLOCK = "block"


class ModelSubagentStopReport(BaseModel):
    """Verifier verdict wrapping the parsed worker report plus explanation.

    Inventory check: the plan's Known Types Inventory lists
    ``ModelSubagentStopReport`` as new — it adds the verdict and reason,
    which ``ModelWorkerReport`` does not carry.
    """

    model_config = ConfigDict(frozen=True)

    decision: EnumVerdict
    reason: str
    report: ModelWorkerReport | None = None
    diff: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2b. Report extraction
# ---------------------------------------------------------------------------

_JSON_REPORT_FENCE_RE = re.compile(
    r"```json-report\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)


def extract_report(message: str) -> ExtractionResult:
    """Pull a ``json-report`` fenced block from ``message`` and parse it.

    Handles all four shapes the plan enumerates:

    * **absent** — no fence → ``found=False``
    * **present, valid** — single fence with parseable JSON → ``found=True``,
      ``parsed`` populated
    * **multiple fences** — the LAST fence wins (agents that retry a report
      typically append the corrected block)
    * **malformed JSON** — ``found=True``, ``parsed=None``, ``error`` set

    Non-empty ``message`` with no fence returns ``found=False`` — callers
    treat that as "missing report block" and block.
    """

    matches = list(_JSON_REPORT_FENCE_RE.finditer(message))
    if not matches:
        return ExtractionResult(found=False, parsed=None, error=None)

    body = matches[-1].group("body").strip()
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        return ExtractionResult(found=True, parsed=None, error=f"json_decode: {exc}")

    try:
        parsed = ModelWorkerReport.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or TypeError
        return ExtractionResult(found=True, parsed=None, error=f"schema: {exc}")

    return ExtractionResult(found=True, parsed=parsed, error=None)


# ---------------------------------------------------------------------------
# 2c. GitHub verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GhVerifyResult:
    """Structured outcome of a single ``gh pr view`` probe."""

    ok: bool
    actual_state: str | None
    reason: str


def verify_pr_claim(
    report: ModelWorkerReport,
    *,
    gh_runner: Any = None,
) -> GhVerifyResult:
    """Verify a ``kind=pr_ship`` report's PR claim via ``gh pr view``.

    ``gh_runner`` is an optional callable ``(args: list[str]) -> subprocess.CompletedProcess``
    for tests. Production uses ``subprocess.run`` with a short timeout. Non-pr_ship
    reports are a no-op pass.
    """

    if report.kind != EnumWorkerReportKind.PR_SHIP:
        return GhVerifyResult(ok=True, actual_state=None, reason="not_pr_ship")
    if report.pr is None:
        return GhVerifyResult(
            ok=False,
            actual_state=None,
            reason="pr_ship report missing 'pr' body",
        )

    args = ["gh", "pr", "view", str(report.pr.number), "--json", "state,mergedAt"]
    if report.pr.repo:
        args.extend(["--repo", report.pr.repo])

    runner = gh_runner if gh_runner is not None else _default_gh_runner
    try:
        proc = runner(args)
    except FileNotFoundError:
        return GhVerifyResult(ok=True, actual_state=None, reason="gh_not_installed")
    except Exception as exc:  # network, timeout
        return GhVerifyResult(ok=True, actual_state=None, reason=f"gh_error: {exc}")

    stderr = (proc.stderr or "").lower()
    if proc.returncode != 0:
        if "could not resolve" in stderr or "not found" in stderr:
            return GhVerifyResult(
                ok=False,
                actual_state=None,
                reason=f"pr_not_found: #{report.pr.number}",
            )
        if "rate limit" in stderr or "api rate" in stderr:
            return GhVerifyResult(ok=True, actual_state=None, reason="rate_limited")
        return GhVerifyResult(
            ok=False,
            actual_state=None,
            reason=f"gh_exit_{proc.returncode}: {stderr.strip()[:120]}",
        )

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return GhVerifyResult(
            ok=False,
            actual_state=None,
            reason="gh_output_not_json",
        )

    actual = str(payload.get("state", "")).upper() or None
    claimed = report.pr.state.upper()
    if actual != claimed:
        return GhVerifyResult(
            ok=False,
            actual_state=actual,
            reason=f"state_mismatch: claimed={claimed} actual={actual}",
        )
    return GhVerifyResult(ok=True, actual_state=actual, reason="state_match")


def _default_gh_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        args,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


# ---------------------------------------------------------------------------
# 2d. Linear verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LinearVerifyResult:
    """Outcome of a Linear ticket-state cross-reference."""

    ok: bool
    actual_state: str | None
    reason: str


def verify_linear_claim(
    report: ModelWorkerReport,
    *,
    linear_runner: Any = None,
) -> LinearVerifyResult:
    """Verify the report's Linear claim (if any) matches ticket state.

    ``linear_runner`` is an optional callable ``(ticket: str) -> dict`` returning
    a Linear issue payload (keys: ``state`` or ``status``). When omitted, this
    function fails open — no Linear transport is bundled with hooks; the actual
    integration goes through the MCP server which isn't reachable from inside
    the hook subprocess. Auth/unreachable errors fail open with a reason string
    callers surface as friction (Task 8 semantics).
    """

    claimed = _extract_claimed_linear_state(report)
    if claimed is None:
        return LinearVerifyResult(
            ok=True,
            actual_state=None,
            reason="no_linear_claim",
        )
    if report.ticket is None:
        return LinearVerifyResult(
            ok=False,
            actual_state=None,
            reason="linear claim present without ticket id",
        )

    if linear_runner is None:
        return LinearVerifyResult(
            ok=True,
            actual_state=None,
            reason="linear_unreachable_from_hook",
        )

    try:
        payload = linear_runner(report.ticket)
    except PermissionError as exc:
        return LinearVerifyResult(
            ok=True,
            actual_state=None,
            reason=f"linear_auth_failed: {exc}",
        )
    except Exception as exc:  # network, unexpected
        return LinearVerifyResult(
            ok=True,
            actual_state=None,
            reason=f"linear_error: {exc}",
        )

    actual = str(payload.get("state") or payload.get("status") or "")
    if not actual:
        return LinearVerifyResult(
            ok=True,
            actual_state=None,
            reason="linear_state_missing",
        )
    if actual.lower() != claimed.lower():
        return LinearVerifyResult(
            ok=False,
            actual_state=actual,
            reason=f"state_mismatch: claimed={claimed} actual={actual}",
        )
    return LinearVerifyResult(ok=True, actual_state=actual, reason="state_match")


def _extract_claimed_linear_state(report: ModelWorkerReport) -> str | None:
    linear = report.linear or {}
    for key in ("ticket_state", "state", "status"):
        val = linear.get(key)
        if isinstance(val, str) and val:
            return val
    return None


# ---------------------------------------------------------------------------
# 2a+2b+2c+2d entrypoints
# ---------------------------------------------------------------------------


def verify_schema_only(message: str) -> ExtractionResult:
    """Schema-only validation entrypoint (shared with Task 7).

    Does 2a+2b — extraction and local-schema parse — without 2c/2d network
    calls. Callers needing pure offline validation use this.
    """

    return extract_report(message)


def verify_stop(
    message: str,
    *,
    gh_runner: Any = None,
    linear_runner: Any = None,
) -> ModelSubagentStopReport:
    """Top-level verifier — extracts the report and runs 2c/2d ground-truth.

    Returns a ``ModelSubagentStopReport`` with ``decision=block`` when the
    report is missing, malformed, or any ground-truth check finds a mismatch.
    Network-error modes (rate limit, auth failure, endpoint unreachable) are
    fail-open per Task 8 semantics; ``reason`` still records why.
    """

    extraction = extract_report(message)
    if not extraction.found:
        return ModelSubagentStopReport(
            decision=EnumVerdict.BLOCK,
            reason="missing_json_report_block",
        )
    if extraction.parsed is None:
        return ModelSubagentStopReport(
            decision=EnumVerdict.BLOCK,
            reason=f"malformed_report: {extraction.error or 'unknown'}",
        )

    report = extraction.parsed
    diff: dict[str, Any] = {}

    # TODO(OMN-9055): delegate to node_evidence_bundle.resolve() once the
    # resolver lands so PR + Linear checks flow through the canonical pipeline.
    gh_result = verify_pr_claim(report, gh_runner=gh_runner)
    if not gh_result.ok:
        diff["pr"] = {
            "claimed": report.pr.state if report.pr else None,
            "actual": gh_result.actual_state,
            "reason": gh_result.reason,
        }
        return ModelSubagentStopReport(
            decision=EnumVerdict.BLOCK,
            reason=f"github_verification_failed: {gh_result.reason}",
            report=report,
            diff=diff,
        )

    linear_result = verify_linear_claim(report, linear_runner=linear_runner)
    if not linear_result.ok:
        diff["linear"] = {
            "claimed": _extract_claimed_linear_state(report),
            "actual": linear_result.actual_state,
            "reason": linear_result.reason,
        }
        return ModelSubagentStopReport(
            decision=EnumVerdict.BLOCK,
            reason=f"linear_verification_failed: {linear_result.reason}",
            report=report,
            diff=diff,
        )

    return ModelSubagentStopReport(
        decision=EnumVerdict.ALLOW,
        reason="verified",
        report=report,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint used by subagent_stop_claim_verifier.sh
# ---------------------------------------------------------------------------


def _extract_last_assistant_message(stop_event: dict[str, Any]) -> str:
    """Pull the final assistant message text out of a SubagentStop event.

    Claude Code's SubagentStop hook passes the subagent's transcript in a
    handful of equivalent shapes across versions. We try them in order and
    fall back to an empty string — the verifier treats missing text as
    "missing json-report block" (block).
    """

    # Shape 1: direct field
    for key in ("final_message", "assistant_message", "last_message"):
        val = stop_event.get(key)
        if isinstance(val, str) and val:
            return val

    # Shape 2: messages array — last assistant content
    messages = stop_event.get("messages")
    if isinstance(messages, list):
        for entry in reversed(messages):
            if not isinstance(entry, dict):
                continue
            if entry.get("role") != "assistant":
                continue
            content = entry.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                joined = "\n".join(p for p in parts if p)
                if joined:
                    return joined

    # Shape 3: transcript blob
    transcript = stop_event.get("transcript")
    if isinstance(transcript, str) and transcript:
        return transcript

    return ""


def _hook_output(verdict: ModelSubagentStopReport) -> dict[str, Any]:
    """Render a verdict into the Claude Code hookSpecificOutput envelope.

    Schema matches OMN-9072: ``hookSpecificOutput.hookEventName`` is required
    on every emission; ``decision`` is ``block`` or ``allow``;
    ``additionalContext`` carries the reason + structured diff so the user
    sees why on block.
    """

    context_parts = [f"SubagentStop verifier: {verdict.reason}"]
    if verdict.diff:
        context_parts.append(f"diff: {json.dumps(verdict.diff, sort_keys=True)}")
    return {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "decision": verdict.decision.value,
            "additionalContext": " | ".join(context_parts),
        }
    }


def _cli_main() -> int:
    """Read SubagentStop stdin JSON, run the verifier, print hook output.

    Exit codes:
        0 — decision=allow (stop is permitted)
        2 — decision=block (stop is blocked; Claude Code surfaces to user)
    """

    import sys as _sys

    raw = _sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {}

    message = _extract_last_assistant_message(event)
    verdict = verify_stop(message)
    _sys.stdout.write(json.dumps(_hook_output(verdict)))
    _sys.stdout.write("\n")
    return 2 if verdict.decision is EnumVerdict.BLOCK else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the shell wrapper
    raise SystemExit(_cli_main())
