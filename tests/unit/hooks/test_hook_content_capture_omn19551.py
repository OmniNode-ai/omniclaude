# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Full-content hook capture (OMN-19551).

Every planted value is built by concatenation and holds ``FAKE``, so no
credential-shaped literal sits in this file.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import hook_content_capture as capture_mod  # noqa: E402
import hook_emit_append as appender  # noqa: E402
import hook_emit_health as health  # noqa: E402
import hook_emit_journal as journal  # noqa: E402

from omniclaude.hooks.capture_redaction import load_contract  # noqa: E402
from omniclaude.hooks.topics import TopicBase  # noqa: E402

SESSION = "0f0f0f0f-1111-2222-3333-444444444444"
GITHUB_FAKE = "gh" + "p_" + "FAKE" + "a1b2" * 9


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    _write_status(directory, ("content.captured", "prompt.submitted", "tool.executed"))
    return directory


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)


def _write_status(journal_dir: Path, types: tuple[str, ...] | None) -> None:
    health.write_status(
        capture_mod.status_path_for(journal_dir),
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=types,
        ),
    )


def _records(
    journal_dir: Path, event_type: str = "content.captured"
) -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == event_type
    ]


def _metadata(journal_dir: Path, event_type: str) -> str | None:
    return appender.append_event(
        event_type=event_type,
        payload={"session_id": SESSION},
        correlation_id=SESSION,
        cwd=None,
        actor=None,
        host_turn_id=None,
        agent_id=None,
        transcript_path=None,
        session_id=SESSION,
        journal_dir=str(journal_dir),
    )


# ---------------------------------------------------------------------------
# AC1 -- prompt and tool content, with the metadata record's turn
# ---------------------------------------------------------------------------


def test_content_capture_prompt_is_journalled_in_full_on_the_prompt_turn(
    jdir: Path,
) -> None:
    turn = _metadata(jdir, "prompt.submitted")
    prompt = "Refactor the parser.\n" + "x" * 5000

    written = capture_mod.capture(
        {"session_id": SESSION, "prompt": prompt}, kind="prompt", journal_dir=jdir
    )

    assert written == 1
    (record,) = _records(jdir)
    assert record["content"] == prompt
    assert record["content_kind"] == "prompt"
    assert record["turn_id"] == turn
    assert record["session_id"] == SESSION
    assert record["chunk_index"] == 0
    assert record["chunk_count"] == 1
    assert record["truncated"] is False


def test_content_capture_tool_input_and_result_carry_tool_use_id_and_turn(
    jdir: Path,
) -> None:
    turn = _metadata(jdir, "prompt.submitted")
    tool_turn = _metadata(jdir, "tool.executed")
    assert tool_turn == turn

    capture_mod.capture(
        {
            "session_id": SESSION,
            "tool_name": "Bash",
            "tool_use_id": "toolu_01",
            "tool_input": {"command": "git status", "description": "status"},
            "tool_response": {
                "stdout": "On branch dev\nnothing to commit",
                "stderr": "",
            },
        },
        kind="tool",
        journal_dir=jdir,
    )

    by_kind = {r["content_kind"]: r for r in _records(jdir)}
    assert set(by_kind) == {"tool_input", "tool_response"}
    for record in by_kind.values():
        assert record["tool_use_id"] == "toolu_01"
        assert record["turn_id"] == turn
        assert record["tool_name"] == "Bash"
        assert record["command"] == "git status"
    assert json.loads(by_kind["tool_input"]["content"])["command"] == "git status"
    assert "nothing to commit" in by_kind["tool_response"]["content"]


def test_content_capture_redacts_a_planted_secret_before_journalling(
    jdir: Path,
) -> None:
    capture_mod.capture(
        {"session_id": SESSION, "prompt": "use " + GITHUB_FAKE + " to push"},
        kind="prompt",
        journal_dir=jdir,
    )
    (record,) = _records(jdir)
    assert record["content"] == "use [REDACTED:github_token] to push"
    assert record["producer_redaction"] == {"github_token": 1}
    assert "FAKE" not in json.dumps(_records(jdir))


def test_content_capture_output_class_hashes_the_result_whole(jdir: Path) -> None:
    capture_mod.capture(
        {
            "session_id": SESSION,
            "tool_name": "Bash",
            "tool_use_id": "toolu_02",
            "tool_input": {"command": "kubectl get secret app -o json"},
            "tool_response": {"stdout": "plain looking output", "stderr": ""},
        },
        kind="tool",
        journal_dir=jdir,
    )
    for record in _records(jdir):
        assert str(record["content"]).startswith("sha256:")
        assert str(record["command"]).startswith("sha256:")
    assert "plain looking output" not in json.dumps(_records(jdir))


# ---------------------------------------------------------------------------
# AC3 -- redaction runs before chunking
# ---------------------------------------------------------------------------


