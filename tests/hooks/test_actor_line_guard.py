# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the actor-line comment guard [OMN-13856].

Ruling: docs/tracking/ROLLING_WORK_LEDGER.md:4344, item (4) -- "agent-posted
Linear comments begin with an actor line naming the posting agent, enforced
rather than advised." Pure ``decide()`` tests -- no I/O boundary to stub, the
guard is a pure function of the tool-call payload.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_LIB_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"


def _load_guard() -> Any:
    import sys

    sys.path.insert(0, str(_LIB_DIR))
    spec = importlib.util.spec_from_file_location(
        "actor_line_guard", _LIB_DIR / "actor_line_guard.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["actor_line_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def _call(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": tool_name, "tool_input": tool_input}


# --------------------------------------------------------------------------- #
# Pass-through: not a covered tool
# --------------------------------------------------------------------------- #


def test_non_linear_tool_allowed() -> None:
    decision = guard.decide(_call("Bash", {"command": "echo hi"}))
    assert decision.allowed
    assert decision.reason == "not_comment_tool"


def test_other_linear_tool_allowed() -> None:
    # save_issue is gated by a different hook (done_flip_guard /
    # ticket_creation_gate) -- this guard does not touch it.
    decision = guard.decide(
        _call("mcp__linear-server__save_issue", {"id": "OMN-1", "state": "Done"})
    )
    assert decision.allowed
    assert decision.reason == "not_comment_tool"


def test_missing_tool_input_blocked() -> None:
    # tool_input entirely absent on a covered tool still resolves to "no
    # body", and an unverifiable actor line is refused, not assumed --
    # consistent with the fail-closed posture every other guard in this tree
    # takes on a payload it cannot evaluate.
    decision = guard.decide({"tool_name": "mcp__linear-server__save_comment"})
    assert not decision.allowed
    assert "empty_body" in decision.reason


def test_non_dict_tool_input_allowed() -> None:
    decision = guard.decide(
        {"tool_name": "mcp__linear-server__save_comment", "tool_input": "not-a-dict"}
    )
    assert decision.allowed


# --------------------------------------------------------------------------- #
# save_comment
# --------------------------------------------------------------------------- #


def test_save_comment_missing_actor_line_blocked() -> None:
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_comment",
            {"issueId": "OMN-1", "body": "Landed the fix, no state change."},
        )
    )
    assert not decision.allowed
    assert "missing_actor_line" in decision.reason


def test_save_comment_well_formed_actor_line_allowed() -> None:
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_comment",
            {
                "issueId": "OMN-1",
                "body": "actor: guard-fp-fix (claude-opus-5-5)\n\nLanded the fix.",
            },
        )
    )
    assert decision.allowed
    assert decision.reason == "actor_line_present"


def test_save_comment_actor_line_case_insensitive() -> None:
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_comment",
            {
                "issueId": "OMN-1",
                "body": "Actor: sealed-review-audit (claude-opus-5.5)",
            },
        )
    )
    assert decision.allowed


def test_save_comment_empty_body_blocked() -> None:
    decision = guard.decide(
        _call("mcp__linear-server__save_comment", {"issueId": "OMN-1", "body": ""})
    )
    assert not decision.allowed
    assert "empty_body" in decision.reason


def test_save_comment_whitespace_only_body_blocked() -> None:
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_comment", {"issueId": "OMN-1", "body": "   \n  "}
        )
    )
    assert not decision.allowed
    assert "empty_body" in decision.reason


def test_save_comment_actor_line_must_be_first_line() -> None:
    # A well-formed actor line buried in the SECOND line does not count --
    # the ruling requires the comment to OPEN with it.
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_comment",
            {
                "issueId": "OMN-1",
                "body": "Landed the fix.\nactor: guard-fp-fix (claude-opus-5-5)",
            },
        )
    )
    assert not decision.allowed
    assert "missing_actor_line" in decision.reason


def test_save_comment_edit_path_also_gated() -> None:
    # An update to an existing comment (id set) is not exempt.
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_comment",
            {"id": "comment-123", "body": "Updated text, no actor line."},
        )
    )
    assert not decision.allowed


def test_save_comment_missing_parens_blocked() -> None:
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_comment",
            {"issueId": "OMN-1", "body": "actor: guard-fp-fix claude-opus-5-5"},
        )
    )
    assert not decision.allowed
    assert "missing_actor_line" in decision.reason


def test_save_comment_actor_prefix_of_another_word_blocked() -> None:
    # "actors:" is not "actor:" -- the guard matches the exact fixed token,
    # not a prefix.
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_comment",
            {"issueId": "OMN-1", "body": "actors: guard-fp-fix (claude-opus-5-5)"},
        )
    )
    assert not decision.allowed


# --------------------------------------------------------------------------- #
# save_diff_comment
# --------------------------------------------------------------------------- #


def test_save_diff_comment_missing_actor_line_blocked() -> None:
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_diff_comment",
            {
                "urlOrId": "https://github.com/OmniNode-ai/omniclaude/pull/1",
                "body": "lgtm",
            },
        )
    )
    assert not decision.allowed
    assert "missing_actor_line" in decision.reason


def test_save_diff_comment_well_formed_allowed() -> None:
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_diff_comment",
            {
                "urlOrId": "https://github.com/OmniNode-ai/omniclaude/pull/1",
                "body": "actor: pr-review-bot (claude-sonnet-5)\n\nlgtm",
            },
        )
    )
    assert decision.allowed


def test_save_diff_comment_draft_still_gated() -> None:
    # A private persisted draft is not exempt -- see module docstring: this
    # guard enforces uniformly regardless of the draft flag.
    decision = guard.decide(
        _call(
            "mcp__linear-server__save_diff_comment",
            {
                "urlOrId": "https://github.com/OmniNode-ai/omniclaude/pull/1",
                "body": "no actor line here",
                "draft": True,
            },
        )
    )
    assert not decision.allowed


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #


def test_first_line_strips_and_splits() -> None:
    assert guard.first_line("  hello\nworld  ") == "hello"
    assert guard.first_line("") == ""
    assert guard.first_line(None) == ""  # type: ignore[arg-type]


def test_has_actor_line_true_and_false() -> None:
    assert guard.has_actor_line("actor: x (y)\nrest")
    assert not guard.has_actor_line("no actor line\nactor: x (y)")
    assert not guard.has_actor_line("")


# --------------------------------------------------------------------------- #
# main() / stdin entrypoint
# --------------------------------------------------------------------------- #


def test_main_blocks_and_exits_2(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    import io
    import json

    payload = json.dumps(
        _call(
            "mcp__linear-server__save_comment", {"issueId": "OMN-1", "body": "no actor"}
        )
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    rc = guard.main()
    assert rc == 2
    captured = capsys.readouterr()
    assert '"decision": "block"' in captured.err
    assert "OMN-13856 actor-line comment guard" in captured.err


def test_main_allows_and_exits_0(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import json

    payload = json.dumps(_call("Bash", {"command": "echo hi"}))
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    rc = guard.main()
    assert rc == 0


def test_main_malformed_stdin_allows() -> None:
    import io
    import sys as _sys

    old_stdin = _sys.stdin
    _sys.stdin = io.StringIO("not json{{{")
    try:
        rc = guard.main()
    finally:
        _sys.stdin = old_stdin
    assert rc == 0
