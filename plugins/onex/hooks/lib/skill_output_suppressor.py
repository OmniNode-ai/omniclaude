# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PostToolUse hook backstop — Layer C of skill output suppression (OMN-13095).

Rewritten for epic OMN-13089 (plan
``docs/plans/2026-06-12-skill-output-suppression-plan.md``, Phase 3).

The previous implementation was a functional no-op: it printed a modified
``tool_info`` dict to plain stdout, which a PostToolUse hook NEVER delivers
to the model (probe OMN-13090, facts F1/F2 — 71,000+ fires, zero effect),
and its pattern list matched no ``onex`` dispatch form (F5).

Protocol contract (pinned by the OMN-13090 probe on Claude Code CLI 2.1.175,
``knowledge-base:reference/claude-code-posttooluse-output-shape.md``):

- **Passthrough emits NOTHING** — empty stdout. Plain JSON on PostToolUse
  stdout is debug-log-only; echoing the tool_info dict is noise.
- **Suppression emits exactly one JSON object** of the form::

      {"hookSpecificOutput": {
          "hookEventName": "PostToolUse",
          "updatedToolOutput": {
              "stdout": "<compact summary + artifact_ref>",
              "stderr": "",
              "interrupted": false,
              "isImage": false}}}

  The object form REPLACES the Bash tool result Claude sees. A shape
  mismatch fails open and INVISIBLY (the CLI silently keeps the original
  output), so the emission shape lives behind one function
  (:func:`build_replacement_output`) and is pinned by protocol-level tests.

Suppression rules (all must hold, in order):

1. ``tool_name == "Bash"`` and the command matches a suppressible pattern
   (legacy tool patterns + ``onex (run|node|run-node)`` covering all
   dispatch shims — F11).
2. The output is NOT a receipt-mode ``ModelSkillResult`` payload
   (schema-version sniff). Receipts pass through untouched regardless of
   size — the result is the result, never tailed/truncated/rewritten.
3. The command did not error: errors are NEVER suppressed (interrupted
   runs and non-zero exit codes pass through in full).
4. The output exceeds the suppression threshold.
5. **Capture before suppress** (no-hidden-loss invariant): the FULL output
   is written to the content-addressed artifact store
   (``omnibase_core.artifacts.ArtifactStore``) and
   ``artifact.captured`` + ``tool.output.captured`` events are emitted via
   the emit daemon. Artifact write failure ⇒ pass through unmodified
   (fail-closed for capture, open for visibility). Event-emission failure
   after a successful artifact write does NOT block suppression — a
   transient daemon outage must never re-flood Claude when the artifact
   exists.

Dependency note: after OMN-17555, ``ArtifactStore`` requires an explicit
``Path`` root. This hook owns that process boundary: it resolves the canonical
``ONEX_STATE_DIR/artifacts`` path and injects it into the store. The legacy
``ONEX_ARTIFACT_STORE_ROOT`` environment variable is not an authority.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CaptureUnavailableError",
    "EnumSuppressionDecision",
    "ModelSuppressionEvaluation",
    "build_replacement_output",
    "detect_command_type",
    "evaluate_payload",
    "is_receipt_output",
    "process_hook_payload",
]


class EnumSuppressionDecision(StrEnum):
    """Terminal decision for one PostToolUse evaluation."""

    passthrough_not_bash = "passthrough_not_bash"
    passthrough_unmatched = "passthrough_unmatched"
    passthrough_small = "passthrough_small"
    passthrough_error = "passthrough_error"
    passthrough_receipt = "passthrough_receipt"
    passthrough_capture_failed = "passthrough_capture_failed"
    suppressed_success = "suppressed_success"
    suppressed_large = "suppressed_large"


