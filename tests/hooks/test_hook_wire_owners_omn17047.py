# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook wire ownership follows registered producers, not historical emitters."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.validation.validate_hook_callees import wire_contract_findings

pytestmark = pytest.mark.unit
REPO_ROOT = Path(__file__).resolve().parents[2]
WIRE_DIR = REPO_ROOT / "src/omniclaude/hooks/contracts/wire"
HOOK_EVENTS = {
    "session_started": "SessionStart",
    "session_ended": "SessionEnd",
    "prompt_submitted": "UserPromptSubmit",
    "tool_executed": "PostToolUse",
}


@pytest.mark.parametrize("event", HOOK_EVENTS)
def test_wire_producer_is_registered_hook(event: str) -> None:
    contract = yaml.safe_load((WIRE_DIR / f"{event}_v1.yaml").read_text())
    hooks = json.loads((REPO_ROOT / "plugins/onex/hooks/hooks.json").read_text())
    commands = [
        hook["command"]
        for group in hooks["hooks"][HOOK_EVENTS[event]]
        for hook in group["hooks"]
    ]
    producer = contract["producer"]["file"]
    assert any(producer.removeprefix("plugins/onex/") in cmd for cmd in commands), (
        f"{event}: declared producer {producer} is not invoked by the hook"
    )


@pytest.fixture
def wire_copy(tmp_path: Path) -> Path:
    directory = tmp_path / "wire"
    shutil.copytree(WIRE_DIR, directory)
    return directory


@pytest.fixture
def market_copy(tmp_path: Path) -> Path:
    spec = importlib.util.find_spec("omnimarket")
    assert spec is not None and spec.origin is not None, (
        "consumer dependency must resolve"
    )
    package = Path(spec.origin).parent
    root = tmp_path / "market"
    for name in (
        "node_projection_session_replay",
        "node_projection_hook_ledger",
        "node_projection_work_events",
        "node_session_phase_reducer",
        "node_emit_daemon/registries",
    ):
        shutil.copytree(package / "nodes" / name, root / "src/omnimarket/nodes" / name)
    return root


def test_live_source_routes_resolve() -> None:
    assert wire_contract_findings(REPO_ROOT) == []


@pytest.mark.parametrize(
    "node",
    [
        "node_event_emit_effect",
        "node_projection_session_replay",
        "node_session_phase_reducer",
    ],
)
def test_unregistered_runtime_node_is_refused(
    node: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = importlib.metadata.entry_points(group="onex.nodes")
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda **kwargs: [entry for entry in entries if entry.name != node],
    )
    findings = wire_contract_findings(REPO_ROOT)
    assert any(f"unregistered onex.nodes symbol {node}" in f for f in findings), (
        findings
    )


@pytest.mark.parametrize("event", HOOK_EVENTS)
def test_required_consumer_routes_are_declared(event: str) -> None:
    data = yaml.safe_load((WIRE_DIR / f"{event}_v1.yaml").read_text())
    names = {Path(c["contract"]).parent.name for c in data["consumers"]}
    expected = {
        "node_projection_session_replay",
        "node_projection_work_events",
        "node_projection_hook_ledger",
    }
    if event in ("session_started", "session_ended"):
        expected.add("node_session_phase_reducer")
    assert names == expected


@pytest.mark.parametrize("side", ["producer", "consumer_class", "consumer_model"])
@pytest.mark.parametrize("event", HOOK_EVENTS)
def test_nonexistent_symbol_fails_even_when_topic_exists(
    side: str,
    event: str,
    wire_copy: Path,
    market_copy: Path,
) -> None:
    path = wire_copy / f"{event}_v1.yaml"
    data = yaml.safe_load(path.read_text())
    topic = data["topic"]
    if side == "producer":
        data["producer"]["emitter"]["function"] = "missing_wire_producer_omn17047"
        symbol = data["producer"]["emitter"]["function"]
    else:
        consumer = data["consumers"][0]
        key = "class" if side == "consumer_class" else "model"
        symbol = "MissingWireSymbolOMN17047"
        consumer[key] = symbol
        # Give the ghost the correct topic and runtime contract binding. Merely
        # checking topic/binding equality must not make this negative control pass.
        runtime_path = market_copy / consumer["contract"]
        runtime = yaml.safe_load(runtime_path.read_text())
        if key == "class":
            runtime["handler"]["class"] = symbol
        else:
            module = (
                consumer["model_file"]
                .removeprefix("src/")
                .removesuffix(".py")
                .replace("/", ".")
            )
            runtime["handler"]["input_model"] = module + "." + symbol
        runtime_path.write_text(yaml.safe_dump(runtime))
        assert topic in runtime["event_bus"]["subscribe_topics"]
    path.write_text(yaml.safe_dump(data))
    findings = wire_contract_findings(REPO_ROOT, market_copy, wire_copy)
    assert any("missing symbol " + symbol in finding for finding in findings), findings


