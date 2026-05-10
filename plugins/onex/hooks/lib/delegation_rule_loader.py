#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegation rule loader — reads ~/.omninode/delegation/delegation-rules.yaml.

Provides mtime-cached rule lookup by task_class with confidence and savings
gates. Returns None when the config file is missing (preserving existing
behavior) or when gates are not satisfied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = Path.home() / ".omninode" / "delegation" / "delegation-rules.yaml"


@dataclass
class DelegationRuleDecision:
    behavior: str
    recipient: str = ""
    max_tokens: int = 0


@dataclass
class _CachedConfig:
    mtime: float
    data: dict[str, Any]


class DelegationRuleLoader:
    """Load and cache delegation rules from YAML; expose get_rule() lookup."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = config_path or _DEFAULT_CONFIG
        self._cache: _CachedConfig | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_rule(
        self,
        task_class: str,
        *,
        confidence: float | None = None,
        estimated_savings_usd: float | None = None,
    ) -> DelegationRuleDecision | None:
        """Return a DelegationRuleDecision or None.

        Returns None when:
        - config file does not exist
        - confidence < min_confidence (when confidence is supplied)
        - estimated_savings_usd < min_savings_usd (when supplied)
        Falls back to default_behavior when no task-class rule matches.
        """
        data = self._load()
        if data is None:
            return None

        min_confidence: float = float(data.get("min_confidence", 0.0))
        min_savings: float = float(data.get("min_savings_usd", 0.0))

        if confidence is not None and confidence < min_confidence:
            return None

        if estimated_savings_usd is not None and estimated_savings_usd < min_savings:
            return None

        rules: list[dict[str, Any]] = data.get("rules", [])
        matched: dict[str, Any] | None = None
        for rule in rules:
            if rule.get("task_class") == task_class:
                matched = rule
                break

        if matched is not None:
            return DelegationRuleDecision(
                behavior=str(matched.get("behavior", "suggest")),
                recipient=str(matched.get("recipient", "")),
                max_tokens=int(matched.get("max_tokens", 0)),
            )

        default_behavior = str(data.get("default_behavior", "suggest"))
        return DelegationRuleDecision(behavior=default_behavior)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None

        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return None

        if self._cache is not None and self._cache.mtime == mtime:
            return self._cache.data

        try:
            import yaml  # type: ignore[import-untyped]

            raw = self._path.read_text(encoding="utf-8")
            loaded = yaml.safe_load(raw) or {}
            if not isinstance(loaded, dict):
                raise ValueError("delegation rules config must be a mapping")
            data: dict[str, Any] = loaded
            self._cache = _CachedConfig(mtime=mtime, data=data)
            return data
        except (OSError, ValueError, yaml.YAMLError):
            logger.warning("delegation_rule_loader: failed to parse %s", self._path)
            return None