class ModelSuppressionEvaluation(BaseModel):
    """Result of evaluating one hook payload (pure decision, no I/O)."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    decision: EnumSuppressionDecision
    command_type: str = ""
    original_bytes: int = 0
    original_lines: int = 0


class CaptureUnavailableError(RuntimeError):
    """The artifact store cannot be opened — capture is impossible.

    Raised by the default store factory when ``omnibase_core.artifacts`` is
    not importable or the configured ``ONEX_STATE_DIR`` cannot be resolved.
    Callers MUST respond by passing the output through unmodified.
    """


class ProtocolArtifactRef(Protocol):
    """Structural type for the content-addressed ref returned by the store."""

    @property
    def ref(self) -> str: ...


class ProtocolBlobStore(Protocol):
    """Structural type matching ``omnibase_core.artifacts.ArtifactStore``."""

    def write_blob(
        self,
        data: bytes,
        *,
        media_type: str,
        artifact_kind: str,
        source_system: str,
        scope_ref: str | None,
        correlation_id: str | None,
    ) -> ProtocolArtifactRef: ...


# Commands whose output is safe to suppress when successful.
# Pattern -> human-readable label for the summary.
_SUPPRESSIBLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ONEX dispatch surface (OMN-13095, F11): covers all dispatch shims and
    # any ad-hoc `onex run`/`onex node`/`onex run-node` that bypasses
    # receipt mode. Receipt-mode output is exempted by the receipt sniff.
    (re.compile(r"\bonex\s+(run|node|run-node)\b"), "onex-dispatch"),
    (re.compile(r"\bpytest\b"), "pytest"),
    (re.compile(r"\bmypy\b"), "mypy"),
    (re.compile(r"\bruff\s+(check|format)\b"), "ruff"),
    (re.compile(r"\bpre-commit\s+run\b"), "pre-commit"),
    (re.compile(r"\bdocker\s+logs\b"), "docker-logs"),
    (re.compile(r"\bnpm\s+run\s+(build|test|lint)\b"), "npm"),
    (re.compile(r"\buv\s+run\s+(pytest|mypy|ruff)\b"), "uv-run"),
    (re.compile(r"\bbandit\b"), "bandit"),
    (re.compile(r"\bpyright\b"), "pyright"),
]

# Output shorter than this (in chars) is never suppressed — already compact.
SUPPRESSION_THRESHOLD = 2000

# At or above this size the capture events record `suppressed_large`
# instead of `suppressed_success` (telemetry granularity only — the
# suppression behavior is identical).
LARGE_OUTPUT_THRESHOLD = 20_000

# Maximum lines included in the summary tail...
_SUMMARY_TAIL_LINES = 15
# ...and a hard char cap on the tail. Applies ONLY to raw un-receipted
# output — receipt-mode ModelSkillResult payloads are never tailed,
# truncated, or rewritten (plan Open Question 3 resolution).
_SUMMARY_TAIL_MAX_CHARS = 4000

# Artifact store metadata constants.
_ARTIFACT_MEDIA_TYPE = "text/plain"
_ARTIFACT_KIND = "tool_stdout"
_SOURCE_SYSTEM = "omniclaude.post_tool_use_suppressor"


def detect_command_type(command: str) -> str | None:
    """Return the command type if it matches a suppressible pattern, else None."""
    for pattern, label in _SUPPRESSIBLE_PATTERNS:
        if pattern.search(command):
            return label
    return None


def is_receipt_output(output: str) -> bool:
    """Detect a receipt-mode ``ModelSkillResult`` payload (schema sniff).

    Layer A receipt-mode dispatch prints exactly one ``ModelSkillResult[T]``
    JSON object to stdout. The backstop must pass it through untouched
    regardless of size (idempotence with Layer A). The sniff requires a
    single parseable JSON object carrying the receipt's schema-identity
    fields: ``schema_version``, ``result_model``, and ``result``.
    """
    stripped = output.strip()
    if not stripped.startswith("{"):
        return False
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return all(key in payload for key in ("schema_version", "result_model", "result"))


def build_replacement_output(summary: str) -> dict[str, object]:
    """Build the exact PostToolUse replacement emission.

    Shape pinned by the OMN-13090 probe (CLI 2.1.175): the object form
    ``{stdout, stderr, interrupted, isImage}`` REPLACES the Bash tool
    result; the string form is schema-rejected (fail-open + invisible).
    All shape knowledge lives in this one function so a future probe
    outcome changes one place.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": {
                "stdout": summary,
                "stderr": "",
                "interrupted": False,
                "isImage": False,
            },
        }
    }


