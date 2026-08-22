#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""SubagentStop secret-leak guard [OMN-15062].

Applies the existing secret_redactor.py pattern set to the surface that
actually leaked on 2026-07-24: an agent's own final report text. Two
credential-investigation subagents printed the exact secret they were sent
to investigate into their final assistant message, verbatim, under an
explicit prompt-level "never print the credential" instruction -- one
rationalized doing so inline. A prompt prohibition alone does not hold
(memory feedback_a_rule_is_not_a_mechanism); this module is the mechanism.

Mechanism, and its real limits:
    Claude Code's SubagentStop hook fires after a Task-spawned subagent
    produces its final assistant message, but before that turn is accepted
    as complete and the message is returned to the caller (same hook point
    subagent_stop_claim_verifier.py already uses for OMN-9086). A
    ``decision: "block"`` verdict forces the subagent to revise its final
    message before the turn completes -- this blocks PROPAGATION of the
    leaked text to the orchestrator's context and to anything the
    orchestrator does with that report afterward (ledger append, PR body,
    Linear comment, TaskUpdate).

    It does NOT retroactively scrub the raw transcript JSONL Claude Code
    has already appended to disk for the blocked attempt -- there is no
    hook surface in this harness that rewrites an already-emitted
    transcript entry. It also does NOT cover the harness's own
    background-workflow ``.output``/``workflow_result.json`` files -- those
    are written by the outer Claude Code harness itself, not by any code in
    this repo, and are outside what a plugin hook can intercept. See the
    OMN-15062 PR body for the full surface-coverage matrix.

Fail-safe posture (deliberate divergence from this repo's general
"hooks never block Claude Code" philosophy in CLAUDE.md "Fail-Fast
Design"): that philosophy exists for *availability* -- a stalled hook must
never freeze the UI. This hook is a *security* control, where the failure
mode that matters is "did a secret get through," not "did the hook finish
fast." Concretely:
    - No text extracted (nothing to scan): ALLOW. There is nothing to have
      leaked via this guard, and blocking here would be a spurious,
      unexplainable stall on every ordinary subagent turn.
    - Text extracted but the scan itself raises: BLOCK. An error mid-scan
      means we cannot prove the text is clean; passing it through "because
      the checker broke" is exactly the failure mode this ticket exists to
      close.
    - Text extracted, scan completes, secrets found: BLOCK.
    - Text extracted, scan completes, no secrets found: ALLOW.

The hook's own output (additionalContext) NEVER echoes the matched secret,
the redacted message, or the raw message -- only a verdict, a match count,
and a generic instruction. additionalContext becomes part of the transcript
too, so it must be safe to emit unconditionally.

Refs: OMN-15062.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from extract_last_assistant_message_utils import _extract_last_assistant_message
from secret_redactor import redact_secrets_with_count


class EnumSecretGuardVerdict(StrEnum):
    """Decision emitted by the SubagentStop secret-leak guard."""

    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True)
class ModelSecretGuardResult:
    """Result of scanning a SubagentStop event's final message for secrets.

    Deliberately carries no secret material -- only a verdict, a match
    count, and a machine-readable reason code safe to log or echo back.
    """

    verdict: EnumSecretGuardVerdict
    redacted_count: int
    reason: str


def scan_stop_event(stop_event: dict[str, Any]) -> ModelSecretGuardResult:
    """Scan a SubagentStop event's final assistant message for secrets.

    See module docstring for the fail-safe branching this function
    implements. Never returns or logs the matched secret text, the
    redacted message, or the raw message body.
    """

    try:
        message = _extract_last_assistant_message(stop_event)
    except Exception:  # noqa: BLE001 - extraction failure, not a scan failure
        # Nothing was extracted, so nothing could have leaked via this
        # guard -- allow, same as the "no message" branch below. This is
        # distinct from the "scan raised" fail-safe branch, which requires
        # having text in hand that we then failed to prove clean.
        return ModelSecretGuardResult(
            verdict=EnumSecretGuardVerdict.ALLOW,
            redacted_count=0,
            reason="extraction_error_nothing_to_scan",
        )

    if not message:
        return ModelSecretGuardResult(
            verdict=EnumSecretGuardVerdict.ALLOW,
            redacted_count=0,
            reason="no_message_extracted",
        )

    try:
        result = redact_secrets_with_count(message)
    except Exception:  # noqa: BLE001 - fail SAFE: assume unsafe, never pass through
        return ModelSecretGuardResult(
            verdict=EnumSecretGuardVerdict.BLOCK,
            redacted_count=-1,
            reason="scan_error_fail_safe",
        )

    if result.redacted_count > 0:
        return ModelSecretGuardResult(
            verdict=EnumSecretGuardVerdict.BLOCK,
            redacted_count=result.redacted_count,
            reason="secret_pattern_matched",
        )

    return ModelSecretGuardResult(
        verdict=EnumSecretGuardVerdict.ALLOW,
        redacted_count=0,
        reason="clean",
    )


def _hook_output(result: ModelSecretGuardResult) -> dict[str, Any]:
    """Render a verdict into the Claude Code hookSpecificOutput envelope.

    IMPORTANT: never place matched secret text, the redacted message, or
    the raw scanned message into additionalContext -- it becomes part of
    the transcript itself, which is exactly the surface this guard exists
    to protect.

    OMN-15213: the ALLOW path no longer carries additionalContext. It used
    to emit "secret-leak guard: clean (matches=0)" on EVERY ordinary
    subagent turn, which put a hook-authored message at the end of the
    turn for the agent to reply to -- and that short reply became the
    captured final return, clobbering the real report 1-2 turns earlier
    (reproduced 3/5 in wf_00bcb6a9-f0b, 3/3 in wf_1923e07f-b65, both on
    2026-07-26, the day after this guard was registered). A guard that is
    not blocking has nothing the agent needs to act on, so it says
    nothing. The BLOCK path keeps its context: there a follow-up turn is
    exactly the intent.
    """

    envelope: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "decision": result.verdict.value,
        }
    }
    if result.verdict is EnumSecretGuardVerdict.BLOCK:
        envelope["hookSpecificOutput"]["additionalContext"] = (
            f"SubagentStop secret-leak guard: {result.reason} "
            f"(matches={result.redacted_count}). "
            "Final message appears to contain a credential/secret. "
            "Redact it (describe it, e.g. 'the Postgres password', never "
            "quote the value) and finish again."
        )
    return envelope


def _cli_main() -> int:
    """Read SubagentStop stdin JSON, scan, print hook output.

    Exit codes: 0 = allow, 2 = block (mirrors subagent_stop_claim_verifier.py).
    """

    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        # Malformed stdin: no text in hand, nothing scanned -- this is the
        # "nothing to scan" branch, not the "scan raised" fail-safe branch.
        event = {}

    result = scan_stop_event(event)
    sys.stdout.write(json.dumps(_hook_output(result)))
    sys.stdout.write("\n")
    return 2 if result.verdict is EnumSecretGuardVerdict.BLOCK else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the shell wrapper
    raise SystemExit(_cli_main())
