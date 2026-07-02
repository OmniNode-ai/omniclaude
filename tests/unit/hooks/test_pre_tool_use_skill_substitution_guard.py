# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for pre_tool_use_skill_substitution_guard (OMN-13835).

Covers:
- Hard block: raw `gh pr merge` -> onex:auto_merge, with suggestion.
- Two-phase override: proceed-anyway retry allows and files friction.
- Stale override marker re-blocks.
- Warn: org-wide gh pr sweep -> onex:merge_sweep; bare Agent()/Task() ->
  onex:self_healing_dispatch.
- Pass-through: benign commands, non-matching gh subcommands, bad JSON.
- Rule loading from the shipped raw_command_to_skill.yaml.
- End-to-end friction append to the NDJSON registry on override.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from omniclaude.hooks.pre_tool_use_skill_substitution_guard import (
    OVERRIDE_WINDOW_SEC,
    SubstitutionRule,
    load_rules,
    run_guard,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bash_hook(command: str) -> str:
    return json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "s1"}
    )


def _agent_hook(prompt: str, tool: str = "Agent") -> str:
    return json.dumps(
        {
            "tool_name": tool,
            "tool_input": {"prompt": prompt, "subagent_type": "general-purpose"},
            "session_id": "s1",
        }
    )


class _Recorder:
    """Capture friction recorder invocations."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(
        self, rule: SubstitutionRule, command_text: str, session_id: str
    ) -> None:
        self.calls.append((rule.rule_id, command_text, session_id))


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_shipped_rules_load_and_contain_gh_pr_merge() -> None:
    rules = load_rules()
    assert rules, "raw_command_to_skill.yaml produced no rules"
    by_id = {r.rule_id: r for r in rules}
    assert "raw-gh-pr-merge" in by_id
    assert by_id["raw-gh-pr-merge"].severity == "block"
    assert by_id["raw-gh-pr-merge"].skill == "onex:auto_merge"


@pytest.mark.unit
def test_malformed_rules_yaml_returns_empty(tmp_path: Path) -> None:
    bad = tmp_path / "rules.yaml"
    bad.write_text("rules:\n  - id: broken\n    pattern: '['\n", encoding="utf-8")
    # Bad regex is skipped; result is an empty (but non-raising) rule list.
    assert load_rules(bad) == []


# ---------------------------------------------------------------------------
# Hard block: raw gh pr merge -> onex:auto_merge  (DoD)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_raw_gh_pr_merge_is_blocked_with_suggestion(tmp_path: Path) -> None:
    exit_code, output = run_guard(
        _bash_hook("gh pr merge 123 --squash --auto"),
        state_dir=tmp_path,
        now=1000.0,
    )
    assert exit_code == 2
    result = json.loads(output)
    assert result["decision"] == "block"
    assert "onex:auto_merge" in result["reason"]
    # A marker was stamped for the two-phase override.
    markers = list((tmp_path / "skill_substitution_guard").glob("*.override"))
    assert len(markers) == 1


@pytest.mark.unit
def test_proceed_anyway_allows_and_files_friction(tmp_path: Path) -> None:
    rec = _Recorder()
    cmd = "gh pr merge 123 --squash --auto"

    # First hit: blocked, marker written.
    code1, _ = run_guard(_bash_hook(cmd), state_dir=tmp_path, now=1000.0, record_fn=rec)
    assert code1 == 2
    assert rec.calls == []  # no friction on the block itself

    # Retry within window: operator proceed-anyway -> allow + friction.
    code2, out2 = run_guard(
        _bash_hook(cmd), state_dir=tmp_path, now=1030.0, record_fn=rec
    )
    assert code2 == 0
    assert json.loads(out2)["tool_name"] == "Bash"  # original passed through
    assert len(rec.calls) == 1
    rule_id, command_text, session_id = rec.calls[0]
    assert rule_id == "raw-gh-pr-merge"
    assert command_text == cmd
    assert session_id == "s1"
    # Marker cleared so the override is one-shot.
    assert list((tmp_path / "skill_substitution_guard").glob("*.override")) == []


@pytest.mark.unit
def test_stale_marker_reblocks(tmp_path: Path) -> None:
    rec = _Recorder()
    cmd = "gh pr merge 7"
    run_guard(_bash_hook(cmd), state_dir=tmp_path, now=1000.0, record_fn=rec)
    # Retry AFTER the override window: stale marker -> re-block, no friction.
    code, output = run_guard(
        _bash_hook(cmd),
        state_dir=tmp_path,
        now=1000.0 + OVERRIDE_WINDOW_SEC + 1,
        record_fn=rec,
    )
    assert code == 2
    assert json.loads(output)["decision"] == "block"
    assert rec.calls == []


# ---------------------------------------------------------------------------
# Warn: org-wide sweep -> onex:merge_sweep
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_gh_search_prs_warns_merge_sweep(tmp_path: Path) -> None:
    code, output = run_guard(
        _bash_hook("gh search prs --owner OmniNode-ai --state open"),
        state_dir=tmp_path,
    )
    assert code == 1
    result = json.loads(output)
    assert result["decision"] == "warn"
    assert "onex:merge_sweep" in result["reason"]


@pytest.mark.unit
def test_org_wide_gh_pr_list_warns_merge_sweep(tmp_path: Path) -> None:
    code, output = run_guard(
        _bash_hook("gh pr list --repo OmniNode-ai/omniclaude --state open"),
        state_dir=tmp_path,
    )
    assert code == 1
    assert "onex:merge_sweep" in json.loads(output)["reason"]


@pytest.mark.unit
def test_local_gh_pr_list_without_org_scope_passes(tmp_path: Path) -> None:
    # A plain, repo-local `gh pr list` (no org/search scope) is not a sweep.
    code, _ = run_guard(_bash_hook("gh pr list"), state_dir=tmp_path)
    assert code == 0


# ---------------------------------------------------------------------------
# Warn: bare Agent()/Task() -> self_healing_dispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bare_agent_warns_dispatch_skill(tmp_path: Path) -> None:
    code, output = run_guard(
        _agent_hook("Go fix the failing PR checks on OMN-1"), state_dir=tmp_path
    )
    assert code == 1
    assert "self_healing_dispatch" in json.loads(output)["reason"]


@pytest.mark.unit
def test_bare_task_warns_dispatch_skill(tmp_path: Path) -> None:
    code, output = run_guard(
        _agent_hook("Work this ticket", tool="Task"), state_dir=tmp_path
    )
    assert code == 1
    assert "self_healing_dispatch" in json.loads(output)["reason"]


# ---------------------------------------------------------------------------
# Pass-through / fail-open
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_benign_bash_passes(tmp_path: Path) -> None:
    code, output = run_guard(_bash_hook("ls -la"), state_dir=tmp_path)
    assert code == 0
    assert json.loads(output)["tool_name"] == "Bash"


@pytest.mark.unit
def test_gh_pr_view_passes(tmp_path: Path) -> None:
    code, _ = run_guard(_bash_hook("gh pr view 42 --json state"), state_dir=tmp_path)
    assert code == 0


@pytest.mark.unit
def test_invalid_json_fails_open() -> None:
    code, _ = run_guard("not-json{{{")
    assert code == 0


@pytest.mark.unit
def test_empty_tool_input_passes() -> None:
    code, _ = run_guard(json.dumps({"tool_name": "Bash", "tool_input": {}}))
    assert code == 0


@pytest.mark.unit
def test_non_matching_tool_passes(tmp_path: Path) -> None:
    hook = json.dumps(
        {"tool_name": "Read", "tool_input": {"file_path": "/x"}, "session_id": "s"}
    )
    code, _ = run_guard(hook, state_dir=tmp_path)
    assert code == 0


# ---------------------------------------------------------------------------
# End-to-end: friction is appended to the NDJSON registry on override
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_override_appends_to_friction_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    # Reset the friction recorder's cached default registry so it resolves the
    # tmp ONEX_STATE_DIR rather than a value cached by an earlier test.
    import sys

    shared = str(
        Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills" / "_shared"
    )
    if shared not in sys.path:
        sys.path.insert(0, shared)
    import friction_recorder  # type: ignore[import-not-found]

    friction_recorder._DEFAULT_REGISTRY = None  # noqa: SLF001

    cmd = "gh pr merge 999 --auto"
    marker_dir = tmp_path / "markers"
    # Block, then proceed-anyway (real recorder, no injected record_fn).
    run_guard(_bash_hook(cmd), state_dir=marker_dir, now=2000.0)
    code, _ = run_guard(_bash_hook(cmd), state_dir=marker_dir, now=2010.0)
    assert code == 0

    registry = tmp_path / "state" / "friction" / "friction.ndjson"
    assert registry.exists(), "friction NDJSON was not written"
    row: dict[str, Any] = json.loads(registry.read_text().strip().splitlines()[-1])
    assert row["skill"] == "skill_substitution_guard"
    assert row["surface"] == "tooling/skill-substitution-override"
    assert row["session_id"] == "s1"


# ---------------------------------------------------------------------------
# Hook-harness: the module CLI (the path the .sh wrapper invokes)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_module_cli_blocks_raw_gh_pr_merge(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "omniclaude.hooks.pre_tool_use_skill_substitution_guard",
        ],
        input=_bash_hook("gh pr merge 1 --auto"),
        capture_output=True,
        text=True,
        cwd=repo_root,
        env={"PATH": "/usr/bin:/bin", "ONEX_STATE_DIR": str(tmp_path)},
        check=False,
    )
    assert proc.returncode == 2
    assert "onex:auto_merge" in json.loads(proc.stdout.strip())["reason"]
