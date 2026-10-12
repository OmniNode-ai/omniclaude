# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The friction observer's handler, as the runtime reaches it from the contract."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import typing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from omniclaude.hooks.topics import TopicBase

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_NODE_DIR = (
    _REPO_ROOT / "src" / "omniclaude" / "nodes" / "node_friction_observer_compute"
)
_CONTRACT_PATH = _NODE_DIR / "contract.yaml"
_SHARED_PATH = str(_REPO_ROOT / "plugins" / "onex" / "skills" / "_shared")
_EMITTED_AT = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _contract() -> dict[str, dict[str, object]]:
    loaded = yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _runtime_entry() -> typing.Callable[[dict[str, object]], object]:
    """Build the handler the way the runtime does: from the contract, no arguments,
    then decode the published wire dict into the handler's declared input model."""
    handler_ref = _contract()["handler_routing"]["handlers"][0]["handler"]
    cls = getattr(importlib.import_module(handler_ref["module"]), handler_ref["name"])
    instance = cls()
    input_model = typing.get_type_hints(instance.handle)["signal"]

    def _enter(wire: dict[str, object]) -> object:
        return instance.handle(input_model.model_validate(wire))

    return _enter


def _wire(status: str, skill_name: str, **extra: object) -> dict[str, object]:
    """A skill-completed event as the producer publishes it, plus its own extra keys."""
    return {
        "event_id": str(uuid4()),
        "run_id": str(uuid4()),
        "skill_name": skill_name,
        "repo_id": "omniclaude",
        "correlation_id": str(uuid4()),
        "status": status,
        "duration_ms": 12,
        "emitted_at": _EMITTED_AT.isoformat(),
        **extra,
    }


@pytest.mark.unit
class TestContractWiring:
    def test_subscribes_to_skill_completed_and_publishes_friction_observed(self):
        contract = _contract()
        assert contract["event_bus"]["subscribe_topics"] == [
            TopicBase.SKILL_COMPLETED.value
        ]
        assert contract["event_bus"]["publish_topics"] == [
            TopicBase.FRICTION_OBSERVED.value
        ]
        assert contract["runtime_dispatch"]["command_topic"] == (
            TopicBase.SKILL_COMPLETED.value
        )
        assert [e["topic"] for e in contract["published_events"]] == [
            TopicBase.FRICTION_OBSERVED.value
        ]

    def test_published_event_name_is_the_output_class_without_its_model_prefix(self):
        """The runtime resolves an emitted event's topic by class name minus ``Model``."""
        contract = _contract()
        output = contract["output_model"]["name"]
        assert [e["event_type"] for e in contract["published_events"]] == [
            output.removeprefix("Model")
        ]

    def test_handler_declared_in_contract_matches_its_signature(self):
        contract = _contract()
        handler = contract["handler"]
        cls = getattr(importlib.import_module(handler["module"]), handler["class"])
        hints = typing.get_type_hints(cls.handle)
        module, _, name = handler["input_model"].rpartition(".")
        assert hints["signal"] is getattr(importlib.import_module(module), name)
        assert contract["input_model"]["name"] == name

    def test_node_package_imports_without_the_plugins_tree(self, tmp_path: Path):
        """A package-only install carries src/omniclaude and nothing under plugins/."""
        copy = tmp_path / "omniclaude"
        shutil.copytree(
            _REPO_ROOT / "src" / "omniclaude",
            copy,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        probe = (
            "import omniclaude, importlib\n"
            f"assert omniclaude.__file__.startswith({str(copy)!r}), omniclaude.__file__\n"
            "importlib.import_module('omniclaude.nodes.node_friction_observer_compute')\n"
            "from omniclaude.nodes.node_friction_observer_compute.handlers import "
            "HandlerFrictionObserver\n"
            "HandlerFrictionObserver()\n"
        )
        env = {**os.environ, "PYTHONPATH": str(tmp_path)}
        env.pop("PYTHONHOME", None)
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


@pytest.mark.unit
class TestRuntimeEntry:
    def test_failed_skill_yields_skill_failed_naming_the_skill(self):
        skill = f"fictional-skill-{uuid4().hex[:8]}"
        wire = _wire("failed", skill, error="synthetic failure")
        event = _runtime_entry()(wire)
        assert event is not None
        assert event.surface == "tooling/skill-failed"
        assert event.severity.value == "medium"
        assert event.rule_id == "skill_failed"
        assert skill in event.description
        assert event.session_id == wire["correlation_id"]
        assert str(event.correlation_id) == wire["correlation_id"]
        assert event.emitted_at == _EMITTED_AT

    def test_session_id_is_kept_when_the_signal_has_one(self):
        event = _runtime_entry()(_wire("failed", "fictional-skill-x", session_id="s-1"))
        assert event is not None
        assert event.session_id == "s-1"

    def test_error_type_fills_the_description_when_error_is_absent(self):
        event = _runtime_entry()(
            _wire("failed", "fictional-skill-x", error_type="RuntimeError")
        )
        assert event is not None
        assert event.description == "Skill fictional-skill-x failed: RuntimeError"

    def test_known_rules_yield_their_surfaces(self):
        entry = _runtime_entry()
        for status, surface in [
            ("error", "tooling/skill-error"),
            ("blocked", "tooling/skill-blocked"),
            ("gated", "tooling/skill-gated"),
        ]:
            event = entry(_wire(status, "fictional-skill-x"))
            assert event is not None
            assert event.surface == surface

    def test_unmatched_status_yields_the_wildcard(self):
        event = _runtime_entry()(_wire("partial", "fictional-skill-x"))
        assert event is not None
        assert event.surface == "unknown/unclassified"
        assert event.severity.value == "low"
        assert event.rule_id == "wildcard"

    def test_success_is_not_friction(self):
        assert _runtime_entry()(_wire("success", "fictional-skill-x")) is None


@pytest.mark.unit
class TestParityWithPortableClassifier:
    """The hooks classify with the portable module; the node must agree on every rule."""

    @pytest.mark.parametrize(
        "status", ["failed", "error", "blocked", "gated", "partial", "other"]
    )
    def test_surface_severity_and_description_agree(self, status: str):
        sys.path.insert(0, _SHARED_PATH)
        try:
            from friction_classifier import load_rules_from_yaml, match_signal
            from friction_signal import FrictionSignal
        finally:
            sys.path.remove(_SHARED_PATH)

        payload = {
            "status": status,
            "skill_name": "fictional-skill-x",
            "error": "boom",
            "blocked_reason": "waiting",
        }
        expected = match_signal(
            FrictionSignal(
                source="skill_completed_consumer",
                event_type="skill.completed",
                payload=payload,
                timestamp=_EMITTED_AT,
            ),
            load_rules_from_yaml(_CONTRACT_PATH),
        )
        actual = _runtime_entry()(
            _wire(
                status,
                "fictional-skill-x",
                error="boom",
                blocked_reason="waiting",
            )
        )
        assert expected is not None
        assert actual is not None
        assert actual.surface == expected.surface
        assert actual.severity.value == expected.severity.value
        assert actual.description == expected.description
        assert actual.rule_id == expected.rule_id
