# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The registry-consistency script reports, not crashes, on an unregistered type.

A hook-side event type can land in omniclaude before omnimarket registers it
(hook.event, OMN-19513; content.captured, OMN-19551). The gate must print that
ordering violation. Before this fix it raised AttributeError on the missing
daemon entry, so CI showed a traceback instead of the reason.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "validation"
    / "check_registry_consistency.py"
)


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_registry_consistency", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_event_type_missing_from_the_daemon_is_a_violation_not_a_crash(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "topics.yaml"
    registry.write_text("events: {}\n", encoding="utf-8")
    violations = _load_checker().check_registry_consistency(registry)
    missing = [v for v in violations if "missing from omnimarket daemon registry" in v]
    assert missing, violations
