# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Contract-declared registrations reach the hook registry (OMN-21416, AC7).

omnimarket publishes ``delegation.usage_call`` and ``delegation.run_step``
through the emit daemon; no Claude Code hook emits them. Under the 2026-10-28
ruling they are declared by wire contracts that the hook registry reads, not
added to the hook-emitted ``EVENT_REGISTRY`` literal or to
``SUPPORTED_EVENT_TYPES``. These tests pin the three properties AC7 names:

* the registry lookup resolves both entries with the contract's topic,
  partition key and required fields, and a removed contract drops its entry;
* ``generate_event_registry.py --check`` matches a daemon registry carrying
  both events only through those contract entries;
* no hook emission call site emits either event, with a perturbation control
  showing the scan finds an emitter that does.

The payloads come from omnimarket's own models at the revision this repository
pins, so a field renamed there fails here.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import omnimarket
import pytest
import yaml
from omnimarket.enums.enum_run_step_kind import EnumRunStepKind
from omnimarket.enums.enum_run_step_outcome import EnumRunStepOutcome
from omnimarket.models.model_delegation_run_step import ModelDelegationRunStep
from omnimarket.models.model_usage_call_event import ModelUsageCallEvent

from omniclaude.hooks.event_registry import (
    EVENT_REGISTRY,
    get_partition_key,
    get_registration,
    list_event_types,
    validate_payload,
)
from omniclaude.nodes.node_contract_event_registration_effect.handlers import (
    handler_contract_event_registrations as contracts,
)
from plugins.onex.hooks.lib.emit_client_wrapper import SUPPORTED_EVENT_TYPES

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "validation" / "generate_event_registry.py"
WIRE_DIR = contracts.WIRE_CONTRACT_DIR
USAGE_CALL = "delegation.usage_call"
RUN_STEP = "delegation.run_step"
CONTRACT_FILES = {
    USAGE_CALL: "delegation_usage_call_v1.yaml",
    RUN_STEP: "delegation_run_step_v1.yaml",
}
# Hook code: everything a Claude Code hook runs or imports to emit.
HOOK_ROOTS = (
    REPO_ROOT / "plugins" / "onex" / "hooks",
    REPO_ROOT / "src" / "omniclaude" / "hooks",
)


def _wire(event_type: str) -> dict[str, Any]:
    loaded = yaml.safe_load((WIRE_DIR / CONTRACT_FILES[event_type]).read_text())
    assert isinstance(loaded, dict)
    return loaded


def _usage_payload() -> dict[str, Any]:
    return ModelUsageCallEvent(
        call_id="call-1",
        model_name="qwen3",
        tenant_id="tenant-a",
        prompt_tokens=10,
        completion_tokens=5,
        estimated_cost_usd=0.0,
        timestamp=datetime.now(UTC),
    ).model_dump(mode="json")


def _run_step_payload() -> dict[str, Any]:
    return ModelDelegationRunStep(
        tenant_id="tenant-a",
        correlation_id=uuid4(),
        step_sequence=1,
        step_kind=next(iter(EnumRunStepKind)),
        started_at=datetime.now(UTC),
        outcome=next(iter(EnumRunStepOutcome)),
    ).model_dump(mode="json")


@pytest.fixture
def wire_copy(tmp_path: Path) -> Iterator[Path]:
    """A copy of the packaged wire contracts the lookup reads instead."""
    copy = tmp_path / "wire"
    shutil.copytree(WIRE_DIR, copy)
    original = contracts.WIRE_CONTRACT_DIR
    contracts.WIRE_CONTRACT_DIR = copy
    contracts._packaged_contract_registrations.cache_clear()
    yield copy
    contracts.WIRE_CONTRACT_DIR = original
    contracts._packaged_contract_registrations.cache_clear()


# --- AC7 (ii): the lookup resolves both contract-declared entries -----------


@pytest.mark.parametrize("event_type", [USAGE_CALL, RUN_STEP])
def test_lookup_resolves_the_contract_entry(event_type: str) -> None:
    wire = _wire(event_type)
    registration = get_registration(event_type)
    assert registration is not None, f"{event_type} does not resolve"
    assert [str(rule.topic_base.value) for rule in registration.fan_out] == [
        wire["topic"]
    ]
    block = wire["event_registration"]
    assert registration.partition_key_field == block["partition_key_field"]
    assert registration.required_fields == block["required_fields"]
    # Every required field is one the wire contract itself requires.
    assert set(registration.required_fields) <= {
        f["name"] for f in wire["required_fields"]
    }


def test_omnimarket_payloads_validate_and_partition_through_the_lookup() -> None:
    usage, step = _usage_payload(), _run_step_payload()
    assert validate_payload(USAGE_CALL, usage) == []
    assert validate_payload(RUN_STEP, step) == []
    assert get_partition_key(USAGE_CALL, usage) == "tenant-a"
    assert get_partition_key(RUN_STEP, step) == str(step["correlation_id"])
    # A payload missing a required field is caught, so the check is not vacuous.
    del usage["model_name"]
    assert validate_payload(USAGE_CALL, usage) == ["model_name"]


@pytest.mark.parametrize("removed", [USAGE_CALL, RUN_STEP])
def test_a_removed_contract_drops_its_entry(wire_copy: Path, removed: str) -> None:
    (wire_copy / CONTRACT_FILES[removed]).unlink()
    kept = RUN_STEP if removed == USAGE_CALL else USAGE_CALL
    assert get_registration(removed) is None
    assert get_registration(kept) is not None


