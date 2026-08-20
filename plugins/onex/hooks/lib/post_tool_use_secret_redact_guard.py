# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PostToolUse Bash-output secret-redaction guard [OMN-16277].

Two credential leaks reached agent transcripts on 2026-08-19, different
shapes, same root gap: nothing masks secret-shaped patterns in raw Bash
``tool_response`` text before it reaches the transcript.

    1. Morning -- an over-broad ``kubectl ... -o json``/jsonpath dump of an
       Infisical machine-identity Secret echoed a ``clientSecret`` field
       verbatim.
    2. Evening -- ``env | grep -i POSTGRES`` was piped through an ad-hoc
       ``sed`` filter written for ``KEY=value`` shape; it missed the
       password embedded mid-URL (``postgresql://user:pass@host``)  # pragma: allowlist secret
       because the credential-bearing var's *name* doesn't match a
       ``PASSWORD|SECRET|TOKEN`` filter -- the secret lives in the value
       shape, not the key.

Ad-hoc, per-command agent-authored redaction is exactly the "rule, not
mechanism" failure this doctrine exists to close (memory
``feedback_a_rule_is_not_a_mechanism``): incident 2 proves it -- a
hand-written filter for one shape missed the other. This module is the
mechanism: it scans EVERY Bash tool_response (no size/command-type/exit-code
gate -- a credential can leak in 40 characters or on an error path) with the
shared ``secret_redactor.SECRET_PATTERNS`` and rewrites the tool output
Claude sees before it lands in the transcript.

Wire protocol (probe-verified on Claude Code CLI 2.1.175, same contract
already proven by the token-budget PostToolUse backstop
``skill_output_suppressor.py`` / OMN-13089/13095/13090 --
``docs/research/2026-06-12-updated-tool-output-shape-probe.md``):

- Passthrough emits NOTHING on stdout (plain PostToolUse stdout is
  debug-log-only).
- A redaction emits exactly one JSON object: the ``hookSpecificOutput``
  envelope with ``updatedToolOutput`` (object form) REPLACING the Bash
  tool result. A shape mismatch fails open and invisibly, so the emission
  shape lives behind one function (:func:`build_redaction_output`).

Fail-safe posture (deliberate divergence from this repo's general
"hooks never block Claude Code" availability philosophy -- same divergence
already taken by the SubagentStop secret-leak guard, OMN-15062): this is a
*security* control. PostToolUse cannot block a tool call that already ran
(that's PreToolUse's job), so there is no "block" verdict here -- the
analogous fail-safe move is "when in doubt, mask more, never emit raw
text". Concretely:

    - Nothing extracted (empty stdout/stderr): passthrough. Nothing could
      have leaked via this guard.
    - Text extracted, scan completes, zero matches: passthrough
      (unmodified -- do not touch text we already proved clean).
    - Text extracted, scan completes, matches found: replace with the
      redacted text.
    - Text extracted, the scan itself raises: replace with a withheld
      placeholder, NEVER pass the raw text through. We cannot prove it is
      clean, and unlike the SubagentStop guard there is no "block and ask
      the agent to retry" option available at this hook point.

No artifact-store dependency (unlike ``skill_output_suppressor.py``): this
guard masks specific matched substrings within the same string, in place --
it does not need to capture/archive the original, so it carries none of the
external I/O failure surface the token-budget backstop has.

Refs: OMN-16277 (this ticket), OMN-15062 (SubagentStop precedent, different
surface), OMN-15462 (bounded-regex fix this ticket depends on).
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from secret_redactor import redact_secrets_with_count


class EnumRedactionDecision(StrEnum):
    """Terminal decision for one PostToolUse evaluation."""

    passthrough_not_bash = "passthrough_not_bash"
    passthrough_clean = "passthrough_clean"
    redacted = "redacted"
    redacted_fail_safe = "redacted_fail_safe"


