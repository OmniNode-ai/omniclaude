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
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from skip_token_surface_guard import find_unauthorized_skip_tokens

# Degrade reasons that indicate genuine verification (not fail-open). Used by
# verify_stop() to decide whether an ALLOW verdict should carry a
# "verified_fail_open" suffix propagating the degraded upstream reason.
_CLEAN_GH_REASONS: frozenset[str] = frozenset({"state_match", "not_pr_ship"})
_CLEAN_LINEAR_REASONS: frozenset[str] = frozenset({"state_match", "no_linear_claim"})


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


class ModelExtractionResult(BaseModel):
    """Outcome of pulling a json-report block from a free-form message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    found: bool
    parsed: ModelWorkerReport | None = None
    error: str | None = None


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

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: EnumVerdict
    reason: str
    report: ModelWorkerReport | None = None
    diff: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2b. Report extraction
# ---------------------------------------------------------------------------

_JSON_REPORT_FENCE_RE = re.compile(
    # Accept both LF and CRLF around the fence. `[^\S\r\n]*` consumes trailing
    # spaces/tabs on the opening line without eating the line terminator.
    r"```json-report[^\S\r\n]*\r?\n(?P<body>.*?)\r?\n```",
    re.DOTALL,
)


def extract_report(message: str) -> ModelExtractionResult:
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
        return ModelExtractionResult(found=False)

    body = matches[-1].group("body").strip()
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        return ModelExtractionResult(found=True, error=f"json_decode: {exc}")

    try:
        parsed = ModelWorkerReport.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or TypeError
        return ModelExtractionResult(found=True, error=f"schema: {exc}")

    return ModelExtractionResult(found=True, parsed=parsed)


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


def verify_schema_only(message: str) -> ModelExtractionResult:
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

    skip_token_findings = find_unauthorized_skip_tokens(
        message,
        surface="SubagentStop final assistant message",
    )
    if skip_token_findings:
        return ModelSubagentStopReport(
            decision=EnumVerdict.BLOCK,
            reason="unauthorized_skip_token_surface",
            diff={
                "skip_tokens": [
                    {"surface": finding.surface, "path": finding.path}
                    for finding in skip_token_findings
                ]
            },
        )

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
    degrade_reasons: list[str] = []

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
    if gh_result.reason not in _CLEAN_GH_REASONS:
        # fail-open (gh_not_installed, rate_limited, gh_error, …) — record so
        # the caller surfaces it in additionalContext.
        degrade_reasons.append(f"github:{gh_result.reason}")

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
    if linear_result.reason not in _CLEAN_LINEAR_REASONS:
        degrade_reasons.append(f"linear:{linear_result.reason}")

    reason = (
        "verified"
        if not degrade_reasons
        else f"verified_fail_open: {'; '.join(degrade_reasons)}"
    )
    return ModelSubagentStopReport(
        decision=EnumVerdict.ALLOW,
        reason=reason,
        report=report,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint used by subagent_stop_claim_verifier.sh
# ---------------------------------------------------------------------------


def _text_from_content(content: Any) -> str:
    """Normalize Claude message content into plain assistant text."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return ""


def _assistant_text_from_message_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    if entry.get("role") != "assistant":
        return ""
    return _text_from_content(entry.get("content"))


def _assistant_text_from_transcript_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""

    message = entry.get("message")
    if isinstance(message, dict):
        role = message.get("role")
        entry_type = entry.get("type")
        if role == "assistant" or entry_type == "assistant":
            return _text_from_content(message.get("content"))

    if entry.get("role") == "assistant":
        return _text_from_content(entry.get("content"))

    return ""


def _extract_last_assistant_message_from_jsonl(transcript: str) -> str | None:
    """Return last assistant text from a JSONL transcript.

    ``None`` means the transcript was malformed and must fail closed. An empty
    string means it parsed but contained no usable assistant entry.
    """

    last_message = ""
    saw_line = False
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        saw_line = True
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return None
        text = _assistant_text_from_transcript_entry(entry)
        if text:
            last_message = text
    return last_message if saw_line else ""


def _looks_like_jsonl(transcript: str) -> bool:
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if line:
            return line.startswith(("{", "["))
    return False


def _extract_last_assistant_message_from_path(raw_path: Any) -> str | None:
    """Read a JSONL transcript path and return its last assistant message.

    Returns ``None`` for unreadable or malformed transcripts so callers block
    instead of accepting unrelated free text.
    """

    if not isinstance(raw_path, str) or not raw_path:
        return ""
    try:
        transcript = Path(raw_path).read_text(encoding="utf-8")
    except OSError:
        return None
    return _extract_last_assistant_message_from_jsonl(transcript)


def _extract_last_assistant_message(stop_event: dict[str, Any]) -> str:
    """Pull the final assistant message text out of a SubagentStop event.

    Claude Code's SubagentStop hook passes the subagent's transcript in a
    handful of equivalent shapes across versions. We try them in order and
    fall back to an empty string — the verifier treats missing text as
    "missing json-report block" (block).
    """

    # Shape 1: direct field
    for key in (
        "last_assistant_message",
        "final_message",
        "assistant_message",
        "last_message",
    ):
        val = stop_event.get(key)
        if isinstance(val, str) and val:
            return val

    # Shape 2: messages array — last assistant content
    messages = stop_event.get("messages")
    if isinstance(messages, list):
        for entry in reversed(messages):
            if not isinstance(entry, dict):
                continue
            text = _assistant_text_from_message_entry(entry)
            if text:
                return text

    # Shape 3: Claude Code transcript JSONL path - last assistant entry only.
    for key in ("agent_transcript_path", "transcript_path"):
        text = _extract_last_assistant_message_from_path(stop_event.get(key))
        if text is None:
            return ""
        if text:
            return text

    # Shape 4: transcript blob. JSONL blobs are parsed assistant-only; legacy
    # free-form blobs fall back to the whole string for backwards compatibility.
    transcript = stop_event.get("transcript")
    if isinstance(transcript, str) and transcript:
        jsonl_message = _extract_last_assistant_message_from_jsonl(transcript)
        if jsonl_message is None:
            if _looks_like_jsonl(transcript):
                return ""
            return transcript
        if jsonl_message:
            return jsonl_message
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
