# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Contract-driven friction classification engine.

Loads classification rules from ONEX contract YAML and evaluates FrictionSignal
instances against them. Pure functions — no side effects, no ONEX node imports.

V1 classification patterns intentionally support only exact event match, one
payload qualifier, and wildcard fallback. Does NOT support: multiple qualifiers,
nested payload paths, inequality/membership operators, regex, source constraints,
or severity escalation by context. More complex matching should be added only
when a concrete signal class requires it.

Rule order is semantically significant in V1. Reordering enabled rules can change
classification behavior and should be treated as a contract behavior change, not
mere formatting.

Pattern format:
  - "event.type" — exact match on event_type
  - "event.type:field=value" — exact match on event_type AND payload[field] == value
  - "*" — wildcard, matches any signal (use as fallback)

Template format:
  - {event_type} — resolves to signal.event_type
  - {source} — resolves to signal.source
  - {payload.key} — resolves to signal.payload.get("key", "")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from friction_recorder import FrictionSeverity
from friction_signal import (
    FrictionSignal,  # noqa: TC002 — runtime usage in _resolve_template/_matches_pattern
)

_TEMPLATE_PATTERN = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True)
class ClassificationRule:
    """A single classification rule loaded from contract YAML."""

    rule_id: str
    event_pattern: str
    surface: str
    severity: str
    description_template: str
    enabled: bool = True
    note: str = ""


@dataclass(frozen=True)
class ClassificationResult:
    """Output of a successful classification."""

    rule_id: str
    surface: str
    severity: FrictionSeverity
    description: str
    event_pattern: str


def _resolve_template(template: str, signal: FrictionSignal) -> str:
    """Resolve {placeholder} tokens against signal fields. Missing keys -> empty string."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "event_type":
            return signal.event_type
        if key == "source":
            return signal.source
        if key.startswith("payload."):
            payload_key = key[len("payload.") :]
            val = signal.payload.get(payload_key, "")
            return str(val) if val is not None else ""
        return ""

    return _TEMPLATE_PATTERN.sub(_replace, template)


def _matches_pattern(signal: FrictionSignal, pattern: str) -> bool:
    """Check if a signal matches a classification rule pattern."""
    if pattern == "*":
        return True

    if ":" in pattern:
        event_part, qualifier = pattern.split(":", 1)
        if signal.event_type != event_part:
            return False
        if "=" in qualifier:
            field, expected = qualifier.split("=", 1)
            actual = signal.payload.get(field)
            return str(actual) == expected if actual is not None else False
        return False

    return signal.event_type == pattern


def match_signal(
    signal: FrictionSignal, rules: list[ClassificationRule]
) -> ClassificationResult | None:
    """Evaluate signal against rules (first-match-wins, skips disabled). Returns None if no match."""
    for rule in rules:
        if not rule.enabled:
            continue
        if _matches_pattern(signal, rule.event_pattern):
            return ClassificationResult(
                rule_id=rule.rule_id,
                surface=rule.surface,
                severity=FrictionSeverity(rule.severity),
                description=_resolve_template(rule.description_template, signal),
                event_pattern=rule.event_pattern,
            )
    return None


_REQUIRED_RULE_FIELDS = frozenset(
    {"rule_id", "event_pattern", "surface", "severity", "description_template"}
)
_VALID_SEVERITIES = frozenset({"low", "medium", "high"})
_VALID_PATTERN = re.compile(
    r"^(\*|[a-z][a-z0-9_.]*(?::[a-z_]+=\S+)?)$"
)  # "*" or "event.type" or "event.type:field=value"


def load_rules_from_yaml(yaml_path: Path) -> list[ClassificationRule]:
    """Parse classification_rules from a contract YAML file.

    Validates required fields and severity values. Raises ValueError with
    path-aware context on malformed rules.
    """
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        raise ValueError(f"Failed to load contract YAML at {yaml_path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Contract YAML at {yaml_path} is not a mapping")

    raw_rules = data.get("classification_rules", [])
    if not raw_rules:
        return []

    rules: list[ClassificationRule] = []
    seen_ids: set[str] = set()

    for i, r in enumerate(raw_rules):
        if not isinstance(r, dict):
            raise ValueError(
                f"Classification rule #{i} in {yaml_path} is not a mapping: {r!r}"
            )

        missing = _REQUIRED_RULE_FIELDS - r.keys()
        if missing:
            raise ValueError(
                f"Classification rule #{i} in {yaml_path} missing required fields: {missing}"
            )

        severity = r["severity"]
        if severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Classification rule #{i} (rule_id={r.get('rule_id', '?')}) in {yaml_path} "
                f"has invalid severity '{severity}', expected one of {_VALID_SEVERITIES}"
            )

        rule_id = r["rule_id"]
        if rule_id in seen_ids:
            raise ValueError(f"Duplicate rule_id '{rule_id}' in {yaml_path}")
        seen_ids.add(rule_id)

        surface = r["surface"]
        if not surface or "/" not in surface:
            raise ValueError(
                f"Classification rule #{i} (rule_id={rule_id}) in {yaml_path} "
                f"has invalid surface '{surface}'. Expected 'category/detail' format."
            )

        pattern = r["event_pattern"]
        if not _VALID_PATTERN.match(pattern):
            raise ValueError(
                f"Classification rule #{i} (rule_id={rule_id}) in {yaml_path} "
                f"has invalid event_pattern '{pattern}'. "
                f"V1 supports: exact event type, one field=value qualifier, or '*' wildcard."
            )

        rules.append(
            ClassificationRule(
                rule_id=rule_id,
                event_pattern=pattern,
                surface=r["surface"],
                severity=severity,
                description_template=r["description_template"],
                enabled=r.get("enabled", True),
                note=r.get("note", ""),
            )
        )

    # Warn if wildcard is not last among enabled rules
    enabled_rules = [r for r in rules if r.enabled]
    for _j, er in enumerate(enabled_rules[:-1]):
        if er.event_pattern == "*":
            raise ValueError(
                f"Wildcard rule '{er.rule_id}' in {yaml_path} is not last among "
                f"enabled rules — it would shadow all subsequent rules."
            )

    return rules
