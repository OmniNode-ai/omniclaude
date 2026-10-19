# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The ``compact`` capture kind (OMN-21122, plan task TA.20b).

``hook_content_capture.py --kind compact`` runs at PostCompact. It asks
``node_compact_package_read_effect``'s handler, loaded by file path from the
installed omnimarket package, for the newest ``compact_boundary`` record of
``transcript_path`` and every record after it, and journals that package
unmodified through the same size policy, refusals and ``content.captured``
event as every other kind. The node's own reading rules are tested in omnimarket;
here a stand-in handler is placed where the loader looks, so these tests hold
whatever omnimarket release the environment pins.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import hook_content_capture as capture_mod
import hook_emit_health as health
import hook_emit_journal as journal
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

SESSION = "2b2b2b2b-3333-4444-5555-666666666666"
BOUNDARY_UUID = "783e1d6e-1111-2222-3333-444444444444"
REPLACEMENT_UUIDS = (
    "99990000-0000-0000-0000-000000000001",
    "99990000-0000-0000-0000-000000000002",
)
REPO_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_SCRIPT = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "claude_hook_capture.sh"
)

#: Stands in for the omnimarket handler: the file from the last line naming the
#: boundary subtype to the end, verbatim, as one compact item. The real one is tested in omnimarket.
STAND_IN_HANDLER = """\
from pathlib import Path


def compact_items(hook_input):
    path = hook_input.get("transcript_path")
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, TypeError):
        return []
    hits = [i for i, line in enumerate(lines) if '"compact_boundary"' in line]
    if not hits:
        return []
    package = "\\n".join(lines[hits[-1] :]) + "\\n"
    return [{"content_kind": "compact", "content": package}]
"""


def _boundary(uuid: str) -> str:
    # Spacing and key order are deliberately not canonical JSON: the capture
    # must keep the transcript's own bytes.
    return (
        '{"parentUuid": null, "type": "system", "subtype": "compact_boundary", '
        f'"uuid": "{uuid}", "compactMetadata": {{"trigger": "manual"}}}}'
    )


def _entry(kind: str, uuid: str, text: str) -> str:
    return json.dumps(
        {"type": kind, "uuid": uuid, "message": {"role": kind, "content": text}},
        ensure_ascii=False,
    )


def _transcript_lines() -> list[str]:
    return [
        _entry("user", "11110000-0000-0000-0000-000000000001", "an early prompt"),
        _boundary(BOUNDARY_UUID),
        _entry("user", REPLACEMENT_UUIDS[0], "summary café — kept"),
        _entry("assistant", REPLACEMENT_UUIDS[1], "ack"),
    ]


def _expected(lines: list[str]) -> str:
    start = max(i for i, line in enumerate(lines) if BOUNDARY_UUID in line)
    return "\n".join(lines[start:]) + "\n"


def _write_transcript(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _status(directory: Path, event_types: tuple[str, ...]) -> None:
    health.write_status(
        capture_mod.status_path_for(directory),
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=event_types,
        ),
    )


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    _status(directory, ("content.captured", "hook.event"))
    return directory


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    return _write_transcript(tmp_path / "session.jsonl", _transcript_lines())


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)
    handler = tmp_path / "stand_in" / "handler_compact_package_read.py"
    handler.parent.mkdir()
    handler.write_text(STAND_IN_HANDLER, encoding="utf-8")
    sys.modules.pop("omnimarket_compact_read", None)
    real = capture_mod.package_files

    def package_files(package: str, *parts: str) -> list[Path]:
        if parts[-1] == handler.name:
            return [handler]
        return real(package, *parts)

    monkeypatch.setattr(capture_mod, "package_files", package_files)


def _records(journal_dir: Path) -> list[dict[str, Any]]:
    records = [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == "content.captured"
    ]
    return sorted(records, key=lambda r: r["chunk_index"])


def _reassembled(records: list[dict[str, Any]]) -> str:
    return "".join(r["content"] for r in records)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hook_input(transcript: Path) -> dict[str, Any]:
    return {
        "session_id": SESSION,
        "hook_event_name": "PostCompact",
        "transcript_path": str(transcript),
    }


