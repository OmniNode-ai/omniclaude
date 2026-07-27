#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""SubagentStop report-contract guard [OMN-15213].

Mechanizes the golden-chain report contract (memory
``feedback_golden_chain_agent_report_contracts``) at the seam where a
subagent's final assistant text is captured and handed back to the
orchestrator. Until this module existed the contract was prompt-side
convention only, and it demonstrably did not hold: workflow run
``wf_00bcb6a9-f0b`` returned filler final text on 3 of 5 lanes and
``wf_1923e07f-b65`` on 3 of 3, while the durable artifacts those lanes
produced (ledger rows, tickets, PRs) were real. A rule with no call-site
mechanism has no force (memory ``feedback_a_rule_is_not_a_mechanism``);
this module is the call-site mechanism.

The defect (from the OMN-15213 ticket comments)
-----------------------------------------------
A ``SubagentStop`` hook notification fires at end-of-turn. The agent
replies to *that notification* with a short acknowledgement, and because
the captured return is the LAST assistant message, the acknowledgement
clobbers the real report sitting 1-2 turns earlier in the transcript.
Agents forced through a structured-output schema were immune (7/7 clean
returns across ``wf_e15874db-1a1`` / ``wf_814a0c42-fa3`` /
``wf_1a1c4c66-d41`` in the same session), which is why a schema-bound
(JSON) return is an unconditional PASS below.

Two changes ship together for OMN-15213 and only make sense as a pair:

1. This guard — the enforcement half. A final return matching the
   clobber signature is RED and blocks the subagent's turn, forcing it
   to re-emit the real report instead of being silently accepted.
2. The solicitation half — the previously-registered ``SubagentStop``
   secret-leak guard emitted ``additionalContext`` on its ALLOW path
   (i.e. on every ordinary subagent turn), which is exactly the
   end-of-turn notification an agent replies to. That path is now
   silent; see ``subagent_secret_leak_guard._hook_output``.

Contract, as implemented
------------------------
PASS requires one of:
  - a schema-bound return (the whole message parses as a JSON object or
    array), or
  - >= 2 distinct evidence classes cited, or
  - >= 1 evidence class AND a report of at least
    ``MIN_REPORT_CHARS`` characters.

Evidence classes are the concrete citations the report contract asks
for: ticket ids, PR/issue numbers or GitHub URLs, file paths, command or
fenced-output blocks, explicit verdict tokens, and commit SHAs. A
bare-completion phrase ("Done.", "Task complete.", ...) is RED
unconditionally — no length or evidence can rescue it, because that
exact shape is the clobber.

Deliberate non-goals: this is a *shape* contract, not a truth oracle. It
cannot tell a real report from a fluent fabrication; that is the
adversarial verifier's job (CLAUDE.md rule 3). What it does close is the
silent-acceptance path, where a lane that returned nothing verifiable
was scored the same as one that returned a full report.

Loop safety
-----------
Claude Code sets ``stop_hook_active`` on a SubagentStop payload when the
turn is already continuing because a stop hook blocked it. Blocking
again on that pass would wedge the lane in an unbounded
block/reply/block cycle, so the guard blocks at most once: on the
second pass the verdict stays RED but the decision is ``allow`` and a
durable RED record is written under
``$ONEX_STATE_DIR/hooks/report_contract_red/`` so the failure survives
as evidence rather than evaporating.

Fail posture
------------
Unlike the sibling secret-leak guard (a security control that blocks
when it cannot prove text clean), a missing/unreadable final message
here yields ALLOW with reason ``no_message_extracted``: the guard only
goes RED on positive evidence of the clobber signature. Blocking on
every transcript shape this repo has not seen would freeze ordinary
subagent turns across every OmniNode repo, and an unavailable transcript
is not evidence that the contract was violated. The verdict is still
recorded, so the skip is visible rather than a silent GREEN.

Uses ``@dataclass`` rather than Pydantic (against the repo-wide naming
convention) to match its sibling ``subagent_secret_leak_guard.py`` and
keep the hook stdlib-only: these modules must import under the lite-mode
system interpreter, where pydantic is not guaranteed to be present.

Refs: OMN-15213, OMN-15062 (sibling guard), OMN-9086 (Task()-dispatch
claim verifier — a different seam).
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from extract_last_assistant_message_utils import _extract_last_assistant_message

# A report shorter than this is only accepted when it is dense with
# evidence (>= 2 distinct classes). Calibrated against the observed
# clobber shapes ("Done." = 5 chars, "Task complete." = 14, the
# hook-notification echo ~= 90) and against legitimately terse but
# citing returns ("PASS - OMN-15213: tests/hooks/test_x.py, 12 passed"
# = 3 evidence classes, accepted by the >= 2 rule regardless of length).
MIN_REPORT_CHARS = 120