@pytest.mark.parametrize(
    "mutation", ["unregistered", "wrong_event", "missing_consumers", "omitted_consumer"]
)
def test_disconnected_wire_route_is_refused(mutation: str, wire_copy: Path) -> None:
    path = wire_copy / "session_started_v1.yaml"
    data = yaml.safe_load(path.read_text())
    if mutation == "unregistered":
        data["producer"]["file"] = (
            "plugins/onex/hooks/scripts/session_end_bus_mirror.sh"
        )
    elif mutation == "wrong_event":
        data["producer"]["event_type"] = "session.ended"
    elif mutation == "omitted_consumer":
        data["consumers"].pop()
    else:
        data["consumers"] = []
    path.write_text(yaml.safe_dump(data))
    assert wire_contract_findings(REPO_ROOT, wire_dir=wire_copy)


def test_commented_out_consumer_model_is_not_a_live_import(
    wire_copy: Path,
    market_copy: Path,
) -> None:
    data = yaml.safe_load((wire_copy / "session_started_v1.yaml").read_text())
    consumer = data["consumers"][0]
    handler = market_copy / consumer["file"]
    # Keep its real class/method and a model annotation; the import exists only
    # as a comment. This is the historical OMN-5737 failure shape.
    model_module = (
        consumer["model_file"]
        .removeprefix("src/")
        .removesuffix(".py")
        .replace("/", ".")
    )
    handler.write_text(
        f"# from {model_module} import {consumer['model']}\n"
        f"class {consumer['class']}:\n"
        f"    def handle(self, request: {consumer['model']}):\n"
        "        return {}\n"
    )
    findings = wire_contract_findings(REPO_ROOT, market_copy, wire_copy)
    assert any("does not import" in finding for finding in findings), findings


@pytest.mark.parametrize("side", ["producer", "consumer"])
@pytest.mark.parametrize("event", HOOK_EVENTS)
def test_existing_gate_cli_rejects_missing_symbol(
    side: str, event: str, wire_copy: Path
) -> None:
    path = wire_copy / f"{event}_v1.yaml"
    data = yaml.safe_load(path.read_text())
    if side == "producer":
        data["producer"]["emitter"]["function"] = "missing_wire_producer_omn17047"
    else:
        data["consumers"][0]["class"] = "MissingWireConsumerOMN17047"
    path.write_text(yaml.safe_dump(data))
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/validation/validate_hook_callees.py"),
            "--wire-dir",
            str(wire_copy),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    symbol = (
        "missing_wire_producer_omn17047"
        if side == "producer"
        else "MissingWireConsumerOMN17047"
    )
    assert symbol in result.stderr


@pytest.mark.parametrize("mutation", ["file", "comment_only", "method"])
def test_source_disconnect_is_refused(
    mutation: str,
    wire_copy: Path,
    market_copy: Path,
) -> None:
    data = yaml.safe_load((wire_copy / "session_started_v1.yaml").read_text())
    consumer = data["consumers"][0]
    target = market_copy / consumer["file"]
    if mutation == "file":
        target.unlink()
    elif mutation == "comment_only":
        target.write_text(f"# class {consumer['class']}: pass\n")
    else:
        target.write_text(f"class {consumer['class']}:\n    pass\n")
    assert wire_contract_findings(REPO_ROOT, market_copy, wire_copy)


def test_malformed_contract_is_a_finding(wire_copy: Path) -> None:
    (wire_copy / "session_started_v1.yaml").write_text("producer: [unterminated")
    findings = wire_contract_findings(REPO_ROOT, wire_dir=wire_copy)
    assert any("session_started_v1.yaml" in finding for finding in findings)