def test_chunk_boundary_secret_is_redacted_in_every_chunk(jdir: Path) -> None:
    topic = TopicBase.CONTENT_CAPTURED.value
    chunk = load_contract().topics[topic].content_policy.chunk_chars
    key_body = ("FAKEKEYBODY" * 20 + "\n") * 4
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n" + key_body + "-----END RSA PRIVATE KEY-----"
    )
    # The block starts 100 characters before the first chunk boundary, so a
    # split-then-scrub would leave the key body alone in the second chunk.
    prompt = "a" * (chunk - 100) + pem + "\nafter"

    capture_mod.capture(
        {"session_id": SESSION, "prompt": prompt}, kind="prompt", journal_dir=jdir
    )

    records = sorted(_records(jdir), key=lambda r: r["chunk_index"])
    assert all("FAKEKEYBODY" not in r["content"] for r in records)
    joined = "".join(r["content"] for r in records)
    assert joined == "a" * (chunk - 100) + "[REDACTED:pem_private_key_block]\nafter"
    assert len({r["content_sha256"] for r in records}) == 1


def test_content_capture_fail_open_oversize_content_is_capped_and_marked(
    jdir: Path,
) -> None:
    policy = load_contract().topics[TopicBase.CONTENT_CAPTURED.value].content_policy
    capture_mod.capture(
        {"session_id": SESSION, "prompt": "y" * (policy.max_content_chars + 10)},
        kind="prompt",
        journal_dir=jdir,
    )
    records = _records(jdir)
    assert len(records) == policy.max_content_chars // policy.chunk_chars
    assert all(r["truncated"] is True for r in records)
    assert all(r["original_chars"] == policy.max_content_chars + 10 for r in records)


# ---------------------------------------------------------------------------
# the refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "types",
    [None, ("prompt.submitted", "tool.executed")],
    ids=["drainer_did_not_say", "drainer_registry_lacks_the_event"],
)
def test_content_capture_is_skipped_when_the_drainer_cannot_publish_it(
    jdir: Path, types: tuple[str, ...] | None
) -> None:
    _write_status(jdir, types)
    written = capture_mod.capture(
        {"session_id": SESSION, "prompt": "hello"}, kind="prompt", journal_dir=jdir
    )
    assert written == 0
    assert _records(jdir) == []


def test_content_capture_is_skipped_with_no_drainer_status(tmp_path: Path) -> None:
    directory = tmp_path / "s" / "hook_emit_journal"
    directory.mkdir(parents=True)
    assert (
        capture_mod.capture(
            {"session_id": SESSION, "prompt": "hi"},
            kind="prompt",
            journal_dir=directory,
        )
        == 0
    )