# Whole-message bare-completion shapes. Matched against the normalized
# message (lowercased, markdown emphasis and trailing punctuation
# stripped), so "**Done.**" and "done" both land here.
_BARE_COMPLETION_RE = re.compile(
    r"^(?:"
    r"done|all done|task done|task complete|task completed|complete|completed|"
    r"finished|all finished|ok|okay|sure|yes|no|acknowledged|understood|"
    r"got it|will do|noted|confirmed|"
    r"no further action|no further action needed|nothing to report|"
    r"nothing further|report complete|complete\.? report submitted"
    r")$",
    re.IGNORECASE,
)

# Markers that identify a reply addressed to the end-of-turn hook
# notification rather than to the dispatching orchestrator. Used only to
# refine the RED reason code -- such messages already fail the evidence
# rules; the distinct reason is what makes the clobber diagnosable.
_HOOK_ECHO_MARKERS = (
    "subagentstop",
    "stop hook",
    "hook notification",
    "additionalcontext",
    "hookspecificoutput",
    "secret-leak guard",
    "leak guard",
    "guard: clean",
)

# Evidence classes the report contract asks for. Order is stable so the
# reason string is deterministic.
_EVIDENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ticket_id", re.compile(r"\bOMN-\d{3,}\b")),
    (
        "pr_or_issue",
        re.compile(
            r"(?:#\d{2,}\b)|(?:https?://\S*github\.com/\S+)|(?:\bPR\s*#?\d{2,})"
        ),
    ),
    (
        "file_path",
        re.compile(
            r"(?:[\w.\-/]*/[\w.\-]+\.(?:py|md|sh|json|ya?ml|toml|ts|tsx|js|sql|txt))"
            r"|(?:\b[\w.\-]+\.(?:py|sh|ya?ml|toml)\b)"
        ),
    ),
    ("command_or_output", re.compile(r"(?:```)|(?:^\s*\$\s+\S)|(?:^\s*>\s+\S)", re.M)),
    (
        "verdict",
        re.compile(
            r"\b(?:PASS|PASSED|FAIL|FAILED|RED|GREEN|BLOCKED|VERIFIED|"
            r"UNVERIFIED|PARTIAL|NO-OP|SKIPPED)\b"
        ),
    ),
    # 7-40 hex chars with at least one digit -- keeps ordinary words
    # ("deadbeef" aside) from masquerading as a commit SHA.
    ("commit_sha", re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")),
)


class EnumReportContractVerdict(StrEnum):
    """Decision emitted by the SubagentStop report-contract guard."""

    PASSED = "passed"
    RED = "red"


@dataclass(frozen=True)
class ModelReportContractResult:
    """Outcome of checking a SubagentStop final return against the contract.

    ``blocking`` is separate from ``verdict`` on purpose: a RED verdict
    on the loop-break pass (``stop_hook_active``) is still RED, it just
    no longer blocks. Collapsing the two would silently downgrade the
    second-pass failure to a PASS.
    """

    verdict: EnumReportContractVerdict
    reason: str
    evidence_classes: tuple[str, ...]
    message_chars: int
    blocking: bool


def _normalize(message: str) -> str:
    """Strip markdown emphasis, surrounding punctuation, and whitespace."""

    text = message.strip()
    text = re.sub(r"[*_`~#]", "", text)
    return text.strip().strip(".!:;,-— \t\n").strip()


def _is_schema_bound(message: str) -> bool:
    """True when the whole message is a JSON object/array (structured return)."""

    text = message.strip()
    if not text.startswith(("{", "[")):
        return False
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(parsed, (dict, list)) and bool(parsed)


def _evidence_classes(message: str) -> tuple[str, ...]:
    """Return the distinct evidence classes cited by *message*."""

    return tuple(
        name for name, pattern in _EVIDENCE_PATTERNS if pattern.search(message)
    )


def _looks_like_hook_echo(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _HOOK_ECHO_MARKERS)


def classify_final_report(message: str) -> ModelReportContractResult:
    """Classify a subagent's final return against the report contract.

    Pure function over the extracted text: no I/O, no environment reads,
    so the fixture transcripts in the test suite exercise exactly the
    code path a live SubagentStop event takes.
    """

    normalized = _normalize(message)
    if not normalized:
        return ModelReportContractResult(
            verdict=EnumReportContractVerdict.RED,
            reason="empty_final_return",
            evidence_classes=(),
            message_chars=0,
            blocking=True,
        )

    if _is_schema_bound(message):
        return ModelReportContractResult(
            verdict=EnumReportContractVerdict.PASSED,
            reason="schema_bound_return",
            evidence_classes=(),
            message_chars=len(normalized),
            blocking=False,
        )

    if _BARE_COMPLETION_RE.match(normalized):
        return ModelReportContractResult(
            verdict=EnumReportContractVerdict.RED,
            reason="bare_completion_claim",
            evidence_classes=(),
            message_chars=len(normalized),
            blocking=True,
        )

    classes = _evidence_classes(message)
    if len(classes) >= 2 or (classes and len(normalized) >= MIN_REPORT_CHARS):
        return ModelReportContractResult(
            verdict=EnumReportContractVerdict.PASSED,
            reason="contract_satisfied",
            evidence_classes=classes,
            message_chars=len(normalized),
            blocking=False,
        )

    if _looks_like_hook_echo(message):
        reason = "hook_notification_echo"
    elif not classes:
        reason = "no_evidence_citations"
    else:
        reason = "report_too_short"

    return ModelReportContractResult(
        verdict=EnumReportContractVerdict.RED,
        reason=reason,
        evidence_classes=classes,
        message_chars=len(normalized),
        blocking=True,
    )