def _open_artifact_store() -> ProtocolBlobStore:
    """Default store factory — open the omnibase_core artifact store.

    Raises:
        CaptureUnavailableError: when the store module is not importable
            or the configured ONEX state root cannot be resolved. Either way
            capture is impossible and the caller must pass the output through
            unmodified.
    """
    try:
        from omnibase_core.artifacts.artifact_store import ArtifactStore
    except ImportError as exc:
        msg = (
            "artifact store unavailable: omnibase_core.artifacts could not "
            f"be imported: {exc}"
        )
        raise CaptureUnavailableError(msg) from exc

    try:
        from onex_state import state_path  # type: ignore[import-not-found]

        artifact_root = state_path("artifacts")
    except (ImportError, RuntimeError) as exc:
        msg = (
            "artifact store unavailable: configured ONEX_STATE_DIR could not "
            f"resolve the artifact root: {exc}"
        )
        raise CaptureUnavailableError(msg) from exc

    return ArtifactStore(root=artifact_root)


def _resolve_correlation_id() -> str:
    """Resolve the session correlation id, minting one when none persists.

    The capture events partition on ``correlation_id``; a freshly minted
    UUID still correlates the ``artifact.captured`` /
    ``tool.output.captured`` pair for this invocation.
    """
    try:
        from correlation_manager import get_correlation_id

        persisted = get_correlation_id()
        if persisted:
            return str(persisted)
    except Exception as exc:  # noqa: BLE001 - hook must never crash on telemetry plumbing
        print(
            f"[skill_output_suppressor] correlation lookup failed: {exc}",
            file=sys.stderr,
        )
    return str(uuid4())


def _emit_capture_events(
    *,
    artifact_ref: str,
    artifact_size_bytes: int,
    suppression_decision: EnumSuppressionDecision,
    command_type: str,
    correlation_id: str,
    session_id: str,
    tool_use_id: str,
    original_lines: int,
) -> bool:
    """Emit ``artifact.captured`` + ``tool.output.captured`` (best effort).

    Returns True when both events were accepted by the daemon. A False
    return is logged by the caller but never blocks suppression: the
    artifact already exists, and a transient daemon outage must not
    re-flood Claude (plan invariant — capture vs telemetry asymmetry).
    """
    try:
        from emit_client_wrapper import emit_event
    except ImportError as exc:
        print(
            f"[skill_output_suppressor] emit client unavailable: {exc}",
            file=sys.stderr,
        )
        return False

    artifact_ok = emit_event(
        "artifact.captured",
        {
            "artifact_ref": artifact_ref,
            "artifact_hash": artifact_ref.removeprefix("sha256:"),
            "artifact_size_bytes": artifact_size_bytes,
            "artifact_media_type": _ARTIFACT_MEDIA_TYPE,
            "artifact_kind": _ARTIFACT_KIND,
            "source_system": _SOURCE_SYSTEM,
            "correlation_id": correlation_id,
            "session_id": session_id,
            "tool_use_id": tool_use_id,
        },
    )
    tool_ok = emit_event(
        "tool.output.captured",
        {
            "tool_name": "Bash",
            "suppression_decision": suppression_decision.value,
            "correlation_id": correlation_id,
            "session_id": session_id,
            "tool_use_id": tool_use_id,
            "artifact_ref": artifact_ref,
            "command_type": command_type,
            "original_bytes": artifact_size_bytes,
            "original_lines": original_lines,
        },
    )
    return artifact_ok and tool_ok


def _extract_pytest_summary(output: str) -> str:
    """Extract pytest's final summary line (e.g., '23 passed in 0.39s')."""
    for line in reversed(output.strip().splitlines()):
        stripped = line.strip()
        if re.search(r"\d+\s+(passed|failed|error)", stripped):
            return stripped.strip("= ").strip()
    return ""


def _extract_mypy_summary(output: str) -> str:
    """Extract mypy's final status line."""
    for line in reversed(output.strip().splitlines()):
        stripped = line.strip()
        if "Success:" in stripped or "Found" in stripped:
            return stripped
    return ""


def _extract_ruff_summary(output: str) -> str:
    """Extract ruff's summary."""
    lines = output.strip().splitlines()
    if not lines:
        return ""
    last = lines[-1].strip()
    if "All checks passed" in last or "Found" in last or "error" in last.lower():
        return last
    return f"{len(lines)} lines of output"