@pytest.mark.parametrize("value", ["0", "off", "false", "NO"])
def test_content_capture_honours_the_operator_opt_out(
    jdir: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(capture_mod.OPT_OUT_ENV, value)
    assert (
        capture_mod.capture(
            {"session_id": SESSION, "prompt": "hi"}, kind="prompt", journal_dir=jdir
        )
        == 0
    )


def test_content_capture_topic_comes_from_the_contract() -> None:
    resolver = capture_mod.load_resolver()
    assert resolver is not None
    assert capture_mod.content_topic(resolver) == TopicBase.CONTENT_CAPTURED.value


def test_content_capture_loads_the_resolver_without_the_heavy_package() -> None:
    probe = (
        "import sys; "
        f"sys.path.insert(0, {str(_LIB_DIR)!r}); "
        "import hook_content_capture as m; "
        "assert m.load_resolver() is not None; "
        "heavy = sorted(x for x in sys.modules "
        "if x.split('.')[0] in {'omnibase_infra', 'omnimarket', 'pydantic', 'aiokafka'}); "
        "print(','.join(heavy))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert out.stdout.strip() == ""


# ---------------------------------------------------------------------------
# AC2 -- the Stop hook's assistant reply
# ---------------------------------------------------------------------------


def _line(entry: dict[str, Any]) -> str:
    return json.dumps(entry)


def _transcript(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(_line(e) for e in entries) + "\n", encoding="utf-8")
    return path


def _user(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _tool_result() -> dict[str, Any]:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": "ok"}],
        },
    }


def _assistant(*blocks: dict[str, Any], sidechain: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type": "assistant",
        "message": {"role": "assistant", "content": list(blocks)},
    }
    if sidechain:
        entry["isSidechain"] = True
    return entry


def test_stop_content_capture_reads_the_last_turn_reply(
    jdir: Path, tmp_path: Path
) -> None:
    transcript = _transcript(
        tmp_path,
        [
            _user("first prompt"),
            _assistant({"type": "text", "text": "old reply"}),
            _user("second prompt"),
            _assistant(
                {"type": "thinking", "thinking": "private"},
                {"type": "text", "text": "Checking."},
                {"type": "tool_use", "id": "t", "name": "Bash", "input": {}},
            ),
            _tool_result(),
            _assistant({"type": "text", "text": "subagent chatter"}, sidechain=True),
            _assistant({"type": "text", "text": "Done: 3 tests pass."}),
        ],
    )
    turn = _metadata(jdir, "prompt.submitted")

    capture_mod.capture(
        {"session_id": SESSION, "transcript_path": str(transcript)},
        kind="stop",
        journal_dir=jdir,
    )

    (record,) = _records(jdir)
    assert record["content_kind"] == "assistant_reply"
    assert record["content"] == "Checking.\n\nDone: 3 tests pass."
    assert record["turn_id"] == turn


def test_stop_content_capture_prefers_the_harness_last_message(jdir: Path) -> None:
    capture_mod.capture(
        {"session_id": SESSION, "last_assistant_message": "direct reply"},
        kind="stop",
        journal_dir=jdir,
    )
    (record,) = _records(jdir)
    assert record["content"] == "direct reply"


def test_stop_content_capture_journals_nothing_when_there_is_no_reply(
    jdir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture_mod, "TRANSCRIPT_POLL_ATTEMPTS", 1)
    transcript = _transcript(tmp_path, [_user("a prompt with no reply yet")])
    items = capture_mod.items_for_stop({"transcript_path": str(transcript)}, attempts=1)
    assert items == []
    capture_mod.capture(
        {"session_id": SESSION, "transcript_path": str(tmp_path / "missing.jsonl")},
        kind="stop",
        journal_dir=jdir,
    )
    assert _records(jdir) == []


def test_stop_content_capture_records_one_reply_once(jdir: Path) -> None:
    for _ in range(2):
        capture_mod.capture(
            {"session_id": SESSION, "last_assistant_message": "same reply"},
            kind="stop",
            journal_dir=jdir,
        )
    assert len(_records(jdir)) == 1


# ---------------------------------------------------------------------------
# AC5 -- fail open
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stdin", ["not json", "[1, 2]", "", '{"session_id": 5}'])
def test_content_capture_fail_open_on_malformed_input(
    jdir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdin: str,
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = capture_mod.main(["--kind", "tool", "--journal-dir", str(jdir)])
    assert code == 0
    assert capsys.readouterr().out == ""
    assert _records(jdir) == []


def test_content_capture_fail_open_on_bad_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert capture_mod.main(["--kind", "nonsense"]) == 0
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# the Stop script, the drainer status and the drainer's registry read
# ---------------------------------------------------------------------------

_STOP_SCRIPT = (
    _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "stop_content_capture.sh"
)


def test_stop_content_capture_script_is_silent_and_never_blocks(tmp_path: Path) -> None:
    import os
    import time

    marker = tmp_path / "argv.txt"
    stub = tmp_path / "fake_python.sh"
    stub.write_text(
        f'#!/bin/bash\nprintf "%s\\n" "$@" > "{marker}"\ncat >/dev/null\nsleep 6\n'
    )
    stub.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
            "OMNICLAUDE_MODE": "full",
            "ONEX_STATE_DIR": str(tmp_path / "onex_state"),
            "PLUGIN_PYTHON_BIN": str(stub),
        }
    )
    payload = json.dumps(
        {"session_id": SESSION, "transcript_path": "/nonexistent.jsonl"}
    )
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(_STOP_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=20,
        env=env,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert time.monotonic() - started < 3.0
    deadline = time.monotonic() + 3.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    argv = marker.read_text().splitlines()
    assert argv[0].endswith("hook_content_capture.py")
    assert argv[argv.index("--kind") + 1] == "stop"


def test_drainer_status_round_trips_its_publishable_event_types(tmp_path: Path) -> None:
    path = tmp_path / health.STATUS_FILENAME
    health.write_status(
        path,
        health.ModelDrainerStatus(
            last_cycle_at=2.0,
            last_publish_at=1.0,
            published_total=3,
            pid=4,
            publishable_event_types=("content.captured", "tool.executed"),
        ),
    )
    status = health.read_status(path)
    assert status is not None
    assert status.publishable_event_types == ("content.captured", "tool.executed")


def test_an_older_drainer_status_reads_as_saying_nothing(tmp_path: Path) -> None:
    path = tmp_path / health.STATUS_FILENAME
    path.write_text(
        json.dumps(
            {
                "last_cycle_at": 1.0,
                "last_publish_at": None,
                "published_total": 0,
                "pid": 1,
            }
        )
    )
    status = health.read_status(path)
    assert status is not None
    assert status.publishable_event_types is None


def test_drainer_reads_the_installed_registry_event_types() -> None:
    import hook_emit_drainer as drainer

    types = drainer.publishable_event_types()
    assert types is not None
    assert "tool.executed" in types
    assert list(types) == sorted(types)
