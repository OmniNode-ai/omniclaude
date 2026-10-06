# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook wire ownership follows registered producers, not historical emitters."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

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
def test_nonexistent_symbol_fails_even_when_topic_exists(
    side: str,
    wire_copy: Path,
    market_copy: Path,
) -> None:
    path = wire_copy / "session_started_v1.yaml"
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


def test_existing_gate_cli_rejects_missing_producer_symbol(wire_copy: Path) -> None:
    path = wire_copy / "session_started_v1.yaml"
    data = yaml.safe_load(path.read_text())
    data["producer"]["emitter"]["function"] = "missing_wire_producer_omn17047"
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
    assert "missing symbol missing_wire_producer_omn17047" in result.stderr


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
