# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Direct tests for the PostToolUse aislop blocking gate."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_SCRIPTS = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"
if str(_HOOK_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_HOOK_SCRIPTS))

from post_tool_use_aislop_gate import run_gate, scan_content


def _write_hook(file_path: str, content: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": content},
        }
    )


def _edit_hook(file_path: str, new_string: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": file_path,
                "old_string": "old",
                "new_string": new_string,
            },
        }
    )


def _blocked(raw_json: str) -> dict[str, object]:
    exit_code, output = run_gate(raw_json)
    assert exit_code == 2
    result = json.loads(output)
    assert result["decision"] == "block"
    return result


def _local_user_path() -> str:
    return "/" + "Users/example/Code/omni_home"


@pytest.mark.unit
def test_hardcoded_path_blocks_without_local_path_annotation() -> None:
    result = _blocked(
        _write_hook(
            "/repo/src/service.py",
            f'ROOT = "{_local_user_path()}"\n',
        )
    )

    assert result["findings"][0]["check"] == "hardcoded-paths"


@pytest.mark.unit
def test_local_path_annotation_allows_hardcoded_path() -> None:
    raw = _write_hook(
        "/repo/src/service.py",
        f'ROOT = "{_local_user_path()}"  # local-path-ok\n',
    )

    exit_code, output = run_gate(raw)

    assert exit_code == 0
    assert output == raw


@pytest.mark.unit
def test_hardcoded_topic_literal_blocks() -> None:
    result = _blocked(
        _write_hook(
            "/repo/src/topics.py",
            'topic = "onex.evt.omniclaude.changed.v1"\n',
        )
    )

    assert result["findings"][0]["check"] == "hardcoded-topics"


@pytest.mark.unit
def test_bare_except_blocks() -> None:
    result = _blocked(
        _edit_hook(
            "/repo/src/worker.py",
            "try:\n    run()\nexcept:\n    recover()\n",
        )
    )

    assert result["findings"][0]["check"] == "bare-except"


@pytest.mark.unit
def test_typed_except_is_allowed() -> None:
    raw = _edit_hook(
        "/repo/src/worker.py",
        "try:\n    run()\nexcept ValueError:\n    recover()\n",
    )

    exit_code, output = run_gate(raw)

    assert exit_code == 0
    assert output == raw


@pytest.mark.unit
def test_empty_impl_in_src_blocks() -> None:
    result = _blocked(
        _write_hook(
            "/repo/src/omniclaude/service.py",
            "def process_event() -> None:\n    pass\n",
        )
    )

    assert result["findings"][0]["check"] == "empty-impls"


@pytest.mark.unit
def test_empty_init_and_abstractmethod_are_allowed() -> None:
    findings = scan_content(
        "/repo/src/omniclaude/service.py",
        "from abc import abstractmethod\n\n"
        "class Base:\n"
        "    def __init__(self) -> None:\n"
        "        pass\n\n"
        "    @abstractmethod\n"
        "    def process_event(self) -> None:\n"
        "        pass\n",
    )

    assert [finding["check"] for finding in findings] == []


@pytest.mark.unit
def test_empty_impl_outside_src_or_under_tests_is_allowed() -> None:
    raw = _write_hook(
        "/repo/tests/test_worker.py",
        "def test_placeholder() -> None:\n    pass\n",
    )

    exit_code, output = run_gate(raw)

    assert exit_code == 0
    assert output == raw


@pytest.mark.unit
def test_gate_disabled_exits_zero_without_checking_content() -> None:
    raw = _write_hook(
        "/repo/src/service.py",
        'topic = "onex.evt.omniclaude.changed.v1"\n'
        "def process_event() -> None:\n"
        "    pass\n",
    )

    exit_code, output = run_gate(raw, gate_enabled=False)

    assert exit_code == 0
    assert output == raw


@pytest.mark.unit
def test_multiedit_content_is_checked() -> None:
    raw = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": "/repo/src/service.py",
                "edits": [
                    {"old_string": "old", "new_string": "value = 1\n"},
                    {
                        "old_string": "old",
                        "new_string": "def process_event() -> None:\n    pass\n",
                    },
                ],
            },
        }
    )

    result = _blocked(raw)

    assert result["findings"][0]["check"] == "empty-impls"


@pytest.mark.unit
def test_1000_line_file_completes_under_100ms() -> None:
    content = "\n".join(f"value_{i} = {i}" for i in range(999))
    content = f"{content}\ntry:\n    run()\nexcept:\n    recover()\n"
    raw = _write_hook("/repo/src/worker.py", content)

    started = time.perf_counter()
    exit_code, output = run_gate(raw)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert exit_code == 2
    assert json.loads(output)["findings"][0]["check"] == "bare-except"
    assert elapsed_ms < 100
