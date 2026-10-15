# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared item identity, producer sequence and barrier (OMN-18531, TA.21).

The omniclaude half of TA.21. The acceptance criteria this file holds, each with
the falsifier the plan names:

* a full-capture lineage reference resolves by ``content_record_id`` to one
  content record, and two byte-identical prompts resolve to two records;
* eight concurrent writers issue 1,000 sequence numbers with no duplicate and
  no gap;
* with ``OMNICLAUDE_CONTENT_CAPTURE=0`` the lineage barrier says
  ``content_capture: disabled`` and the content stream journals nothing;
* the new fields are classified by the capture-redaction contract, so the
  fan-out does not hash them.

Planted text is built by concatenation and carries ``FAKE``.
"""

from __future__ import annotations

import ast
import importlib
import json
import multiprocessing
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from omniclaude.hooks.model_claude_hook_event import (
    HOOK_CAPTURE_NAMESPACE,
    make_content_record_id,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

lineage_mod = importlib.import_module("hook_claude_capture")
content_mod = importlib.import_module("hook_content_capture")
health = importlib.import_module("hook_emit_health")
journal = importlib.import_module("hook_emit_journal")
ident = content_mod.load_item_identity()
assert ident is not None, "the item-identity module must load by path"

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

SESSION = "session-ta21-1"
_REDACTION = (
    _REPO_ROOT / "src" / "omniclaude" / "hooks" / "contracts" / "capture_redaction.yaml"
)


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(lineage_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.delenv(content_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(lineage_mod, "lane_grant_pending", lambda: False)
    monkeypatch.setattr(content_mod, "onex_home", lambda: tmp_path / "no-onex")


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    health.write_status(
        content_mod.status_path_for(directory),
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("hook.event", "content.captured"),
        ),
    )
    return directory


def _records(journal_dir: Path, event_type: str) -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == event_type
    ]


def _barriers(journal_dir: Path) -> list[dict[str, Any]]:
    return [
        r
        for r in _records(journal_dir, ident.BARRIER_EVENT_TYPE)
        if r["content_kind"] == ident.BARRIER_CONTENT_KIND
    ]


def _lineage(hook_input: dict[str, Any], jdir: Path) -> None:
    assert lineage_mod.capture(dict(hook_input), journal_dir=jdir) == 1


def _content(kind: str, hook_input: dict[str, Any], jdir: Path) -> int:
    return content_mod.capture(dict(hook_input), kind=kind, journal_dir=jdir)


def _prompt(text: str) -> dict[str, Any]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": SESSION,
        "prompt": text,
        "prompt_id": "prompt-" + uuid.uuid4().hex[:8],
    }


def _tool(name: str, tool_use_id: str, *, post: bool) -> dict[str, Any]:
    base: dict[str, Any] = {
        "hook_event_name": "PostToolUse" if post else "PreToolUse",
        "session_id": SESSION,
        "tool_name": "Bash",
        "tool_use_id": tool_use_id,
        "tool_input": {"command": name},
    }
    if post:
        base["tool_response"] = {"interrupted": False, "output": "out of " + name}
    return base


def _refs(event: dict[str, Any]) -> dict[str, str]:
    """``field -> content_record_id`` of every reference in a lineage payload."""
    payload = event["payload"]
    return {
        ref["field"]: ref["content_record_id"]
        for key, ref in payload.items()
        if key.endswith("_ref") and isinstance(ref, dict)
    }


def test_the_module_imports_only_the_standard_library_at_module_level() -> None:
    """The hooks load it by path; a package import would cost 22 s cold."""
    tree = ast.parse(Path(ident.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.If):  # the TYPE_CHECKING block is not runtime
            assert ast.unparse(node.test) == "TYPE_CHECKING"
    assert imported <= set(sys.stdlib_module_names)


def test_the_node_handler_answers_each_operation(tmp_path: Path) -> None:
    from omniclaude.nodes.node_capture_item_identity_compute.handlers import (
        HandlerCaptureItemIdentity,
    )
    from omniclaude.nodes.node_capture_item_identity_compute.models import (
        EnumCaptureItemOperation,
        ModelCaptureItemIdentityRequest,
    )

    handler = HandlerCaptureItemIdentity()
    event_id = uuid.uuid4()
    common = {"item_dir": str(tmp_path), "session_id": SESSION}

    def ask(**fields: Any) -> Any:
        return handler.handle(ModelCaptureItemIdentityRequest(**common, **fields))

    got = handler.handle(
        ModelCaptureItemIdentityRequest(
            operation=EnumCaptureItemOperation.CONTENT_RECORD_ID,
            event_id=event_id,
            field="prompt",
        )
    )
    assert got.content_record_id == ident.content_record_id(event_id, "prompt")
    claimed = ask(
        operation=EnumCaptureItemOperation.CLAIM_EVENT_ID,
        hook_event_name="PostToolUse",
        discriminator="toolu-1",
        stream=ident.STREAM_LINEAGE,
        minted_event_id=event_id,
    )
    assert claimed.event_id == event_id
    seq = ask(
        operation=EnumCaptureItemOperation.NEXT_PRODUCER_SEQ,
        stream=ident.STREAM_CONTENT,
    )
    assert seq.sequence == 1
    top = ask(
        operation=EnumCaptureItemOperation.HIGH_WATER, stream=ident.STREAM_CONTENT
    )
    assert top.sequence == 1
    with pytest.raises(ValueError, match="needs session_id and item_dir"):
        handler.handle(
            ModelCaptureItemIdentityRequest(
                operation=EnumCaptureItemOperation.HIGH_WATER
            )
        )


def test_namespace_and_function_match_the_package() -> None:
    assert ident.HOOK_CAPTURE_NAMESPACE == HOOK_CAPTURE_NAMESPACE
    event_id = uuid.uuid4()
    assert ident.content_record_id(event_id, "prompt") == make_content_record_id(
        event_id, "prompt"
    )


def test_partner_adopts_the_first_hooks_event_id_in_either_order(
    tmp_path: Path,
) -> None:
    for first, second in (
        (ident.STREAM_LINEAGE, ident.STREAM_CONTENT),
        (ident.STREAM_CONTENT, ident.STREAM_LINEAGE),
    ):
        item_dir = tmp_path / f"items-{first}"
        mine, theirs = uuid.uuid4(), uuid.uuid4()
        kwargs: dict[str, Any] = {
            "session_id": SESSION,
            "agent_id": None,
            "hook_event_name": "PostToolUse",
            "discriminator": "toolu-1",
        }
        got_first = ident.claim_event_id(item_dir, stream=first, minted=mine, **kwargs)
        got_second = ident.claim_event_id(
            item_dir, stream=second, minted=theirs, **kwargs
        )
        assert got_first == got_second == mine


def test_one_stream_arriving_twice_opens_a_second_entry(tmp_path: Path) -> None:
    kwargs: dict[str, Any] = {
        "session_id": SESSION,
        "agent_id": None,
        "hook_event_name": "UserPromptSubmit",
        "discriminator": "same-text",
        "stream": ident.STREAM_LINEAGE,
    }
    first, second = uuid.uuid4(), uuid.uuid4()
    assert ident.claim_event_id(tmp_path, minted=first, **kwargs) == first
    assert ident.claim_event_id(tmp_path, minted=second, **kwargs) == second


def test_a_stale_entry_is_never_matched(tmp_path: Path) -> None:
    kwargs: dict[str, Any] = {
        "session_id": SESSION,
        "agent_id": None,
        "hook_event_name": "PostToolUse",
        "discriminator": "toolu-old",
    }
    old, new = uuid.uuid4(), uuid.uuid4()
    ident.claim_event_id(
        tmp_path, stream=ident.STREAM_LINEAGE, minted=old, now=1000.0, **kwargs
    )
    got = ident.claim_event_id(
        tmp_path,
        stream=ident.STREAM_CONTENT,
        minted=new,
        now=1000.0 + ident.ENTRY_TTL_SECONDS + 1,
        **kwargs,
    )
    assert got == new


def test_a_tools_input_joins_its_pre_event_and_its_result_its_post_event(
    jdir: Path,
) -> None:
    _lineage(_tool("ls", "toolu-9", post=False), jdir)
    _lineage(_tool("ls", "toolu-9", post=True), jdir)
    assert _content("tool", _tool("ls", "toolu-9", post=True), jdir) == 2

    events = _records(jdir, "hook.event")
    pre = next(e for e in events if e["hook_event_name"] == "PreToolUse")
    post = next(e for e in events if e["hook_event_name"] == "PostToolUse")
    by_kind = {r["content_kind"]: r for r in _records(jdir, "content.captured")}
    assert by_kind["tool_input"]["content_record_id"] == _refs(pre)["tool_input"]
    assert by_kind["tool_response"]["content_record_id"] == _refs(post)["tool_response"]


def test_every_full_capture_reference_resolves_to_exactly_one_content_record(
    jdir: Path,
) -> None:
    """A 50-turn session, content hook running before the lineage hook on half."""
    for turn in range(50):
        prompt = _prompt("same words" if turn % 2 else f"words {turn}")
        tool_id = f"toolu-{turn}"
        reply = f"reply {turn}"
        stop = {
            "hook_event_name": "Stop",
            "session_id": SESSION,
            "last_assistant_message": reply,
            "stop_hook_active": False,
        }
        steps = [
            ("prompt", prompt),
            ("tool", _tool("ls", tool_id, post=True)),
            ("stop", stop),
        ]
        _lineage(_tool("ls", tool_id, post=False), jdir)
        for kind, hook_input in steps:
            if turn % 2:
                _lineage(hook_input, jdir)
                _content(kind, hook_input, jdir)
            else:
                _content(kind, hook_input, jdir)
                _lineage(hook_input, jdir)

    records = _records(jdir, "content.captured")
    by_id: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_id.setdefault(record["content_record_id"], []).append(record)

    full_capture_refs = 0
    for event in _records(jdir, "hook.event"):
        name = event["hook_event_name"]
        for field, record_id in _refs(event).items():
            if not ident.is_full_capture(name, field):
                continue
            full_capture_refs += 1
            matches = by_id.get(record_id, [])
            assert len(matches) == 1, (name, field)
            assert matches[0]["chunk_count"] == 1
    # 50 prompts, 50 pre tool_inputs, 50 tool_responses, 50 replies.
    assert full_capture_refs == 200

    identical = [
        e
        for e in _records(jdir, "hook.event")
        if e["hook_event_name"] == "UserPromptSubmit"
    ]
    ids = [_refs(e)["prompt"] for e in identical]
    assert len(ids) == len(set(ids)) == 50


def test_chunks_of_one_item_share_its_content_record_id(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = "x" * 70000  # over the contract's 65,536-character chunk size
    hook_input = _prompt(big)
    _lineage(hook_input, jdir)
    written = _content("prompt", hook_input, jdir)
    assert written >= 2
    chunks = _records(jdir, "content.captured")
    assert len({c["content_record_id"] for c in chunks}) == 1
    assert sorted(c["chunk_index"] for c in chunks) == list(range(written))
    event = _records(jdir, "hook.event")[0]
    assert chunks[0]["content_record_id"] == _refs(event)["prompt"]


def test_operator_prompt_items_carry_no_lineage_identity(jdir: Path) -> None:
    assert ident.FULL_CAPTURE_BY_KIND.get("operator_prompt") is None


def _issue(args: tuple[str, str, int]) -> list[int]:
    directory, stream, count = args
    return [
        ident.next_producer_seq(Path(directory), SESSION, stream) for _ in range(count)
    ]


def test_eight_concurrent_writers_issue_1000_gap_free_sequence_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The budget is the production default's business; a loaded runner must not
    # turn this test into a lock-timeout test.
    monkeypatch.setenv("ONEX_HOOK_LOCK_WAIT_S", "60")
    jobs = [(str(tmp_path), ident.STREAM_CONTENT, 125)] * 8
    with multiprocessing.get_context("fork").Pool(8) as pool:
        issued = [n for batch in pool.map(_issue, jobs) for n in batch]
    assert sorted(issued) == list(range(1, 1001))
    assert ident.high_water(tmp_path, SESSION, ident.STREAM_CONTENT) == 1000
    assert ident.high_water(tmp_path, SESSION, ident.STREAM_LINEAGE) == 0


def test_producers_stamp_each_record_with_a_per_stream_sequence(jdir: Path) -> None:
    for n in range(3):
        hook_input = _prompt(f"prompt {n}")
        _lineage(hook_input, jdir)
        _content("prompt", hook_input, jdir)
    lineage = _records(jdir, "hook.event")
    content = _records(jdir, "content.captured")
    assert [e["producer_seq"] for e in lineage] == [1, 2, 3]
    assert {e["stream"] for e in lineage} == {ident.STREAM_LINEAGE}
    assert [c["producer_seq"] for c in content] == [1, 2, 3]
    assert {c["stream"] for c in content} == {ident.STREAM_CONTENT}


def test_barrier_states_each_streams_high_water(jdir: Path) -> None:
    for n in range(2):
        hook_input = _prompt(f"prompt {n}")
        _lineage(hook_input, jdir)
        _content("prompt", hook_input, jdir)
    _lineage(_tool("ls", "toolu-1", post=False), jdir)

    assert (
        lineage_mod.journal_session_barrier(SESSION, journal_dir=jdir, barrier_id="b1")
        == 2
    )
    barriers = {b["stream"]: b for b in _barriers(jdir)}
    assert barriers[ident.STREAM_LINEAGE]["high_water"] == 3
    assert barriers[ident.STREAM_CONTENT]["high_water"] == 2
    assert barriers[ident.STREAM_LINEAGE]["content_capture"] == "enabled"
    assert "content_capture" not in barriers[ident.STREAM_CONTENT]
    assert {b["barrier_id"] for b in barriers.values()} == {"b1"}
    assert {b["record_type"] for b in barriers.values()} == {"barrier"}
    # A barrier states a high-water; it consumes no sequence number.
    assert (
        ident.high_water(ident.item_dir_for(jdir), SESSION, ident.STREAM_LINEAGE) == 3
    )


def test_content_capture_off_marks_the_lineage_barrier_and_journals_no_content(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(content_mod.OPT_OUT_ENV, "0")
    hook_input = _prompt("private words")
    _lineage(hook_input, jdir)
    assert _content("prompt", hook_input, jdir) == 0
    assert (
        lineage_mod.journal_session_barrier(SESSION, journal_dir=jdir, barrier_id="b2")
        == 1
    )

    assert [
        r for r in _records(jdir, "content.captured") if r["content_kind"] != "barrier"
    ] == []
    (barrier,) = _barriers(jdir)
    assert barrier["stream"] == ident.STREAM_LINEAGE
    assert barrier["content_capture"] == "disabled"
    assert barrier["high_water"] == 1


def test_no_barrier_when_the_drainer_does_not_list_the_event_type(
    jdir: Path,
) -> None:
    health.write_status(
        content_mod.status_path_for(jdir),
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("hook.event",),
        ),
    )
    assert lineage_mod.journal_session_barrier(SESSION, journal_dir=jdir) == 0
    assert _barriers(jdir) == []


def test_barrier_cli_reads_the_session_from_stdin(
    jdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"session_id": SESSION, "barrier_id": "b3"})),
    )
    assert lineage_mod.main(["--barrier", "--journal-dir", str(jdir)]) == 0
    assert {b["barrier_id"] for b in _barriers(jdir)} == {"b3"}


def test_the_redaction_contract_classifies_every_new_field() -> None:
    topics = yaml.safe_load(_REDACTION.read_text(encoding="utf-8"))
    sections = topics.get("topics") or topics.get("sinks") or topics
    content = _fields_of(sections, "onex.cmd.omniintelligence.content-captured.v1")
    lineage = _fields_of(sections, "onex.evt.omniclaude.hook-event.v1")
    for name in (
        "content_record_id",
        "producer_seq",
        "stream",
        "record_type",
        "barrier_id",
        "high_water",
        "content_capture",
    ):
        assert content[name] == "capture_verbatim", name
    for name in ("producer_seq", "stream"):
        assert lineage[name] == "capture_verbatim", name


def test_the_fan_out_keeps_identity_sequence_and_barrier_fields_verbatim(
    jdir: Path,
) -> None:
    """Through the real transform, not the yaml: an unclassified field would hash."""
    from omniclaude.hooks.capture_redaction import redact_capture
    from omniclaude.hooks.topics import TopicBase

    hook_input = _prompt("words")
    _lineage(hook_input, jdir)
    _content("prompt", hook_input, jdir)
    lineage_mod.journal_session_barrier(SESSION, journal_dir=jdir, barrier_id="b9")

    (event,) = _records(jdir, "hook.event")
    out = redact_capture(event, topic=TopicBase.HOOK_EVENT.value)
    assert out["producer_seq"] == 1
    assert out["stream"] == ident.STREAM_LINEAGE

    for record in _records(jdir, "content.captured"):
        out = redact_capture(record, topic=TopicBase.CONTENT_CAPTURED.value)
        for name in (
            "content_record_id",
            "producer_seq",
            "stream",
            "barrier_id",
            "high_water",
            "content_capture",
            "record_type",
        ):
            if name in record:
                assert out[name] == record[name], name


def _fields_of(sections: Any, topic: str) -> dict[str, str]:
    def find(node: Any) -> dict[str, str] | None:
        if isinstance(node, dict):
            if topic in node and isinstance(node[topic], dict):
                fields = node[topic].get("fields")
                if isinstance(fields, dict):
                    return {str(k): str(v) for k, v in fields.items()}
            for value in node.values():
                found = find(value)
                if found is not None:
                    return found
        return None

    found = find(sections)
    assert found is not None, topic
    return found
