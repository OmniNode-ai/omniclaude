# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Contract and mock-seam tests for complete Claude hook capture."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import get_args

import pytest
import yaml
from pydantic import ValidationError

from omniclaude.hooks.model_claude_hook_event import (
    HOOK_PAYLOAD_ADAPTER,
    EnumClaudeHookEventName,
    ModelClaudeHookEvent,
    ModelHookContentRecord,
    ModelHookLineage,
    ModelHookPayload,
    UnknownHookEventError,
    make_tool_call_key,
    map_hook_stdin,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/hooks/claude_hook_capture"
CONTRACT_PATH = (
    REPO_ROOT / "src/omniclaude/hooks/contracts/contract_hook_claude_capture.yaml"
)
FAKE_SECRET = "sk-ant-FAKE0000000000000000000000000000"  # noqa: S105  # pragma: allowlist secret  # secret-ok: planted fake fixture value
GENERATOR_PATH = REPO_ROOT / "scripts/generate_claude_hook_capture_fixtures.py"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_claude_hook_capture_fixtures", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = _load_generator()
SCRUB = GENERATOR.mock_content_scrubber


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _pretty(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_enum_contract_and_discriminated_union_cover_exactly_33_hooks() -> None:
    enum_names = {name.value for name in EnumClaudeHookEventName}
    assert len(enum_names) == 33

    contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    coverage_names = {row["hook"] for row in contract["coverage"]}
    assert coverage_names == enum_names

    annotated_args = get_args(ModelHookPayload)
    assert annotated_args and isinstance(annotated_args[1], object)
    union_members = get_args(annotated_args[0])
    member_names = {
        get_args(member.model_fields["hook_event_name"].annotation)[0]
        for member in union_members
    }
    assert len(union_members) == 33
    assert member_names == enum_names
    assert isinstance(HOOK_PAYLOAD_ADAPTER, object)


@pytest.mark.parametrize("hook_name", list(EnumClaudeHookEventName))
def test_each_stdin_fixture_maps_and_reserializes_byte_identically(
    hook_name: EnumClaudeHookEventName,
) -> None:
    stdin = _load_json(FIXTURE_ROOT / "stdin" / f"{hook_name.value}.json")
    expected_path = FIXTURE_ROOT / "events" / f"{hook_name.value}.json"
    expected = _load_json(expected_path)
    assert isinstance(stdin, dict)
    assert isinstance(expected, dict)
    emitted_at = datetime.fromisoformat(
        str(expected["emitted_at"]).replace("Z", "+00:00")
    )
    lineage = expected["lineage"]
    assert isinstance(lineage, dict)

    result = map_hook_stdin(
        stdin,
        emitted_at=emitted_at,
        sidecar=None,
        claude_code_version="2.1.283",
        turn_id=lineage["turn_id"] if isinstance(lineage["turn_id"], str) else None,
        content_scrubber=SCRUB,
    )
    validated = ModelClaudeHookEvent.model_validate(
        result.event.model_dump(mode="json")
    )
    assert validated == result.event
    assert _pretty(result.event.model_dump(mode="json")) == expected_path.read_text(
        encoding="utf-8"
    )


def test_content_values_and_planted_secret_never_enter_metadata_events() -> None:
    all_event_text = "".join(
        path.read_text(encoding="utf-8")
        for path in sorted((FIXTURE_ROOT / "events").glob("*.json"))
    )
    for content_path in sorted((FIXTURE_ROOT / "content").glob("*.json")):
        records = _load_json(content_path)
        assert isinstance(records, list)
        for record in records:
            assert isinstance(record, dict)
            value = record["value"]
            assert isinstance(value, str)
            assert value not in all_event_text

    for scenario_events in sorted((FIXTURE_ROOT / "scenarios").glob("*.events.jsonl")):
        content_path = scenario_events.with_name(
            scenario_events.name.replace(".events.jsonl", ".content.jsonl")
        )
        event_text = scenario_events.read_text(encoding="utf-8")
        for record in _load_jsonl(content_path):
            value = record["value"]
            assert isinstance(value, str)
            assert value not in event_text


def test_planted_secret_survives_only_in_stdin_fixtures() -> None:
    """Scrub-before-hash: the secret reaches no event and no content record."""

    carriers = []
    for path in sorted(FIXTURE_ROOT.rglob("*")):
        if path.is_file() and FAKE_SECRET in path.read_text(encoding="utf-8"):
            carriers.append(path.relative_to(FIXTURE_ROOT).as_posix())
    assert carriers, "positive control: the stdin fixtures must plant the secret"
    for carrier in carriers:
        assert carrier.startswith("stdin/") or carrier.endswith(".stdin.jsonl"), carrier


def test_scrubbed_content_record_carries_its_redaction_state() -> None:
    raw = _load_json(FIXTURE_ROOT / "content" / "UserPromptSubmit.json")
    assert isinstance(raw, list)
    records = [ModelHookContentRecord.model_validate(value) for value in raw]
    prompt = next(record for record in records if record.field == "prompt")
    assert prompt.redaction_state == "secret_detected"
    assert prompt.matched_pattern_names == ("anthropic_api_key",)
    assert "[REDACTED:anthropic_api_key]" in prompt.value
    title = next(record for record in records if record.field == "session_title")
    assert title.redaction_state == "clean"
    assert title.matched_pattern_names == ()


def test_mapper_requires_an_explicit_scrubber() -> None:
    raw = _load_json(FIXTURE_ROOT / "stdin" / "UserPromptSubmit.json")
    assert isinstance(raw, dict)
    with pytest.raises(TypeError):
        map_hook_stdin(  # type: ignore[call-arg]
            raw,
            emitted_at=datetime.fromisoformat("2026-09-26T12:00:00+00:00"),
            sidecar=None,
            claude_code_version="2.1.283",
            turn_id=None,
        )


def test_every_content_ref_has_one_matching_record() -> None:
    for hook_name in EnumClaudeHookEventName:
        event = ModelClaudeHookEvent.model_validate(
            _load_json(FIXTURE_ROOT / "events" / f"{hook_name.value}.json")
        )
        raw_records = _load_json(FIXTURE_ROOT / "content" / f"{hook_name.value}.json")
        assert isinstance(raw_records, list)
        records = [
            ModelHookContentRecord.model_validate(value) for value in raw_records
        ]
        by_id = {record.content_record_id: record for record in records}
        assert set(by_id) == {ref.content_record_id for ref in event.content_refs}
        for ref in event.content_refs:
            record = by_id[ref.content_record_id]
            assert record.sha256 == ref.sha256
            assert record.length == ref.length


def test_subagent_projection_distinguishes_main_nested_and_workflow_agents() -> None:
    events = _load_jsonl(FIXTURE_ROOT / "scenarios" / "subagent_tree.events.jsonl")
    for event in events:
        lineage = event["lineage"]
        assert isinstance(lineage, dict)
        if lineage["agent_id"] is None:
            assert lineage["is_subagent"] is False
        else:
            assert lineage["is_subagent"] is True
            assert lineage["agent_id"] in {"a1", "a2"}

    span_rows = _load_jsonl(
        FIXTURE_ROOT / "expected_projection" / "claude_agent_spans.jsonl"
    )
    spans = {(row["session_id"], row["agent_id"]): row for row in span_rows}
    a1 = spans[("session-subagent-tree", "a1")]
    a2 = spans[("session-subagent-tree", "a2")]
    workflow = spans[("session-workflow-agent", "workflow-a1")]
    assert a1["parent_agent_id"] is None
    assert a1["parent_tool_use_id"] == "toolu_main_1"
    assert a2["parent_agent_id"] == "a1"
    assert a2["parent_tool_use_id"] == "toolu_sub_2"
    assert workflow["workflow_run_id"] == "workflow-run-1"
    assert workflow["parent_tool_use_id"] is None
    assert a1["parent_resolution"] == "main_thread"
    assert a2["parent_resolution"] == "resolved"
    assert workflow["parent_resolution"] == "workflow"
    orphan = spans[("session-orphan-agent", "orphan-a1")]
    assert orphan["parent_resolution"] == "unknown"
    assert orphan["parent_agent_id"] is None
    assert orphan["parent_tool_use_id"] is None
    assert orphan["tool_call_count"] == 1

    projected_events = _load_jsonl(
        FIXTURE_ROOT / "expected_projection" / "claude_hook_events.jsonl"
    )
    a1_tools = {
        row["tool_use_id"]
        for row in projected_events
        if row["session_id"] == "session-subagent-tree"
        and row["agent_id"] == "a1"
        and row["tool_use_id"] is not None
    }
    main_tools = {
        row["tool_use_id"]
        for row in projected_events
        if row["session_id"] == "session-subagent-tree"
        and row["agent_id"] is None
        and row["tool_use_id"] is not None
    }
    assert "toolu_sub_1" in a1_tools
    assert "toolu_main_1" in main_tools
    assert a1_tools != main_tools


def test_post_tool_causation_matches_pre_tool_call_key() -> None:
    pre = ModelClaudeHookEvent.model_validate(
        _load_json(FIXTURE_ROOT / "events" / "PreToolUse.json")
    )
    post = ModelClaudeHookEvent.model_validate(
        _load_json(FIXTURE_ROOT / "events" / "PostToolUse.json")
    )
    assert pre.lineage.tool_use_id == post.lineage.tool_use_id
    expected_key = make_tool_call_key(
        pre.lineage.session_id,
        str(pre.lineage.tool_use_id),
    )
    assert pre.payload.hook_event_name == "PreToolUse"
    assert pre.payload.tool_call_key == expected_key
    assert post.lineage.causation_id == expected_key


def test_event_id_is_deterministic_and_agent_sensitive() -> None:
    raw = _load_json(FIXTURE_ROOT / "stdin" / "PreToolUse.json")
    assert isinstance(raw, dict)
    emitted_at = datetime.fromisoformat("2026-09-26T12:00:00+00:00")
    first = map_hook_stdin(
        raw,
        emitted_at=emitted_at,
        sidecar=None,
        claude_code_version="2.1.283",
        turn_id="turn-fixed-1",
        content_scrubber=SCRUB,
    )
    second = map_hook_stdin(
        raw,
        emitted_at=emitted_at,
        sidecar=None,
        claude_code_version="2.1.283",
        turn_id="turn-fixed-1",
        content_scrubber=SCRUB,
    )
    agent_raw = {**raw, "agent_id": "different-agent"}
    agent = map_hook_stdin(
        agent_raw,
        emitted_at=emitted_at,
        sidecar=None,
        claude_code_version="2.1.283",
        turn_id="turn-fixed-1",
        content_scrubber=SCRUB,
    )
    assert first.event.event_id == second.event.event_id
    assert first.event.event_id != agent.event.event_id


def test_unknown_hook_name_fails_closed() -> None:
    with pytest.raises(UnknownHookEventError):
        map_hook_stdin(
            {
                "session_id": "session-unknown",
                "hook_event_name": "FutureHook",
            },
            emitted_at=datetime.fromisoformat("2026-09-26T12:00:00+00:00"),
            sidecar=None,
            claude_code_version="2.1.283",
            turn_id=None,
            content_scrubber=SCRUB,
        )


def test_lineage_rejects_is_subagent_agent_id_inconsistency() -> None:
    with pytest.raises(ValidationError, match="is_subagent"):
        ModelHookLineage(
            session_id="session-invalid",
            agent_id=None,
            agent_type=None,
            is_subagent=True,
            parent_tool_use_id=None,
            workflow_run_id=None,
            spawn_depth=None,
            tool_use_id=None,
            prompt_id=None,
            turn_id=None,
            correlation_id="9c9bfcbd-fdf0-5f48-987f-4f20560458af",
            causation_id=None,
        )


def test_generator_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_claude_hook_capture_fixtures.py",
            "--check",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
