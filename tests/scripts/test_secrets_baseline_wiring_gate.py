# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the secrets-baseline wiring gate (OMN-18669).

RED-first finding this pins: `omnimemory` carried a committed `.secrets.baseline`
that no pre-commit hook and no CI workflow read. A full scan against that
baseline surfaced 47 findings in 18 files nothing had ever approved, while the
repository looked protected because the file was there.

The gate's invariant is the WIRING, not the scan. These tests pin the four
verdicts that matter -- no baseline passes, both halves pass, either half
missing fails, and prose that merely mentions the baseline is not a reader
(CLAUDE.md rule 15) -- plus the fail-closed and positive-control behaviour that
keeps a broken matcher from reporting a clean bill of health (rule 16).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_GATE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "secrets_baseline_wiring_gate.py"
)

_spec = importlib.util.spec_from_file_location(
    "secrets_baseline_wiring_gate", _GATE_PATH
)
assert _spec is not None and _spec.loader is not None
mod = importlib.util.module_from_spec(_spec)
sys.modules["secrets_baseline_wiring_gate"] = mod
_spec.loader.exec_module(mod)


PRECOMMIT_READER = """\
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline', '--no-verify']
"""

WORKFLOW_READER = """\
jobs:
  detect-secrets:
    steps:
      - run: detect-secrets-hook --baseline .secrets.baseline
"""


def _write_repo(
    root: Path,
    *,
    baseline: bool,
    precommit: str | None,
    workflows: dict[str, str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if baseline:
        (root / ".secrets.baseline").write_text('{"results": {}}\n')
    if precommit is not None:
        (root / ".pre-commit-config.yaml").write_text(precommit)
    if workflows:
        wf_dir = root / ".github" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        for name, text in workflows.items():
            (wf_dir / name).write_text(text)
    return root


@pytest.mark.unit
def test_no_baseline_passes(tmp_path: Path) -> None:
    """The gate never demands a baseline -- only that a present one is read."""
    repo = _write_repo(tmp_path / "repo", baseline=False, precommit="repos: []\n")
    assert mod.main(["--repo-root", str(repo)]) == 0


@pytest.mark.unit
def test_both_halves_wired_passes(tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path / "repo",
        baseline=True,
        precommit=PRECOMMIT_READER,
        workflows={"ci.yml": WORKFLOW_READER},
    )
    assert mod.main(["--repo-root", str(repo)]) == 0


@pytest.mark.unit
def test_baseline_with_no_reader_at_all_fails(tmp_path: Path) -> None:
    """The measured omnimemory state: file present, nothing reading it."""
    repo = _write_repo(
        tmp_path / "repo",
        baseline=True,
        precommit="repos:\n  - repo: local\n    hooks:\n      - id: ruff\n",
        workflows={"ci.yml": "jobs:\n  lint:\n    runs-on: ubuntu-latest\n"},
    )
    assert mod.main(["--repo-root", str(repo)]) == 1


@pytest.mark.unit
def test_ci_half_alone_fails(tmp_path: Path) -> None:
    """A CI-only gate finds the credential after it has left the machine."""
    repo = _write_repo(
        tmp_path / "repo",
        baseline=True,
        precommit="repos:\n  - repo: local\n    hooks:\n      - id: ruff\n",
        workflows={"ci.yml": WORKFLOW_READER},
    )
    assert mod.main(["--repo-root", str(repo)]) == 1


@pytest.mark.unit
def test_local_half_alone_fails(tmp_path: Path) -> None:
    """A local-only gate is skippable and never sees another machine's commit."""
    repo = _write_repo(
        tmp_path / "repo",
        baseline=True,
        precommit=PRECOMMIT_READER,
        workflows={"ci.yml": "jobs:\n  lint:\n    runs-on: ubuntu-latest\n"},
    )
    assert mod.main(["--repo-root", str(repo)]) == 1


@pytest.mark.unit
def test_missing_precommit_config_fails(tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path / "repo",
        baseline=True,
        precommit=None,
        workflows={"ci.yml": WORKFLOW_READER},
    )
    assert mod.main(["--repo-root", str(repo)]) == 1


@pytest.mark.unit
def test_comment_mentioning_the_baseline_is_not_a_reader(tmp_path: Path) -> None:
    """Rule 15: prose that MENTIONS a trigger must not satisfy a gate scanning for it."""
    repo = _write_repo(
        tmp_path / "repo",
        baseline=True,
        precommit="# TODO: someday read .secrets.baseline here\nrepos: []\n",
        workflows={
            "ci.yml": "# detect-secrets-hook is not wired in this repo\njobs: {}\n"
        },
    )
    assert mod.main(["--repo-root", str(repo)]) == 1


@pytest.mark.unit
def test_trailing_comment_does_not_satisfy_either_half(tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path / "repo",
        baseline=True,
        precommit="repos: []  # once wired, reads .secrets.baseline\n",
        workflows={"ci.yml": "jobs: {}  # detect-secrets-hook goes here\n"},
    )
    assert mod.main(["--repo-root", str(repo)]) == 1


@pytest.mark.unit
def test_unreadable_repo_root_is_exit_2_not_a_pass(tmp_path: Path) -> None:
    """Fail closed: an undecidable run is never reported as clean."""
    assert mod.main(["--repo-root", str(tmp_path / "does-not-exist")]) == 2


@pytest.mark.unit
def test_positive_control_failure_forces_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken matcher must not be able to report a clean repository (rule 16)."""
    repo = _write_repo(
        tmp_path / "repo",
        baseline=True,
        precommit=PRECOMMIT_READER,
        workflows={"ci.yml": WORKFLOW_READER},
    )
    assert mod.main(["--repo-root", str(repo)]) == 0

    monkeypatch.setattr(
        mod,
        "evaluate",
        lambda inputs: mod.ModelWiringVerdict(
            ok=True, exit_code=0, lines=["fake pass"]
        ),
    )
    assert mod.main(["--repo-root", str(repo)]) == 2


@pytest.mark.unit
def test_gate_declares_no_force_or_skip_option() -> None:
    """A bypass flag would make this a suggestion. Its return is a red test."""
    options: set[str] = set()
    for action in mod.build_parser()._actions:
        options.update(action.option_strings)
    for forbidden in ("--force", "--skip", "--allow", "--no-fail", "--warn-only"):
        assert forbidden not in options


@pytest.mark.unit
def test_this_repository_satisfies_its_own_gate() -> None:
    """Dogfood: omniclaude carries a baseline, so it owes both halves too."""
    repo_root = Path(__file__).resolve().parents[2]
    assert mod.main(["--repo-root", str(repo_root)]) == 0
