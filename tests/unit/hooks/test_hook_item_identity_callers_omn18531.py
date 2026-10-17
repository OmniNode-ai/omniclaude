# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The two capture hooks call node_capture_item_identity_effect (OMN-18531, TA.21).

Each hook makes one call into the omnimarket node's stdlib-only handler, loaded
by file path from the installed omnimarket package: the lineage hook calls
``stamp_lineage_event`` and the content hook ``stamp_content_records``. These
tests hold the callers to the plan's TA.21 criteria that a producer can show:
the content record carries the ``content_record_id`` of the lineage reference
it fulfils, in either hook order; two identical prompts get two ids; each
stream's ``producer_seq`` counts 1, 2, 3 with no gap; and a hook that cannot
load the handler journals nothing rather than an unstamped record.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

lineage_mod = importlib.import_module("hook_claude_capture")
content_mod = importlib.import_module("hook_content_capture")
health = importlib.import_module("hook_emit_health")
journal = importlib.import_module("hook_emit_journal")

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

_STDIN = _REPO_ROOT / "tests" / "fixtures" / "hooks" / "claude_hook_capture" / "stdin"


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(lineage_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.delenv(content_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(lineage_mod, "lane_grant_pending", lambda: False)


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


def _prompt_stdin(prompt: str | None = None) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (_STDIN / "UserPromptSubmit.json").read_text(encoding="utf-8")
    )
    if prompt is not None:
        loaded["prompt"] = prompt
    return loaded


def _payloads(journal_dir: Path, event_type: str) -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == event_type
    ]


def _ref_ids(node: Any, field: str) -> list[str]:
    """Every ``content_record_id`` of a content reference to ``field``."""
    found: list[str] = []
    if isinstance(node, dict):
        if node.get("field") == field and node.get("content_record_id"):
            found.append(str(node["content_record_id"]))
        for value in node.values():
            found.extend(_ref_ids(value, field))
    elif isinstance(node, list):
        for value in node:
            found.extend(_ref_ids(value, field))
    return found


def _lineage(stdin: dict[str, Any], journal_dir: Path) -> None:
    assert lineage_mod.capture(stdin, journal_dir=journal_dir) == 1


def _content(stdin: dict[str, Any], journal_dir: Path) -> None:
    assert content_mod.capture(stdin, kind="prompt", journal_dir=journal_dir) >= 1


def test_the_item_identity_handler_loads_from_the_installed_omnimarket() -> None:
    module = content_mod.load_item_identity()
    assert module is not None
    assert Path(module.__file__).parts[-5:] == (
        "omnimarket",
        "nodes",
        "node_capture_item_identity_effect",
        "handlers",
        "handler_item_identity.py",
    )


@pytest.mark.parametrize("order", ["lineage_first", "content_first"])
def test_content_record_carries_the_lineage_reference_id(
    jdir: Path, order: str
) -> None:
    stdin = _prompt_stdin()
    first, second = (
        (_lineage, _content) if order == "lineage_first" else (_content, _lineage)
    )
    first(stdin, jdir)
    second(stdin, jdir)

    (event,) = _payloads(jdir, "hook.event")
    ref_ids = set(_ref_ids(event, "prompt"))
    assert len(ref_ids) == 1
    records = _payloads(jdir, "content.captured")
    assert records
    assert {r["content_record_id"] for r in records} == ref_ids


def test_two_identical_prompts_get_two_record_ids(jdir: Path) -> None:
    stdin = _prompt_stdin("the same words twice")
    for _ in range(2):
        _lineage(stdin, jdir)
        _content(stdin, jdir)

    events = _payloads(jdir, "hook.event")
    lineage_ids = [_ref_ids(event, "prompt")[0] for event in events]
    content_ids = [r["content_record_id"] for r in _payloads(jdir, "content.captured")]
    assert len(set(lineage_ids)) == 2
    assert content_ids == lineage_ids


def test_each_stream_counts_its_own_sequence_without_a_gap(jdir: Path) -> None:
    for text in ("one", "two", "three"):
        stdin = _prompt_stdin(text)
        _lineage(stdin, jdir)
        _content(stdin, jdir)

    events = _payloads(jdir, "hook.event")
    records = _payloads(jdir, "content.captured")
    assert [e["stream"] for e in events] == ["lineage"] * 3
    assert [e["producer_seq"] for e in events] == [1, 2, 3]
    assert {r["stream"] for r in records} == {"content"}
    assert [r["producer_seq"] for r in records] == list(range(1, len(records) + 1))


def test_a_hook_that_cannot_load_the_handler_journals_nothing(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(sys.modules, content_mod._ITEM_IDENTITY_MODULE_NAME, False)
    monkeypatch.setattr(content_mod, "package_files", lambda *_parts: [])
    stdin = _prompt_stdin()

    assert lineage_mod.capture(stdin, journal_dir=jdir) == 0
    assert content_mod.capture(stdin, kind="prompt", journal_dir=jdir) == 0
    assert _payloads(jdir, "hook.event") == []
    assert _payloads(jdir, "content.captured") == []