class ModelRedactionEvaluation(BaseModel):
    """Result of evaluating one hook payload (pure decision, no I/O)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: EnumRedactionDecision
    redacted_count: int = 0


_FAIL_SAFE_PLACEHOLDER = "[REDACTED: secret-scan error, output withheld]"


def _extract_stdout_stderr(tool_response: object) -> tuple[str, str]:
    """Pull stdout/stderr from the tool_response.

    Live shape (probe OMN-13090, shared with skill_output_suppressor.py):
    ``{stdout, stderr, interrupted, isImage, noOutputExpected}``. The
    legacy ``output`` key and bare-string responses are accepted for
    replayed historical payloads (falls into stdout).
    """
    if isinstance(tool_response, dict):
        stdout = tool_response.get("stdout")
        stdout = stdout if isinstance(stdout, str) else ""
        stderr = tool_response.get("stderr")
        stderr = stderr if isinstance(stderr, str) else ""
        if not stdout and not stderr:
            legacy_output = tool_response.get("output")
            if isinstance(legacy_output, str):
                stdout = legacy_output
        return stdout, stderr
    if isinstance(tool_response, str):
        return tool_response, ""
    return "", ""


def build_redaction_output(
    *, stdout: str, stderr: str, original: dict[str, Any]
) -> dict[str, Any]:
    """Build the exact PostToolUse replacement emission.

    Shape pinned by the OMN-13090 probe (CLI 2.1.175), same contract as
    ``skill_output_suppressor.build_replacement_output``: the object form
    ``{stdout, stderr, interrupted, isImage}`` REPLACES the Bash tool
    result. ``interrupted``/``isImage`` are preserved from the original
    response rather than hardcoded -- redacting a secret out of an errored
    or interrupted command's output must not silently clear the flag that
    told the caller it failed.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": {
                "stdout": stdout,
                "stderr": stderr,
                "interrupted": bool(original.get("interrupted", False)),
                "isImage": bool(original.get("isImage", False)),
            },
        }
    }


def evaluate_and_redact(
    payload: dict[str, Any],
) -> tuple[ModelRedactionEvaluation, dict[str, Any] | None]:
    """Evaluate one PostToolUse payload and produce its verdict + emission.

    Returns ``(evaluation, replacement)`` where ``replacement`` is the
    exact hook JSON to print (``None`` for every passthrough outcome --
    the hook prints NOTHING, per the wire protocol above).
    """
    if payload.get("tool_name") != "Bash":
        return (
            ModelRedactionEvaluation(
                decision=EnumRedactionDecision.passthrough_not_bash
            ),
            None,
        )

    tool_response = payload.get("tool_response")
    stdout, stderr = _extract_stdout_stderr(tool_response)
    if not stdout and not stderr:
        return (
            ModelRedactionEvaluation(decision=EnumRedactionDecision.passthrough_clean),
            None,
        )

    original = tool_response if isinstance(tool_response, dict) else {}

    try:
        stdout_result = redact_secrets_with_count(stdout) if stdout else None
        stderr_result = redact_secrets_with_count(stderr) if stderr else None
    except Exception:  # noqa: BLE001 - fail SAFE: cannot prove clean, never pass through raw
        replacement = build_redaction_output(
            stdout=_FAIL_SAFE_PLACEHOLDER if stdout else "",
            stderr=_FAIL_SAFE_PLACEHOLDER if stderr else "",
            original=original,
        )
        return (
            ModelRedactionEvaluation(
                decision=EnumRedactionDecision.redacted_fail_safe, redacted_count=-1
            ),
            replacement,
        )

    stdout_count = stdout_result.redacted_count if stdout_result else 0
    stderr_count = stderr_result.redacted_count if stderr_result else 0
    total = stdout_count + stderr_count

    if total == 0:
        return (
            ModelRedactionEvaluation(decision=EnumRedactionDecision.passthrough_clean),
            None,
        )

    replacement = build_redaction_output(
        stdout=stdout_result.text if stdout_result else stdout,
        stderr=stderr_result.text if stderr_result else stderr,
        original=original,
    )
    return (
        ModelRedactionEvaluation(
            decision=EnumRedactionDecision.redacted, redacted_count=total
        ),
        replacement,
    )


def main() -> int:
    """CLI entry: read PostToolUse JSON on stdin, print replacement or nothing.

    Always exits 0 -- a hook crash must never block Claude Code, and
    PostToolUse has no block verdict to route a crash to anyway. Malformed
    stdin has no text to scan, so it is the "nothing extracted" passthrough
    branch, not the fail-safe branch.
    """
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        _evaluation, replacement = evaluate_and_redact(payload)
        if replacement is not None:
            print(json.dumps(replacement))
    except Exception as exc:  # noqa: BLE001 - hook must never crash
        print(f"[post_tool_use_secret_redact_guard] error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the shell wrapper
    raise SystemExit(main())
