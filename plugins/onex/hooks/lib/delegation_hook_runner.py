#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Delegation hook runner for pre_tool_use_delegation.sh (OMN-10607, OMN-23413).
# Agent/Task: SensitivityGate, TaskClassifier, node_hook_delegate_effect, then prints
# not_delegatable:<why> or "DELEGATED: <task_type> answered by <model> (run <id>)",
# NON-AUTHORITATIVE telemetry JSON and the answer. A prompt prints the node's hook
# output. Every reason that keeps text with Claude is named in the hook log.

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — allow running from the plugin lib dir or repo root
# ---------------------------------------------------------------------------
# hooks/lib -> hooks -> plugins/onex -> plugins -> omniclaude root
_REPO_ROOT = Path(__file__).parents[4]

for _candidate in [_REPO_ROOT / "src", _REPO_ROOT]:
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def _import_gate():  # type: ignore[return]
    # An import or construction error is named by _gate_why (gate_error:<type>).
    from omniclaude.delegation.sensitivity_gate import SensitivityGate

    return SensitivityGate()


def _import_classifier():  # type: ignore[return]
    try:
        from omniclaude.lib.task_classifier import TaskClassifier

        return TaskClassifier()
    except Exception:  # noqa: BLE001
        return None


def _import_telemetry():  # type: ignore[return]
    try:
        from hook_delegation_telemetry import (  # type: ignore[import-not-found]
            ModelHookDelegationTelemetry,
            build_routing_policy_hash,
        )

        return ModelHookDelegationTelemetry, build_routing_policy_hash
    except Exception:  # noqa: BLE001
        return None, None


def _build_telemetry_json(
    task_type: str, model: str, t0: float, correlation_id: str, session_id: str
) -> str:
    # NON-AUTHORITATIVE telemetry JSON, or "" when hook_delegation_telemetry is
    # missing (calling its None stand-ins raises TypeError, caught below).
    TelemetryClass, hash_fn = _import_telemetry()
    try:
        telemetry = TelemetryClass(
            correlation_id=correlation_id,
            session_id=session_id,
            task_type=task_type,
            delegated_to=model,
            routing_policy_hash=hash_fn(),
            delegation_latency_ms=int((time.monotonic() - t0) * 1000),
            # tokens_input / tokens_output / cost_usd stay 0 — hook has no LLM usage
        )
        return json.dumps(telemetry.to_dict())
    except Exception:  # noqa: BLE001
        return ""


def _gate_why(text: str) -> str:
    # "" when text may go to a delegated model, else why not. Fails closed
    # (OMN-23413): with no working gate nothing is sent, and stderr (the hook log)
    # names the reason, so a broken install never reads as a real hit. Empty text
    # holds nothing to keep.
    why = "no_gate"
    try:
        gate = _import_gate() if text else None
        if gate is not None or not text:
            return "sensitive" if text and gate.check(text).is_sensitive else ""
    except Exception as error:  # noqa: BLE001 - fail closed, keep it with Claude
        why = f"gate_error:{type(error).__name__}"
    print(f"delegation gate unavailable ({why}): nothing sent", file=sys.stderr)
    return why


def _sensitive(text: str) -> bool:
    # The node's check for recent conversation (OMN-23413): any text, uncut or not.
    return bool(_gate_why(text))


def _strings(value: object) -> list[str]:
    # Every string a tool input holds, decoded and nested ones included.
    items = [*value.keys(), *value.values()] if isinstance(value, dict) else value
    if isinstance(items, list):
        return [text for item in items for text in _strings(item)]
    return [value] if isinstance(value, str) else []


def main() -> int:
    t0 = time.monotonic()
    # OMN-23413: the answering node; if missing, exit 1 and the .sh passes through
    from omnimarket.nodes.node_hook_delegate_effect import container, models

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    # correlation_id and session_id come from the shell hook, else its environment
    fields = payload if isinstance(payload, dict) else {}
    correlation_id = str(fields.get("correlation_id", ""))
    correlation_id = correlation_id or os.environ.get("HOOK_CORRELATION_ID", "")
    session_id = str(fields.get("session_id", ""))
    if not session_id:
        try:  # PLC0415 (import outside top level) is off for this repo
            from .session_id import resolve_session_id
        except ImportError:
            from plugins.onex.hooks.lib.session_id import resolve_session_id
        session_id = resolve_session_id(default="")

    handler = container.build_handler()
    limit = os.environ.get("ONEX_HOOK_DELEGATE_TIMEOUT_S")  # set by the .sh
    if fields.get("hook_event_name") == "UserPromptSubmit":
        handler.begin_turn(session_id)  # even a disabled prompt starts a new turn
        if os.environ.get("ONEX_HOOK_RESET_ONLY") == "1":
            return 0
        # AC33: every prompt goes to delegation first; Claude answers what it cannot.
        prompt = str(fields.get("prompt", ""))
        # The intent only picks a task class; a classifier error exits 1 and the
        # .sh passes the prompt to Claude.
        tc = _import_classifier()  # the TaskClassifier
        intent = tc.is_delegatable(prompt).classified_intent if tc else ""
        request = models.ModelPromptDelegateRequest.of(
            fields, session_id, _sensitive(prompt), intent, limit
        )
        # The node withholds recent conversation this gate flags (OMN-23413). An
        # omnimarket older than that callback (dependency skew) sends nothing.
        try:
            prompt_handler = container.build_prompt_handler(sensitive=_sensitive)
        except TypeError:
            print("prompt not_delegatable:node_skew (no sensitive)", file=sys.stderr)
            return 0
        result = prompt_handler.handle(request)
        print(result.log_line, file=sys.stderr)  # the .sh appends stderr to its log
        print(result.hook_output)
        return 0

    # Classify the task itself, never session metadata or the whole hook envelope.
    tool_input = fields.get("tool_input", payload)
    tool_text = (
        json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input)
    )
    # The gate reads the decoded strings that are sent, not only their JSON form,
    # where a newline is backslash-n and hides a key from a word boundary.
    why = _gate_why("\n".join([*_strings(tool_input), tool_text]))
    if why:
        print(f"not_delegatable:{why}")
        return 0

    why = "no_classifier"  # OMN-23413: the hook log names every pass-through's reason
    classifier = _import_classifier()
    if classifier is not None:
        try:
            score = classifier.is_delegatable(tool_text)
            why = "classifier"
            if score.delegatable:
                task_type = score.classified_intent
                request = models.ModelHookDelegateRequest.of(
                    tool_input, tool_text, task_type, limit
                ).model_copy(update={"session_id": session_id})
                result = handler.handle(request)
                if not result.answered:  # never block a subagent without an answer
                    print(f"not_delegatable:{result.outcome}")
                    return 0
                model = result.model or score.delegate_to_model or "local-model"
                run = result.run_id
                print(f"DELEGATED: {task_type} answered by {model} (run {run})")
                # NON-AUTHORITATIVE telemetry on a second line, for emit_via_daemon.
                telemetry_json = _build_telemetry_json(
                    task_type, model, t0, correlation_id, session_id
                )
                if telemetry_json:
                    print(telemetry_json)
                print(
                    getattr(result, "hook_output", "") or result.answer
                )  # OMN-26688 deny
                return 0
        except Exception as error:  # noqa: BLE001 - fail open
            why = f"error:{type(error).__name__}"

    print(f"not_delegatable:{why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