def test_post_compact_journals_the_newest_boundary_and_every_record_after_it(
    jdir: Path, transcript: Path
) -> None:
    written = capture_mod.capture(
        _hook_input(transcript), kind="compact", journal_dir=jdir, session_id=SESSION
    )

    assert written == 1
    records = _records(jdir)
    record = records[0]
    assert record["content_kind"] == "compact"
    assert record["hook_source"] == "compact"
    assert record["session_id"] == SESSION
    text = _reassembled(records)
    assert text == _expected(_transcript_lines())
    assert BOUNDARY_UUID in text
    for uuid in REPLACEMENT_UUIDS:
        assert uuid in text
    assert record["content_sha256"] == _sha(text)


def test_the_records_before_the_boundary_are_not_journalled(
    jdir: Path, transcript: Path
) -> None:
    capture_mod.capture(
        _hook_input(transcript), kind="compact", journal_dir=jdir, session_id=SESSION
    )

    text = _reassembled(_records(jdir))
    assert "an early prompt" not in text


def test_the_records_ride_unmodified(jdir: Path, transcript: Path) -> None:
    capture_mod.capture(
        _hook_input(transcript), kind="compact", journal_dir=jdir, session_id=SESSION
    )

    text = _reassembled(_records(jdir))
    # The boundary line keeps its own spacing and key order byte for byte.
    assert _boundary(BOUNDARY_UUID) + "\n" in text
    assert "café — kept" in text


def test_a_package_larger_than_one_chunk_reassembles_to_the_records(
    jdir: Path, tmp_path: Path
) -> None:
    lines = [_boundary(BOUNDARY_UUID)] + [
        _entry("user", f"77770000-0000-0000-0000-{n:012d}", "kept record " + "x" * 90)
        for n in range(1500)
    ]
    path = _write_transcript(tmp_path / "big.jsonl", lines)
    expected = "\n".join(lines) + "\n"
    assert len(expected) > 65536

    written = capture_mod.capture(
        _hook_input(path), kind="compact", journal_dir=jdir, session_id=SESSION
    )

    records = _records(jdir)
    assert written == len(records) > 1
    assert _sha(_reassembled(records)) == _sha(expected)


def test_main_reads_the_transcript_path_from_the_hook_input_on_stdin(
    jdir: Path, transcript: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_hook_input(transcript))))

    rc = capture_mod.main(["--kind", "compact", "--journal-dir", str(jdir)])

    assert rc == 0
    records = _records(jdir)
    assert _reassembled(records) == _expected(_transcript_lines())