@pytest.mark.asyncio
async def test_journal_emitter_replay_and_phase_runtime_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the real lab dispatch seams in process with isolated storage.

    In-process is intentional: ownership must be verifiable in CI without
    writing synthetic sessions to the shared broker or production tables.
    Only the publish adapter and database are replaced; journal append/drain,
    topic fan-out, handler/model imports and phase dispatch are real.
    """
    import importlib

    import hook_emit_append
    import hook_emit_drainer
    from omnibase_core.enums import EnumNodeKind
    from omnibase_infra.runtime.auto_wiring.handler_wiring import (
        _make_dispatch_callback,
    )
    from omnibase_infra.runtime.state_io.state_store_adapter import (
        CONTEXTVAR_STATE_IO_ROWS,
    )
    from omnimarket.nodes.node_session_phase_reducer.state_codec import (
        StateIoCodec,
        reset_default_proxy,
    )
    from omnimarket.projection.protocol_database import InmemoryDatabaseAdapter

    class Publisher:
        def __init__(self) -> None:
            self.messages: list[tuple[str, dict[str, Any]]] = []

        def publish(self, topic: str, payload: Any, **kwargs: Any) -> None:
            assert isinstance(payload, dict)
            self.messages.append((topic, payload))

    class SnapshotPublisher:
        def __init__(self) -> None:
            self.messages: list[Any] = []

        def publish(self, message: Any) -> bool:
            self.messages.append(message)
            return True

    publisher = Publisher()
    snapshots = SnapshotPublisher()
    monkeypatch.setattr(
        hook_emit_drainer._Emitter,
        "_build_persistent_adapter",
        lambda self, handler_cls: publisher,
    )
    monkeypatch.setenv("ONEX_EMIT_EFFECT_SPOOL_DIR", str(tmp_path / "spool"))
    journal_dir = tmp_path / "journal"
    session_id = "omn17047-inprocess-proof"
    events = ["session_started", "prompt_submitted", "tool_executed", "session_ended"]
    # Match the registered scripts' payloads before registry redaction. Content
    # previews belong on the separate capture topic, not lifecycle telemetry.
    payloads = [
        {"working_directory": "omniclaude", "hook_source": "startup"},
        {
            "working_directory": "omniclaude",
            "prompt_length": 10,
            "hook_source": "user_prompt_submit",
        },
        {
            "working_directory": "omniclaude",
            "tool_name": "Read",
            "duration_ms": 1,
            "interrupted": False,
            "hook_source": "post_tool_use",
        },
        {"reason": "other"},
    ]
    contracts = [
        yaml.safe_load((WIRE_DIR / f"{event}_v1.yaml").read_text()) for event in events
    ]
    for contract, payload in zip(contracts, payloads, strict=True):
        hook_emit_append.append_event(
            event_type=contract["producer"]["event_type"],
            payload={"session_id": session_id, **payload},
            correlation_id=session_id,
            cwd=str(REPO_ROOT),
            actor="codex",
            host_turn_id=None,
            agent_id=None,
            transcript_path=None,
            session_id=session_id,
            journal_dir=str(journal_dir),
        )
    emitter = hook_emit_drainer._Emitter()
    try:
        assert hook_emit_drainer.drain_once(journal_dir, emitter) == (4, 0, 0)
    finally:
        emitter.close()

    def handler_for(consumer: dict[str, str], **kwargs: Any) -> Any:
        module = (
            consumer["file"].removeprefix("src/").removesuffix(".py").replace("/", ".")
        )
        return getattr(importlib.import_module(module), consumer["class"])(**kwargs)

    db = InmemoryDatabaseAdapter()
    phase_row: str | None = None
    for contract in contracts:
        messages = [
            payload
            for topic, payload in publisher.messages
            if topic == contract["topic"]
        ]
        assert len(messages) == 1, (contract["topic"], publisher.messages)
        payload = messages[0]
        replay = next(
            c
            for c in contract["consumers"]
            if "node_projection_session_replay" in c["contract"]
        )
        result = handler_for(replay, publisher=snapshots).handle(
            {**payload, "_db": db, "_topic": contract["topic"]}
        )
        assert result["rows_upserted"] == 1
        assert result["snapshot_published"] is True
        phase = next(
            (
                c
                for c in contract["consumers"]
                if "node_session_phase_reducer" in c["contract"]
            ),
            None,
        )
        if phase is not None:
            wire_session_id = payload["session_id"]
            reset_default_proxy()
            token = CONTEXTVAR_STATE_IO_ROWS.set({wire_session_id: (phase_row, 0)})
            try:
                callback = _make_dispatch_callback(
                    handler_for(phase), None, EnumNodeKind.REDUCER, None
                )
                dispatch = await callback(
                    {
                        "payload": payload,
                        "__bindings": {},
                        "__debug_trace": {"topic": contract["topic"]},
                    }
                )
                assert dispatch is not None
                phase_row = StateIoCodec().flush(wire_session_id)
                assert phase_row is not None
            finally:
                CONTEXTVAR_STATE_IO_ROWS.reset(token)
                reset_default_proxy()
    rows = sorted(
        db.query("session_replay_snapshots"), key=lambda row: int(str(row["sequence"]))
    )
    assert [row["event_type"] for row in rows] == [
        "session_start",
        "user_input",
        "tool_call",
        "session_end",
    ]
    assert phase_row is not None
    assert StateIoCodec().decode(phase_row).current_phase == "ended"
    assert len(snapshots.messages) == 4