def scan_stop_event(stop_event: dict[str, Any]) -> ModelReportContractResult:
    """Extract the final assistant message and classify it.

    Honors ``stop_hook_active`` as the loop break: the verdict is
    unchanged, but a second consecutive RED does not block again.
    """

    try:
        message = _extract_last_assistant_message(stop_event)
    except Exception:  # noqa: BLE001 - extraction failure is not a contract violation
        return ModelReportContractResult(
            verdict=EnumReportContractVerdict.PASSED,
            reason="extraction_error_nothing_to_check",
            evidence_classes=(),
            message_chars=0,
            blocking=False,
        )

    if not message:
        return ModelReportContractResult(
            verdict=EnumReportContractVerdict.PASSED,
            reason="no_message_extracted",
            evidence_classes=(),
            message_chars=0,
            blocking=False,
        )

    result = classify_final_report(message)

    if result.blocking and stop_event.get("stop_hook_active"):
        # Already blocked once this turn. Stay RED, stop blocking, and
        # make the failure durable instead of letting it evaporate.
        result = ModelReportContractResult(
            verdict=result.verdict,
            reason=f"{result.reason}_retry_exhausted",
            evidence_classes=result.evidence_classes,
            message_chars=result.message_chars,
            blocking=False,
        )
        _record_red(result, stop_event)

    return result


def _record_red(result: ModelReportContractResult, stop_event: dict[str, Any]) -> None:
    """Best-effort durable RED record; never raises into the hook path.

    Written only on the loop-break pass, where the guard stops blocking:
    without this the lane's contract failure would leave no trace at all
    and be indistinguishable from a clean return.
    """

    try:
        from onex_state import ensure_state_path  # local import: optional state dir

        session = str(stop_event.get("session_id") or stop_event.get("sessionId") or "")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = ensure_state_path(
            "hooks",
            "report_contract_red",
            f"{stamp}-{uuid.uuid4().hex[:8]}.json",
        )
        path.write_text(
            json.dumps(
                {
                    "ticket": "OMN-15213",
                    "verdict": result.verdict.value,
                    "reason": result.reason,
                    "evidence_classes": list(result.evidence_classes),
                    "message_chars": result.message_chars,
                    "session_id": session,
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 - state dir unset/unwritable must not wedge the hook
        return


def _hook_output(result: ModelReportContractResult) -> dict[str, Any] | None:
    """Render a verdict into a Claude Code hook envelope, or ``None``.

    ``None`` means emit nothing at all. That is the point of the OMN-15213
    fix: a hook that speaks on the PASS path is itself the end-of-turn
    notification an agent replies to, and that reply is what clobbers the
    real report. Only a blocking verdict -- where a follow-up turn is
    exactly what we want -- produces output.

    Both the top-level ``decision``/``reason`` form and the
    ``hookSpecificOutput`` form are emitted: this repo's registered
    SubagentStop guard uses the latter, while Stop/SubagentStop blocking
    is documented against the former. Emitting both is strictly more
    likely to be honored than picking one.
    """

    if not result.blocking:
        return None

    reason = (
        f"REPORT CONTRACT RED ({result.reason}): the final return does not satisfy "
        "the golden-chain report contract (OMN-15213). Re-emit the actual report as "
        "your final message -- do not reply to this notification with an "
        "acknowledgement. It must cite concrete evidence: file paths, ticket/PR ids, "
        "the commands you ran with their output, and an explicit verdict. If the "
        "lane failed or was blocked, say so and cite what proves it."
    )
    return {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "decision": "block",
            "additionalContext": reason,
        },
    }


def _cli_main() -> int:
    """Read SubagentStop stdin JSON, classify, print hook output.

    Exit codes: 0 = pass/allow, 2 = block (mirrors the sibling
    secret-leak guard). On exit 2 the reason also goes to stderr, which
    is the documented channel Claude Code feeds back to the agent.
    """

    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {}

    result = scan_stop_event(event)
    output = _hook_output(result)
    if output is None:
        return 0

    sys.stdout.write(json.dumps(output))
    sys.stdout.write("\n")
    sys.stderr.write(str(output.get("reason", "")) + "\n")
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised by the shell wrapper
    raise SystemExit(_cli_main())
