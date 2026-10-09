# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verdict parity of the relocated handler against the pre-relocation golden.

The golden was recorded from the shared-tree guard at c13a44482. A committed
fixture keeps these tests usable in shallow CI checkouts, where ``git show``
cannot read that historical object.

To re-record, load the pre-relocation module and its shell_words dependency and
policy from ``git show c13a44482:<path>`` into a temporary directory preserving
the lib/config layout. Run ``observe_cases(module, tmp_path, monkeypatch)`` and
write ``{"recorded_from": <source paths and revision>, "cases": <observations>}``
as JSON to the golden fixture. Historical git objects are needed only for this
one-time recording, never when running the parity tests.
"""

from __future__ import annotations

import dataclasses
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from omniclaude.nodes.node_git_effect.handlers import handler_git_admission as guard
from omniclaude.nodes.node_git_effect.models.model_git_admission import (
    ModelGitAdmissionRequest,
)
from tests.hooks.test_dirty_path_restore_guard import _git, _init

pytestmark = pytest.mark.unit

GOLDEN = Path(__file__).with_name("fixtures") / "git_admission_parity_golden.json"

REGISTRY_COMMANDS = [
    "git reset --hard origin/main",
    "git clean -fd",
    "git checkout -b feature",
    "git switch main",
    "git rebase origin/main",
    "git merge origin/main",
    "git merge --ff-only origin/main",
    "git status",
    "git diff",
    "git push origin feature",
    "git push --force origin main",
    "git checkout -- docs/tracking/ROLLING_WORK_LEDGER.md",
    "git branch -d main",
    "git branch feature",
    "echo 'git reset --hard'",
    "# git reset\ngit status",
    "git reset 'unterminated",
    "printf 'unterminated",
    "git -C . reset --hard",
    "cd ../sibling && git reset --hard",
]
RESTORE_COMMANDS = [
    "git restore file.txt",
    "git checkout HEAD -- file.txt",
    "git restore --staged file.txt",
]
FETCH_COMMANDS = [
    "git fetch origin",
    "git pull --ff-only origin main",
    "git ls-remote origin",
    "git remote update origin",
    "git push origin feature",
]
PAYLOADS = [
    "broken JSON",
    "[]",
    "{}",
    '{"tool_input":{"command":"echo hello"}}',
    '{"tool_input":{"command":"git status"},"cwd":"/nonexistent-parity"}',
]


def observe_cases(
    module: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine_label: str = "<ENGINE>",
) -> dict[str, dict[str, Any]]:
    """Observe the same isolated corpus through either guard module's public API."""
    policy = module.load_policy()
    cases = [
        (f"registry:{n}", "registry", command, False)
        for n, command in enumerate(REGISTRY_COMMANDS)
    ]
    cases.extend(
        (f"restore:{'dirty' if dirty else 'clean'}:{n}", "restore", command, dirty)
        for dirty in (False, True)
        for n, command in enumerate(RESTORE_COMMANDS)
    )
    cases.extend(
        (f"fetch:{n}", "fetch", command, False)
        for n, command in enumerate(FETCH_COMMANDS)
    )
    cases.extend(
        (f"payload:{n}", "payload", raw, False) for n, raw in enumerate(PAYLOADS)
    )
    observed: dict[str, dict[str, Any]] = {}
    with monkeypatch.context() as engine_patch:
        if "clone_sync_engine" in {
            field.name for field in dataclasses.fields(module.Policy)
        }:
            policy = dataclasses.replace(policy, clone_sync_engine=engine_label)
        else:
            engine_patch.setattr(module, "CLONE_SYNC_ENGINE", Path(engine_label))

        for case_id, scenario, command, dirty in cases:
            with monkeypatch.context() as case_patch:
                for name in (
                    *policy.fetch_lane_envs,
                    *policy.worktree_root_envs,
                    *policy.registry_root_envs,
                    "CLAUDE_PROJECT_DIR",
                    "OMNI_HOME",
                ):
                    case_patch.delenv(name, raising=False)
                case_patch.setenv("ONEX_STATE_DIR", str(tmp_path / "state" / case_id))
                case_dir = tmp_path / case_id
                case_dir.mkdir()
                registry_root: Path | None = None
                target: Path | None = None
                original = ""

                if scenario == "registry":
                    registry_root = case_dir / "registry"
                    (registry_root / ".git").mkdir(parents=True)
                    (registry_root / ".git" / "HEAD").write_text(
                        "ref: refs/heads/main\n"
                    )
                    # A second repository beside the registry, so a command that
                    # leaves the registry reaches a git root inside tmp_path on
                    # every host (a stray /tmp/.git must not change a verdict).
                    (case_dir / "sibling" / ".git").mkdir(parents=True)
                    (case_dir / "sibling" / ".git" / "HEAD").write_text(
                        "ref: refs/heads/main\n"
                    )
                    case_patch.setenv("OMNI_HOME", str(registry_root))
                    cwd = registry_root
                elif scenario == "restore":
                    registry_root = case_dir / "fleet"
                    cwd = registry_root / "repo"
                    _init(cwd)
                    target = cwd / "file.txt"
                    target.write_text("committed\n")
                    _git("add", "file.txt", cwd=cwd)
                    _git("commit", "-qm", "fixture", cwd=cwd)
                    if dirty:
                        target.write_text("uncommitted\n")
                    original = target.read_text()
                    case_patch.setenv("OMNI_HOME", str(registry_root))
                elif scenario == "fetch":
                    cwd = case_dir / "repo"
                    _init(cwd)
                    _git(
                        "remote",
                        "add",
                        "origin",
                        "https://github.com/OmniNode-ai/omniclaude.git",
                        cwd=cwd,
                    )
                    case_patch.setenv("ONEX_LANE", "parity-lane")
                else:
                    case_patch.setattr(sys, "stdin", io.StringIO(command))
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        exit_code = module.main([])
                    text = stdout.getvalue().replace(str(tmp_path), "<TMP>")
                    observed[case_id] = {
                        "exit": exit_code,
                        "stdout": json.loads(text) if text else None,
                    }
                    continue

                decision = module.evaluate_bash_command(
                    command, policy, cwd, registry_root, ()
                )
                if target is not None:
                    assert target.read_text() == original, case_id
                observed[case_id] = {
                    "blocked": decision.blocked,
                    "reason": decision.reason.replace(str(tmp_path), "<TMP>"),
                    "notes": [
                        note.replace(str(tmp_path), "<TMP>") for note in decision.notes
                    ],
                }
    return observed