def _tool_summary(command_type: str, output: str) -> str:
    if command_type in ("pytest", "uv-run"):
        return _extract_pytest_summary(output)
    if command_type == "mypy":
        return _extract_mypy_summary(output)
    if command_type in ("ruff", "bandit", "pyright"):
        return _extract_ruff_summary(output)
    return ""


def _build_summary(
    *,
    command_type: str,
    output: str,
    original_lines: int,
    artifact_ref: str,
) -> str:
    """Compact Claude-visible replacement: header + ref + bounded tail.

    The tail cap applies ONLY here — to raw un-receipted output. Receipt
    payloads never reach this function (the receipt sniff passes them
    through untouched).
    """
    lines = output.strip().splitlines()
    tail = lines[-_SUMMARY_TAIL_LINES:]
    tail_text = "\n".join(tail)
    if len(tail_text) > _SUMMARY_TAIL_MAX_CHARS:
        tail_text = tail_text[-_SUMMARY_TAIL_MAX_CHARS:]

    parts = [
        (
            f"[{command_type}] output suppressed by hook backstop "
            f"({original_lines} lines / {len(output.encode('utf-8'))} bytes "
            "captured to artifact store)"
        ),
        f"artifact_ref: {artifact_ref}",
        (
            'full output: ArtifactStore(root=state_path("artifacts")).read_blob('
            "ModelArtifactRef("
            f'ref="{artifact_ref}")) '
            "[store root: configured ONEX_STATE_DIR/artifacts]"
        ),
    ]
    tool_summary = _tool_summary(command_type, output)
    if tool_summary:
        parts.append(f"Result: {tool_summary}")
    parts.append(f"--- last {len(tail)} lines ---")
    parts.append(tail_text)
    return "\n".join(parts)


def _extract_output(tool_response: object) -> str:
    """Pull the Bash output from the tool_response.

    The live shape (probe OMN-13090) is
    ``{stdout, stderr, interrupted, isImage, noOutputExpected}`` with
    stderr already merged into stdout before hooks fire (Probe 5). The
    legacy ``output`` key and bare-string responses are accepted for
    replayed historical payloads.
    """
    if isinstance(tool_response, dict):
        stdout = tool_response.get("stdout")
        if isinstance(stdout, str) and stdout:
            return stdout
        output = tool_response.get("output")
        if isinstance(output, str):
            return output
        return ""
    if isinstance(tool_response, str):
        return tool_response
    return ""


def _extract_exit_code(tool_response: object) -> int | None:
    if not isinstance(tool_response, dict):
        return None
    raw = tool_response.get("exit_code", tool_response.get("exitCode"))
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def evaluate_payload(payload: dict[str, object]) -> ModelSuppressionEvaluation:
    """Pre-capture evaluation: decide whether this payload is suppress-eligible.

    Pure decision logic — no I/O. Capture, event emission, and replacement
    happen in :func:`process_hook_payload` only when this returns
    ``suppressed_success`` or ``suppressed_large``.
    """
    if payload.get("tool_name") != "Bash":
        return ModelSuppressionEvaluation(
            decision=EnumSuppressionDecision.passthrough_not_bash
        )

    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        raw_command = tool_input.get("command")
        if isinstance(raw_command, str):
            command = raw_command

    command_type = detect_command_type(command)
    if command_type is None:
        return ModelSuppressionEvaluation(
            decision=EnumSuppressionDecision.passthrough_unmatched
        )

    tool_response = payload.get("tool_response")
    output = _extract_output(tool_response)
    original_lines = output.count("\n") + 1 if output else 0
    original_bytes = len(output.encode("utf-8"))

    # Errors are NEVER suppressed: interrupted runs and non-zero exits
    # keep their full output for debugging.
    interrupted = (
        isinstance(tool_response, dict) and tool_response.get("interrupted") is True
    )
    exit_code = _extract_exit_code(tool_response)
    if interrupted or (exit_code is not None and exit_code != 0):
        return ModelSuppressionEvaluation(
            decision=EnumSuppressionDecision.passthrough_error,
            command_type=command_type,
            original_bytes=original_bytes,
            original_lines=original_lines,
        )

    # Idempotence with Layer A: receipt-mode ModelSkillResult output passes
    # through untouched regardless of size.
    if is_receipt_output(output):
        return ModelSuppressionEvaluation(
            decision=EnumSuppressionDecision.passthrough_receipt,
            command_type=command_type,
            original_bytes=original_bytes,
            original_lines=original_lines,
        )

    if len(output) < SUPPRESSION_THRESHOLD:
        return ModelSuppressionEvaluation(
            decision=EnumSuppressionDecision.passthrough_small,
            command_type=command_type,
            original_bytes=original_bytes,
            original_lines=original_lines,
        )

    decision = (
        EnumSuppressionDecision.suppressed_large
        if len(output) >= LARGE_OUTPUT_THRESHOLD
        else EnumSuppressionDecision.suppressed_success
    )
    return ModelSuppressionEvaluation(
        decision=decision,
        command_type=command_type,
        original_bytes=original_bytes,
        original_lines=original_lines,
    )


