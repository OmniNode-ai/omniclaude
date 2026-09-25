# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19153: the omniclaude spelling of the DoD-verify-completed topic is retired.

Two spellings existed. The surviving one is omnimarket's, which the verify
node declares and the durable verdict projection subscribes. The omniclaude
one had no consumer anywhere, an incompatible flat telemetry payload, a
``duty_critical`` registry tier contradicted by a ``telemetry`` waiver, and a
live emitting call site. It is deleted (decision recorded on OMN-19153).

The retired literal is assembled from parts so this guard never matches
itself.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RETIRED = "onex.evt.omniclaude." + "dod-verify-completed.v1"
SURVIVING = "onex.evt.omnimarket." + "dod-verify-completed.v1"
RETIRED_EVENT_TYPE = "dod.verify" + ".completed"
_SCANNED_ROOTS = ("src", "plugins")
_SCANNED_SUFFIXES = (".py", ".yaml", ".yml", ".json", ".sh")


def _occurrences(needle: str) -> list[str]:
    hits: list[str] = []
    for root in _SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*"):
            if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
                continue
            if "tests" in path.relative_to(REPO_ROOT).parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if needle in text:
                hits.append(str(path.relative_to(REPO_ROOT)))
    return sorted(hits)


@pytest.mark.unit
def test_no_source_contract_registry_or_waiver_names_the_retired_spelling() -> None:
    assert _occurrences(RETIRED) == []


@pytest.mark.unit
def test_the_matcher_finds_the_surviving_spelling() -> None:
    """Positive control: the same scan does find a spelling that is present."""
    assert "src/omniclaude/nodes/node_skill_dod_verify_orchestrator/contract.yaml" in (
        _occurrences(SURVIVING)
    )


@pytest.mark.unit
def test_the_retired_event_type_is_registered_nowhere() -> None:
    from omniclaude.hooks.event_registry import EVENT_REGISTRY

    assert RETIRED_EVENT_TYPE not in EVENT_REGISTRY
    plugin_registry = yaml.safe_load(
        (REPO_ROOT / "plugins/onex/lib/event_registry/omniclaude.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert RETIRED_EVENT_TYPE not in plugin_registry["events"]
    assert _occurrences(f'"{RETIRED_EVENT_TYPE}"') == []


@pytest.mark.unit
def test_the_evidence_runner_writes_its_receipt_and_emits_nothing() -> None:
    runner_dir = REPO_ROOT / "plugins/onex/skills/_lib/dod-evidence-runner"
    sys.path.insert(0, str(runner_dir))
    try:
        import dod_evidence_runner
    finally:
        sys.path.remove(str(runner_dir))
    assert not hasattr(dod_evidence_runner, "emit_dod_verify_completed")
    params = inspect.signature(dod_evidence_runner.write_evidence_receipt).parameters
    assert "emit" not in params
    assert "policy_mode" not in params