def test_golden_names_its_source() -> None:
    golden = json.loads(GOLDEN.read_text())
    assert "c13a44482" in golden["recorded_from"]
    assert "plugins/onex/hooks/lib/shared_tree_git_guard.py" in golden["recorded_from"]
    assert len(golden["cases"]) >= 35


def test_relocated_guard_matches_pre_relocation_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = observe_cases(guard, tmp_path, monkeypatch)
    expected = json.loads(GOLDEN.read_text())["cases"]
    # OMN-18936: a tokeniser refusal names the failed segment and its syntax
    # error. The golden stays the pre-relocation record; only this wording moved.
    expected["registry:16"]["reason"] = expected["registry:16"]["reason"].replace(
        "could not be tokenised (an unbalanced quote, most likely)",
        "could not be tokenised in the segment starting at line 1, column 1 "
        "(unterminated single quote)",
    )
    assert set(observed) == set(expected)
    for case_id in observed:
        assert observed[case_id] == expected[case_id], case_id


class _ThroughHandler:
    """The guard module's API, with every verdict produced by the typed handler.

    ``HandlerGitAdmission.handle`` resolves the registry and worktree roots from
    the environment, which ``observe_cases`` sets per scenario, so the explicit
    roots it passes are not forwarded.
    """

    Policy = guard.Policy
    load_policy = staticmethod(guard.load_policy)
    main = staticmethod(guard.main)

    @staticmethod
    def evaluate_bash_command(
        command: str,
        policy: guard.Policy,
        cwd: Path,
        _registry_root: Path | None,
        _worktree_roots: tuple[Path, ...],
    ) -> guard.Decision:
        result = guard.HandlerGitAdmission().handle(
            ModelGitAdmissionRequest(
                raw_payload=json.dumps(
                    {"tool_input": {"command": command}, "cwd": str(cwd)}
                ),
                clone_sync_engine=policy.clone_sync_engine,
            )
        )
        return guard.Decision(
            blocked=result.blocked, reason=result.reason, notes=tuple(result.notes)
        )


def test_typed_handler_matches_pre_relocation_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The definition-B handler and the runtime-routed hook entry point both
    return the recorded verdict for every case (payload cases run ``main``,
    which dispatches through the contract-declared in-memory runtime)."""
    observed = observe_cases(_ThroughHandler, tmp_path, monkeypatch)
    expected = json.loads(GOLDEN.read_text())["cases"]
    assert set(observed) == set(expected)
    for case_id in observed:
        assert observed[case_id] == expected[case_id], case_id


def test_corpus_discriminates() -> None:
    cases = json.loads(GOLDEN.read_text())["cases"]
    registry = [case for key, case in cases.items() if key.startswith("registry:")]
    fetch = [case for key, case in cases.items() if key.startswith("fetch:")]
    payload = [case for key, case in cases.items() if key.startswith("payload:")]
    assert any(case["blocked"] for case in registry)
    assert any(not case["blocked"] for case in registry)
    assert any(case["blocked"] for case in fetch)
    assert any(case["exit"] == 2 for case in payload)
    assert any(case["exit"] == 0 for case in payload)