def process_hook_payload(
    payload: dict[str, object],
    *,
    store_factory: Callable[[], ProtocolBlobStore] = _open_artifact_store,
) -> str:
    """Process one PostToolUse payload; return the exact hook stdout.

    Returns the empty string for every passthrough outcome (the hook prints
    NOTHING — plain stdout is debug-log-only) and the serialized
    ``hookSpecificOutput`` replacement JSON when suppression applies.

    Capture is fail-closed: any failure to open the store or write the blob
    logs to stderr and passes the output through unmodified. Event-emission
    failure after a successful write never blocks suppression.
    """
    evaluation = evaluate_payload(payload)
    if evaluation.decision not in (
        EnumSuppressionDecision.suppressed_success,
        EnumSuppressionDecision.suppressed_large,
    ):
        return ""

    output = _extract_output(payload.get("tool_response"))
    correlation_id = _resolve_correlation_id()
    session_id = str(payload.get("session_id") or "")
    tool_use_id = str(payload.get("tool_use_id") or "")

    # Capture BEFORE suppress (no-hidden-loss invariant). Failure here means
    # no suppression: full output stays visible.
    try:
        store = store_factory()
        artifact_ref = store.write_blob(
            output.encode("utf-8"),
            media_type=_ARTIFACT_MEDIA_TYPE,
            artifact_kind=_ARTIFACT_KIND,
            source_system=_SOURCE_SYSTEM,
            scope_ref=session_id or None,
            correlation_id=correlation_id,
        ).ref
    except CaptureUnavailableError as exc:
        print(f"[skill_output_suppressor] capture unavailable: {exc}", file=sys.stderr)
        return ""
    except Exception as exc:  # noqa: BLE001 - any write failure must fail open for visibility
        print(
            f"[skill_output_suppressor] artifact write failed: {exc}", file=sys.stderr
        )
        return ""

    emitted = _emit_capture_events(
        artifact_ref=artifact_ref,
        artifact_size_bytes=evaluation.original_bytes,
        suppression_decision=evaluation.decision,
        command_type=evaluation.command_type,
        correlation_id=correlation_id,
        session_id=session_id,
        tool_use_id=tool_use_id,
        original_lines=evaluation.original_lines,
    )
    if not emitted:
        # Artifact exists — suppression proceeds. Log for the outbox/replay
        # surface; never re-flood Claude over a telemetry outage.
        print(
            "[skill_output_suppressor] capture events not emitted "
            f"(artifact {artifact_ref} persisted; suppression proceeds)",
            file=sys.stderr,
        )

    summary = _build_summary(
        command_type=evaluation.command_type,
        output=output,
        original_lines=evaluation.original_lines,
        artifact_ref=artifact_ref,
    )
    return json.dumps(build_replacement_output(summary))


def main() -> int:
    """CLI entry: read PostToolUse JSON on stdin, print replacement or nothing.

    Always exits 0 — a hook crash must never block Claude Code. Any error
    results in empty stdout (passthrough: the model sees the original
    output unchanged).
    """
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            return 0
        emission = process_hook_payload(payload)
        if emission:
            print(emission)
    except Exception as exc:  # noqa: BLE001 - hook must never crash; passthrough on error
        print(f"[skill_output_suppressor] error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