def test_a_malformed_contract_fails_closed(wire_copy: Path) -> None:
    path = wire_copy / CONTRACT_FILES[USAGE_CALL]
    path.write_text(
        path.read_text().replace(
            "partition_key_field: tenant_id", "partition_key_field: 7"
        )
    )
    with pytest.raises(ValueError, match="partition_key_field"):
        get_registration(USAGE_CALL)


def test_two_contracts_declaring_one_event_fail_closed(wire_copy: Path) -> None:
    shutil.copy(
        wire_copy / CONTRACT_FILES[RUN_STEP], wire_copy / "zz_duplicate_v1.yaml"
    )
    with pytest.raises(ValueError, match="already declared"):
        get_registration(RUN_STEP)


def test_contract_entries_stay_out_of_the_hook_emitted_sets() -> None:
    for event_type in (USAGE_CALL, RUN_STEP):
        assert event_type not in EVENT_REGISTRY
        assert event_type not in list_event_types()
        assert event_type not in SUPPORTED_EVENT_TYPES
    # A hook-emitted event still resolves from the literal.
    assert get_registration("prompt.submitted") is EVENT_REGISTRY["prompt.submitted"]


# --- AC7 (i): the generator check matches only through the contract entries -


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "generate_event_registry_omn21416", GENERATOR
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _daemon_events_with_both() -> dict[str, Any]:
    """The pinned omnimarket emit registry plus the entries it still lacks.

    omnimarket#4755 (OMN-21320) declared ``delegation.run_step`` at the pin, so a
    pinned entry is kept as published, not overwritten; ``delegation.usage_call``
    is added.
    """
    registry = (
        Path(omnimarket.__file__).parent
        / "nodes"
        / "node_emit_daemon"
        / "registries"
        / "topics.yaml"
    )
    events = dict(yaml.safe_load(registry.read_text())["events"])
    assert USAGE_CALL not in events, "pin already carries delegation.usage_call"
    events[USAGE_CALL] = {
        "fan_out": [{"topic": "onex.evt.omnimarket.delegation-usage-call.v1"}],
        "partition_key_field": "tenant_id",
        "required_fields": ["call_id", "model_name", "tenant_id", "timestamp"],
    }
    if RUN_STEP not in events:
        events[RUN_STEP] = {
            "fan_out": [{"topic": "onex.evt.omnimarket.delegation-run-step.v1"}],
            "partition_key_field": "correlation_id",
            "required_fields": [
                "tenant_id",
                "correlation_id",
                "step_sequence",
                "step_kind",
                "started_at",
                "outcome",
            ],
        }
    return events


def _drift(gen: Any, daemon_events: dict[str, Any]) -> list[str]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    violations: list[str] = gen.diff_registries(
        gen.build_projected_registry(daemon_events),
        gen.load_committed_registry_as_data(),
    )
    return violations


def test_generator_check_passes_through_the_contract_entries() -> None:
    assert _drift(_generator(), _daemon_events_with_both()) == []


@pytest.mark.parametrize("removed", [USAGE_CALL, RUN_STEP])
def test_generator_check_fails_without_a_contract(
    wire_copy: Path, removed: str
) -> None:
    (wire_copy / CONTRACT_FILES[removed]).unlink()
    violations = _drift(_generator(), _daemon_events_with_both())
    assert any(removed in v for v in violations), violations


def test_generator_check_fails_on_a_partition_key_mismatch() -> None:
    events = _daemon_events_with_both()
    events[USAGE_CALL] = {**events[USAGE_CALL], "partition_key_field": "call_id"}
    violations = _drift(_generator(), events)
    assert any(USAGE_CALL in v and "partition_key_field" in v for v in violations), (
        violations
    )


# --- AC7 (iii): no hook emission call site emits either event --------------

_QUOTED = re.compile(r"""["']([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)["']""")


def _hook_emitted_names(roots: tuple[Path, ...]) -> set[str]:
    """Every quoted dotted name in hook code: event types and topics alike."""
    names: set[str] = set()
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix in {".py", ".sh"} and path.is_file():
                names.update(
                    _QUOTED.findall(path.read_text(encoding="utf-8", errors="replace"))
                )
    return names


def _contract_names() -> set[str]:
    return {USAGE_CALL, RUN_STEP} | {_wire(e)["topic"] for e in (USAGE_CALL, RUN_STEP)}


def test_no_hook_emits_a_contract_declared_event() -> None:
    found = _hook_emitted_names(HOOK_ROOTS)
    # Positive control: the scan sees the events hooks do emit.
    assert {"prompt.submitted", "session.started", "tool.executed"} <= found
    assert found & _contract_names() == set()


@pytest.mark.parametrize("event_type", [USAGE_CALL, RUN_STEP])
def test_the_scan_finds_an_emitter_fixture(tmp_path: Path, event_type: str) -> None:
    hooks = tmp_path / "hooks"
    shutil.copytree(REPO_ROOT / "plugins" / "onex" / "hooks" / "lib", hooks / "lib")
    (hooks / "lib" / "rogue_emitter.py").write_text(
        f'emit_event("{event_type}", {{"tenant_id": "t"}})\n'
    )
    assert event_type in _hook_emitted_names((hooks,)) & _contract_names()