def test_the_opt_out_switch_journals_no_compact_record(
    jdir: Path, transcript: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(capture_mod.OPT_OUT_ENV, "0")

    written = capture_mod.capture(
        _hook_input(transcript), kind="compact", journal_dir=jdir, session_id=SESSION
    )

    assert written == 0
    assert _records(jdir) == []


def test_a_drainer_that_cannot_publish_the_type_journals_no_compact_record(
    jdir: Path, transcript: Path
) -> None:
    _status(jdir, ("hook.event",))

    written = capture_mod.capture(
        _hook_input(transcript), kind="compact", journal_dir=jdir, session_id=SESSION
    )

    assert written == 0
    assert _records(jdir) == []


def test_a_transcript_with_no_boundary_journals_nothing(
    jdir: Path, tmp_path: Path
) -> None:
    path = _write_transcript(
        tmp_path / "plain.jsonl",
        [_entry("user", "11110000-0000-0000-0000-000000000001", "hello")],
    )

    assert (
        capture_mod.capture(
            _hook_input(path), kind="compact", journal_dir=jdir, session_id=SESSION
        )
        == 0
    )
    assert _records(jdir) == []


def _without_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """An omnimarket that carries every other node but not the compact reader.

    Only the reader's file is withheld: the resolver and the item-identity
    handler still load, so the capture reaches the compact read itself. Hiding
    every omnimarket file instead stops the capture at the item-identity load,
    before the compact read, and a test written that way passes for that reason.
    """
    sys.modules.pop("omnimarket_compact_read", None)
    real = capture_mod.package_files

    def package_files(package: str, *parts: str) -> list[Path]:
        if parts and parts[-1] == "handler_compact_package_read.py":
            return []
        return real(package, *parts)

    monkeypatch.setattr(capture_mod, "package_files", package_files)


def test_a_reader_that_is_not_installed_journals_nothing_and_fails_loud(
    jdir: Path, transcript: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An omnimarket without the node journals nothing, and says so by raising.

    On 2026-10-19 a session went through 27 compactions with no compact record:
    the hook interpreter's omnimarket predated the node, and the capture
    returned no items without a word. A missing reader is a dependency defect,
    so the capture names the node instead of passing for an empty package.
    """
    _without_the_reader(monkeypatch)

    with pytest.raises(ModuleNotFoundError, match="node_compact_package_read_effect"):
        capture_mod.capture(
            _hook_input(transcript),
            kind="compact",
            journal_dir=jdir,
            session_id=SESSION,
        )

    assert _records(jdir) == []


def test_main_exits_one_naming_the_node_when_the_reader_is_not_installed_fails_loud(
    jdir: Path,
    transcript: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 1 is what makes onex_emit_bounded raise its alarm (OMN-20110)."""
    _without_the_reader(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_hook_input(transcript))))

    rc = capture_mod.main(["--kind", "compact", "--journal-dir", str(jdir)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "content NOT journalled" in err
    assert "node_compact_package_read_effect" in err
    assert _records(jdir) == []


def test_a_missing_transcript_path_journals_nothing(jdir: Path, tmp_path: Path) -> None:
    for hook_input in (
        {"session_id": SESSION},
        {"session_id": SESSION, "transcript_path": str(tmp_path / "absent.jsonl")},
    ):
        assert (
            capture_mod.capture(
                hook_input, kind="compact", journal_dir=jdir, session_id=SESSION
            )
            == 0
        )
    assert _records(jdir) == []


def _run_capture_script(tmp_path: Path, payload: dict[str, Any]) -> list[list[str]]:
    """Run claude_hook_capture.sh with a recording stand-in for the interpreter.

    Returns the argv of every capture process the script started (the bounded
    emit runner itself runs on the real interpreter, as in the sibling tests).
    """
    log = tmp_path / "argv.log"
    stub = tmp_path / "fake_python.sh"
    stub.write_text(
        f'#!/bin/bash\ncase "$1" in *hook_emit_bounded.py) exec "{sys.executable}" "$@" ;; esac\n'
        f'printf "%s\\n" "$*" >> "{log}"\ncat >/dev/null\n'
    )
    stub.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "OMNICLAUDE_MODE": "full",
            "ONEX_STATE_DIR": str(tmp_path / "onex_state"),
            "PLUGIN_PYTHON_BIN": str(stub),
            "ONEX_HOOK_EMIT_BUDGET_S": "5",
            "ONEX_EMIT_ALARM_CMD": "/usr/bin/true",
            "ONEX_EMIT_EPISODE_MARKER": str(tmp_path / "episode"),
        }
    )
    result = subprocess.run(
        ["bash", str(CAPTURE_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    if not log.exists():
        return []
    return [line.split() for line in log.read_text().splitlines()]


def _content_capture_calls(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if c and c[0].endswith("hook_content_capture.py")]


def test_the_postcompact_capture_registration_runs_the_compact_kind(
    tmp_path: Path,
) -> None:
    """The existing PostCompact capture script also journals the compaction."""
    calls = _run_capture_script(
        tmp_path,
        {
            "session_id": SESSION,
            "hook_event_name": "PostCompact",
            "transcript_path": str(tmp_path / "t.jsonl"),
        },
    )

    metadata = [c for c in calls if c and c[0].endswith("hook_claude_capture.py")]
    content = _content_capture_calls(calls)
    assert len(metadata) == 1
    assert len(content) == 1
    assert content[0][content[0].index("--kind") + 1] == "compact"


@pytest.mark.parametrize("event", ["PreCompact", "SessionStart", "Notification"])
def test_no_other_event_starts_the_compact_capture(tmp_path: Path, event: str) -> None:
    calls = _run_capture_script(
        tmp_path, {"session_id": SESSION, "hook_event_name": event}
    )

    assert [c for c in calls if c and c[0].endswith("hook_claude_capture.py")]
    assert _content_capture_calls(calls) == []
