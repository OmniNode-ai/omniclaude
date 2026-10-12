# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Definition-B handler of the friction observer: one skill-completed event in,
at most one friction-observed event out.

The classification rules are read once from this node's contract.yaml, so the
contract stays the only place a rule lives. A package-only install (the runtime
image carries ``src/omniclaude`` and nothing under ``plugins/``) can run this
handler; the portable classifier under ``plugins/onex/skills/_shared`` that the
hooks call directly is not importable there.

A completed skill that succeeded is not a friction signal and produces no event.
Every other status is classified; a status no rule names falls to the contract's
wildcard rule (surface ``unknown/unclassified``).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from omniclaude.nodes.node_friction_observer_compute.models import (
    ModelFrictionClassificationRule,
    ModelFrictionObservedEvent,
    ModelFrictionSkillCompletedSignal,
)

_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "contract.yaml"
_EVENT_TYPE = "skill.completed"
_SOURCE = "skill_completed_consumer"
_NON_FRICTION_STATUSES = frozenset({"success"})
_TEMPLATE_PATTERN = re.compile(r"\{([^}]+)\}")


def load_rules(
    contract_path: Path = _CONTRACT_PATH,
) -> tuple[ModelFrictionClassificationRule, ...]:
    """Read and validate ``classification_rules`` from the node contract."""
    with contract_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"contract at {contract_path} is not a mapping")
    rules = tuple(
        ModelFrictionClassificationRule.model_validate(raw)
        for raw in data.get("classification_rules", [])
    )
    seen: set[str] = set()
    for rule in rules:
        if rule.rule_id in seen:
            raise ValueError(f"duplicate rule_id {rule.rule_id!r} in {contract_path}")
        seen.add(rule.rule_id)
    enabled = [rule for rule in rules if rule.enabled]
    for rule in enabled[:-1]:
        if rule.event_pattern == "*":
            raise ValueError(
                f"wildcard rule {rule.rule_id!r} is not last among enabled rules"
            )
    return rules


class HandlerFrictionObserver:
    """Classify a completed skill into a friction event."""

    def __init__(
        self, rules: tuple[ModelFrictionClassificationRule, ...] | None = None
    ) -> None:
        self._rules = load_rules() if rules is None else rules

    def handle(
        self, signal: ModelFrictionSkillCompletedSignal
    ) -> ModelFrictionObservedEvent | None:
        if signal.status in _NON_FRICTION_STATUSES:
            return None
        payload = {
            "status": signal.status,
            "skill_name": signal.skill_name,
            "error": signal.error or signal.error_type or "",
            "blocked_reason": signal.blocked_reason or "",
        }
        for rule in self._rules:
            if rule.enabled and _matches(rule.event_pattern, payload):
                return ModelFrictionObservedEvent(
                    session_id=signal.session_id or str(signal.correlation_id),
                    correlation_id=signal.correlation_id,
                    surface=rule.surface,
                    severity=rule.severity,
                    rule_id=rule.rule_id,
                    event_pattern=rule.event_pattern,
                    source=_SOURCE,
                    description=_render(rule.description_template, payload),
                    emitted_at=signal.emitted_at,
                )
        return None


def _matches(pattern: str, payload: dict[str, str]) -> bool:
    if pattern == "*":
        return True
    event_part, _, qualifier = pattern.partition(":")
    if event_part != _EVENT_TYPE:
        return False
    if not qualifier:
        return True
    field, _, expected = qualifier.partition("=")
    return field in payload and payload[field] == expected


def _render(template: str, payload: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "event_type":
            return _EVENT_TYPE
        if key == "source":
            return _SOURCE
        if key.startswith("payload."):
            return payload.get(key[len("payload.") :], "")
        return ""

    return _TEMPLATE_PATTERN.sub(_replace, template)


__all__ = ["HandlerFrictionObserver", "load_rules"]
