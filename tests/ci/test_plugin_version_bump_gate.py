# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20710 (port of OMN-20497): PRs leave the version for one post-merge bot PR.

The per-PR gate refuses changed broken or lowered versions and marketplace skew.
Throwaway git repos exercise concurrent unbumped PRs, numeric merge-base floors,
and the validator's byte-preserving post-merge bump. The workflow's actual bump
shell runs locally without network to verify its last-version-commit selection.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.validation import validate_plugin_version_bump as gate  # noqa: E402

PLUGIN_JSON = "plugins/onex/.claude-plugin/plugin.json"
MARKETPLACE_JSON = "plugins/test-marketplace/.claude-plugin/marketplace.json"
WORKFLOW = REPO_ROOT / ".github/workflows/plugin-version-bump.yml"
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"


def _git_env(repo: Path) -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(repo),
    }


def _git(repo: Path, *args: str) -> str:
    # A full literal env, never derived from os.environ: a hook's GIT_DIR would
    # otherwise point git at the real worktree (OMN-18434).
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
            "HOME": str(repo),
        },
    ).stdout


def _write_versions(repo: Path, plugin: str, marketplace: str | None = None) -> None:
    (repo / PLUGIN_JSON).parent.mkdir(parents=True, exist_ok=True)
    (repo / MARKETPLACE_JSON).parent.mkdir(parents=True, exist_ok=True)
    (repo / PLUGIN_JSON).write_text(json.dumps({"name": "onex", "version": plugin}))
    (repo / MARKETPLACE_JSON).write_text(
        json.dumps({"plugins": [{"name": "onex", "version": marketplace or plugin}]})
    )


def _versions(repo: Path) -> tuple[str, str]:
    return (
        json.loads((repo / PLUGIN_JSON).read_text())["version"],
        json.loads((repo / MARKETPLACE_JSON).read_text())["plugins"][0]["version"],
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "dev")
    _write_versions(tmp_path, "1.0.0")
    (tmp_path / "plugins/onex/skills/a").mkdir(parents=True)
    (tmp_path / "plugins/onex/skills/a/SKILL.md").write_text("one\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")


def _merged_changes(repo: Path) -> str:
    """Two changes merged to dev since the last version-setting commit."""
    base = _git(repo, "rev-parse", "dev").strip()
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _commit(repo)
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge first")
    _git(repo, "checkout", "-q", "-b", "second")
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("three\n")
    _commit(repo)
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "second", "-m", "merge second")
    return base


@pytest.mark.unit
def test_two_unbumped_prs_pass_before_and_after_dev_merge(repo: Path) -> None:
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _commit(repo)
    assert gate.check(repo, "dev") == []
    _git(repo, "checkout", "-q", "-b", "second", "dev")
    skill = repo / "plugins/onex/skills/b/SKILL.md"
    skill.parent.mkdir()
    skill.write_text("other feature\n")
    _commit(repo)
    assert gate.check(repo, "dev") == []
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge first")
    _git(repo, "checkout", "-q", "second")
    _git(repo, "merge", "-q", "dev", "-m", "merge dev")
    assert gate.check(repo, "dev") == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("version", "kind"),
    [
        ("0.9.9", "LOWERED_VERSION"),
        ("2.x", "BROKEN_VERSION"),
        ("2.4.53-rc1", "BROKEN_VERSION"),
        ("1.0.1", None),
        ("2.5", None),
    ],
)
def test_changed_version_rule(repo: Path, version: str, kind: str | None) -> None:
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _write_versions(repo, version)
    _commit(repo)
    findings = gate.check(repo, "dev")
    assert [f.kind for f in findings] == ([kind] if kind else [])
    if kind:
        assert "PRs no longer bump" in findings[0].detail
        assert "Put dev's value back in both files" in findings[0].detail


@pytest.mark.unit
def test_lowered_version_without_content_change_fails(repo: Path) -> None:
    # Only plugin.json changes: this must be checked even without another shipped edit.
    (repo / PLUGIN_JSON).write_text(json.dumps({"name": "onex", "version": "0.9.9"}))
    _commit(repo)
    assert [f.kind for f in gate.check(repo, "dev")] == [
        "LOWERED_VERSION",
        "MARKETPLACE_SKEW",
    ]


@pytest.mark.unit
def test_version_compare_is_numeric_not_lexical(repo: Path) -> None:
    _write_versions(repo, "1.0.9")
    _commit(repo)
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--ff-only", "feature")
    _git(repo, "checkout", "-q", "-b", "f2")
    _write_versions(repo, "1.0.10")
    _commit(repo)
    assert gate.check(repo, "dev") == []


@pytest.mark.unit
def test_invalid_base_version_has_no_floor(repo: Path) -> None:
    _write_versions(repo, "2.x")
    _commit(repo)
    base = _git(repo, "rev-parse", "HEAD").strip()
    assert gate.check(repo, base) == []  # Unchanged versions have no new finding.
    _write_versions(repo, "1.0.0")
    assert gate.check(repo, base) == []


@pytest.mark.unit
def test_plugin_absent_at_merge_base_has_no_floor(repo: Path) -> None:
    _git(repo, "rm", PLUGIN_JSON)
    _commit(repo)
    base = _git(repo, "rev-parse", "HEAD").strip()
    _write_versions(repo, "0.0.1")
    assert gate.check(repo, base) == []


@pytest.mark.unit
@pytest.mark.parametrize("content", ["{}", '{"version": 1}', "not json", None])
def test_unreadable_head_version_is_gate_error(repo: Path, content: str | None) -> None:
    path = repo / PLUGIN_JSON
    if content is None:
        path.unlink()
    else:
        path.write_text(content)
    with pytest.raises(gate.GateError):
        gate.check(repo, "dev")
    assert gate.main(["--repo-root", str(repo), "--base", "dev"]) == 2


@pytest.mark.unit
def test_marketplace_version_must_match_plugin(repo: Path) -> None:
    _write_versions(repo, "1.0.1", marketplace="1.0.0")
    _commit(repo)
    findings = gate.check(repo, "dev")
    assert [f.kind for f in findings] == ["MARKETPLACE_SKEW"]
    assert "PRs no longer bump" in findings[0].detail


@pytest.mark.unit
def test_staged_lowered_version_counts_for_precommit(repo: Path) -> None:
    _write_versions(repo, "0.9.9")
    _git(repo, "add", "-A")
    assert [f.kind for f in gate.check(repo, "dev")] == ["LOWERED_VERSION"]


@pytest.mark.unit
def test_unresolvable_base_is_an_error_not_a_pass(repo: Path) -> None:
    with pytest.raises(gate.GateError):
        gate.check(repo, "no-such-ref")
    with pytest.raises(gate.GateError):
        gate.bump_to_base(repo, "no-such-ref")


@pytest.mark.unit
def test_real_repo_manifests_agree() -> None:
    """The committed plugin.json and dev marketplace.json never disagree."""
    assert gate.marketplace_skew(REPO_ROOT) == []


@pytest.mark.unit
def test_defer_flag_only_defers_under_github_actions(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_versions(repo, "0.9.9")
    _commit(repo)
    argv = ["--repo-root", str(repo), "--base", "dev", "--defer-to-workflow-in-ci"]
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert gate.main(argv) == 1
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert gate.main(argv) == 0
    assert gate.main(argv[:-1]) == 1


@pytest.mark.unit
def test_bump_after_two_merged_changes_is_idempotent(repo: Path) -> None:
    base = _merged_changes(repo)
    assert gate.bump_to_base(repo, base) == [
        f"bumped {PLUGIN_JSON}: onex 1.0.0 -> 1.0.1",
        f"bumped {MARKETPLACE_JSON}: onex 1.0.0 -> 1.0.1",
    ]
    assert _versions(repo) == ("1.0.1", "1.0.1")
    assert gate.bump_to_base(repo, base) == []
    assert gate.check(repo, base) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "plugins/onex/tests/test_x.py",
        "README.md",
        "plugins/onex/hooks/__pycache__/x.pyc",
        "plugins/onex/.venv/x.py",
    ],
)
def test_bump_exempt_changes_do_nothing(repo: Path, path: str) -> None:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("x\n")
    _commit(repo)
    assert gate.bump_to_base(repo, "dev") == []
    assert _versions(repo) == ("1.0.0", "1.0.0")


@pytest.mark.unit
def test_bump_includes_untracked_shipped_changes(repo: Path) -> None:
    (repo / "plugins/onex/new.md").write_text("untracked\n")
    assert len(gate.bump_to_base(repo, "dev")) == 2
    assert _versions(repo) == ("1.0.1", "1.0.1")


@pytest.mark.unit
@pytest.mark.parametrize("invalid_file", ["plugin", "marketplace"])
def test_bump_refuses_non_dotted_base(repo: Path, invalid_file: str) -> None:
    _write_versions(repo, "2.x" if invalid_file == "plugin" else "1.0.0", "2.x")
    _commit(repo)
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    before = [(repo / path).read_bytes() for path in (PLUGIN_JSON, MARKETPLACE_JSON)]
    with pytest.raises(gate.GateError, match="set the version by hand"):
        gate.bump_to_base(repo, base)
    assert [
        (repo / path).read_bytes() for path in (PLUGIN_JSON, MARKETPLACE_JSON)
    ] == before


@pytest.mark.unit
@pytest.mark.parametrize("ahead_file", ["plugin", "marketplace"])
def test_file_already_above_keeps_value_and_other_joins(
    repo: Path, ahead_file: str
) -> None:
    _write_versions(
        repo,
        "1.0.7" if ahead_file == "plugin" else "1.0.0",
        "1.0.7" if ahead_file == "marketplace" else "1.0.0",
    )
    ahead_path = PLUGIN_JSON if ahead_file == "plugin" else MARKETPLACE_JSON
    original = (repo / ahead_path).read_bytes()
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    lines = gate.bump_to_base(repo, "dev")
    assert len(lines) == 1
    assert _versions(repo) == ("1.0.7", "1.0.7")
    assert (repo / ahead_path).read_bytes() == original
    assert gate.bump_to_base(repo, "dev") == []


@pytest.mark.unit
def test_bump_uses_larger_base_and_each_files_own_floor(repo: Path) -> None:
    _write_versions(repo, "1.0.0", "1.0.3")
    _commit(repo)
    base = _git(repo, "rev-parse", "HEAD").strip()
    _write_versions(repo, "1.0.2", "1.0.3")
    assert gate.bump_to_base(repo, base) == [
        f"bumped {MARKETPLACE_JSON}: onex 1.0.3 -> 1.0.4"
    ]
    assert _versions(repo) == ("1.0.2", "1.0.4")  # Above its own floor stays unchanged.


@pytest.mark.unit
def test_bump_edits_only_the_intended_version_bytes(repo: Path) -> None:
    plugin = (
        '{\r\n  "name": "onex",\r\n'
        '  "nested": {"min_version": "0.39.0", "version": "1.0.0"},\r\n'
        '  "version" : "1.0.0",\r\n  "description": "café"\r\n}\r\n'
    ).encode()
    marketplace = (
        b'{\n "version": "1.0.0", "plugins": [\n'
        b' {"name": "other", "version": "1.0.0"},\n'
        b' {"name": "onex", "nested": {"version": "1.0.0"}, "version" : "1.0.0"}\n'
        b" ]\n}\n"
    )
    (repo / PLUGIN_JSON).write_bytes(plugin)
    (repo / MARKETPLACE_JSON).write_bytes(marketplace)
    _commit(repo)
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    assert len(gate.bump_to_base(repo, base)) == 2
    for path, original in ((PLUGIN_JSON, plugin), (MARKETPLACE_JSON, marketplace)):
        assert (repo / path).read_bytes() == original.replace(
            b'"version" : "1.0.0"', b'"version" : "1.0.1"'
        )


@pytest.mark.unit
def test_failed_edit_does_not_write_any_file(repo: Path) -> None:
    # JSON decodes the escaped version, but the exact setter cannot replace it.
    (repo / MARKETPLACE_JSON).write_bytes(
        b'{"plugins": [{"name": "onex", "version": "1.0.\\u0030"}]}'
    )
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    original = (repo / PLUGIN_JSON).read_bytes()
    with pytest.raises(gate.GateError, match="cannot find the one version"):
        gate.bump_to_base(repo, "dev")
    assert (repo / PLUGIN_JSON).read_bytes() == original


@pytest.mark.unit
def test_bump_main_prints_lines_then_checks(
    repo: Path, capsys: pytest.CaptureFixture
) -> None:
    base = _merged_changes(repo)
    argv = ["--repo-root", str(repo), "--base", base, "--bump-to-base"]
    assert gate.main(argv) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert gate.main(argv) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.unit
@pytest.mark.parametrize("already_versioned", [False, True])
def test_workflow_bump_shell_uses_last_version_commit(
    repo: Path, tmp_path: Path, already_versioned: bool
) -> None:
    _merged_changes(repo)
    validator = repo / "scripts/validation/validate_plugin_version_bump.py"
    validator.parent.mkdir(parents=True)
    shutil.copyfile(
        REPO_ROOT / "scripts/validation/validate_plugin_version_bump.py", validator
    )
    if already_versioned:
        _write_versions(repo, "1.0.1")
    _commit(repo)
    workflow = yaml.safe_load(WORKFLOW.read_text())
    bump = next(
        step
        for step in workflow["jobs"]["plugin-version-bump"]["steps"]
        if step.get("id") == "bump"
    )
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "python").symlink_to(sys.executable)
    output = runner_temp / "output"
    proc = subprocess.run(
        ["bash", "-c", bump["run"]],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={
            **_git_env(repo),
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(output),
            "PATH": f"{shim}:{os.environ['PATH']}",
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert output.read_text() == f"changed={str(not already_versioned).lower()}\n"
    assert _versions(repo) == ("1.0.1", "1.0.1")


@pytest.mark.unit
def test_workflow_shape_has_one_app_authenticated_dev_bump() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    triggers = workflow[True]  # PyYAML's YAML 1.1 interpretation of `on`.
    assert triggers["push"]["branches"] == ["dev"]
    assert triggers["schedule"] == [{"cron": "*/30 * * * *"}]
    assert "workflow_dispatch" in triggers
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "plugin-version-bump",
        "cancel-in-progress": False,
    }
    job = workflow["jobs"]["plugin-version-bump"]
    assert "omn-20710" in job["env"]["BUMP_BRANCH"]
    assert job["timeout-minutes"] == 15
    steps = job["steps"]
    assert not any(step.get("id") == "gate" for step in steps)
    publish = next(
        step
        for step in steps
        if step.get("name", "").startswith("Open, update or close")
    )
    assert "--base dev" in publish["run"]
    assert "git merge-tree --write-tree" in publish["run"]
    assert "--body-file" in publish["run"]
    assert "Evidence-Ticket: OMN-20710" in publish["run"]
    assert publish["env"]["GH_TOKEN"] == "${{ steps.app-token.outputs.token }}"
    app = next(step for step in steps if step.get("id") == "app-token")
    assert app["with"]["app-id"] == "${{ secrets.ONEXBOT_OCC_APP_ID }}"
    assert app["with"]["permission-workflows"] == "write"
    assert "GITHUB_TOKEN" not in WORKFLOW.read_text()


VALIDATOR = REPO_ROOT / "scripts/validation/validate_plugin_version_bump.py"
GATE_WORKFLOW = REPO_ROOT / ".github/workflows/plugin-version-bump-gate.yml"


def _run_validator(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """The validator as the gate workflow runs it: its CLI, in its own process."""
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env={**_git_env(repo), "PYTHONPATH": ""},
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("plugin", "marketplace", "kind"),
    [
        ("0.9.9", "0.9.9", "LOWERED_VERSION"),
        ("1.0.0", "1.0.0", None),
        ("2.x", "2.x", "BROKEN_VERSION"),
        ("1.0.1", "1.0.0", "MARKETPLACE_SKEW"),
        ("1.0.1", "1.0.1", None),
    ],
    ids=["lowered", "unchanged", "malformed", "inconsistent", "raised"],
)
def test_bad_version_refused(
    repo: Path, plugin: str, marketplace: str, kind: str | None
) -> None:
    """OMN-20710 AC1: the gate's CLI exits 1 for a lowered, malformed or inconsistent version.

    The two rows that carry no finding are the positive controls: the same
    command exits 0 on an unchanged and on a raised, agreeing version, so the
    refusals above are the validator's verdict and not a harness failure.
    """
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _write_versions(repo, plugin, marketplace)
    _commit(repo)
    proc = _run_validator(repo, "--base", "dev")
    if kind is None:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert proc.stderr == ""
    else:
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert kind in proc.stderr
        assert "PRs no longer bump" in proc.stderr


@pytest.mark.unit
def test_bad_version_refused_and_single_bump_pr_cases_run_in_ci_and_precommit() -> None:
    """The cases above are wired: a named required-umbrella CI step plus a check-only hook.

    This is the part of AC1 and AC2 that is a change to the repository's wiring,
    so it fails on a tree where the step or the hook is absent. The gate and the
    bot themselves are unchanged by OMN-20710: they already ran on dev.
    """
    gate = yaml.safe_load(GATE_WORKFLOW.read_text())
    gate_job = gate["jobs"]["plugin-version-bump-gate"]
    run = next(
        s["run"]
        for s in gate_job["steps"]
        if "validate_plugin_version_bump" in s.get("run", "")
    )
    assert "scripts/validation/validate_plugin_version_bump.py --base" in run
    assert "--bump-to-base" not in run
    assert gate_job["name"] == "Plugin Version Bump Gate"

    ci_steps = yaml.safe_load(CI_WORKFLOW.read_text())["jobs"]["refusal-surface"][
        "steps"
    ]
    named = [
        s for s in ci_steps if "test_plugin_version_bump_gate.py" in s.get("run", "")
    ]
    assert len(named) == 1
    assert "(OMN-20710)" in named[0]["name"]
    assert named[0]["run"].startswith(
        "uv run pytest tests/ci/test_plugin_version_bump_gate.py"
    )
    assert "-k" not in named[0]["run"].split()  # the whole file, not a subset

    hooks = {
        hook["id"]: hook
        for repo_cfg in yaml.safe_load(
            (REPO_ROOT / ".pre-commit-config.yaml").read_text()
        )["repos"]
        for hook in repo_cfg["hooks"]
    }
    # `plugin-version-bump-gate` is the existing hook in .pre-commit-config.yaml
    # (already on dev, id: plugin-version-bump-gate, always_run: true); only
    # `plugin-version-bump-tests` is added beside it by this change.
    assert "plugin-version-bump-gate" in hooks, "the existing gate hook is missing"
    entry = hooks["plugin-version-bump-gate"]["entry"]
    assert "validate_plugin_version_bump.py --base origin/dev" in entry
    assert hooks["plugin-version-bump-gate"]["always_run"] is True
    tests_hook = hooks["plugin-version-bump-tests"]
    assert "tests/ci/test_plugin_version_bump_gate.py" in tests_hook["entry"]
    assert tests_hook["pass_filenames"] is False
    for touched in (
        "tests/ci/test_plugin_version_bump_gate.py",
        "scripts/validation/validate_plugin_version_bump.py",
        ".github/workflows/plugin-version-bump.yml",
        ".github/workflows/plugin-version-bump-gate.yml",
    ):
        assert re.search(tests_hook["files"], touched), touched


def _publish_step() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["plugin-version-bump"]["steps"]
    return next(
        s for s in steps if s.get("name", "").startswith("Open, update or close")
    )


def _bump_step() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return next(
        s
        for s in workflow["jobs"]["plugin-version-bump"]["steps"]
        if s.get("id") == "bump"
    )


_FAKE_GH = """#!/bin/bash
# A stand-in for the pull request API: one state directory, no network.
state="$FAKE_GH_STATE"
case "$1 $2" in
  "pr list") cat "$state/open" 2>/dev/null || true ;;
  "pr create") echo create >> "$state/calls"; echo 1 > "$state/open"; echo "https://example.invalid/pull/1" ;;
  "pr close") echo close >> "$state/calls"; rm -f "$state/open" ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""


class _BotHarness:
    """Run the workflow's two real shell steps against a local origin and a fake gh."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.origin = root / "origin.git"
        self.seed = root / "seed"
        self.state = root / "gh-state"
        self.state.mkdir()
        shim = root / "shim"
        shim.mkdir()
        (shim / "python").symlink_to(sys.executable)
        gh = shim / "gh"
        gh.write_text(_FAKE_GH)
        gh.chmod(0o755)
        self.shim = shim
        self.runs = 0
        self.branch = yaml.safe_load(WORKFLOW.read_text())["jobs"][
            "plugin-version-bump"
        ]["env"]["BUMP_BRANCH"]
        _git(root, "init", "-q", "--bare", "-b", "dev", str(self.origin))
        self.seed.mkdir()
        _git(self.seed, "init", "-q", "-b", "dev")
        _write_versions(self.seed, "1.0.0")
        skill = self.seed / "plugins/onex/skills/a/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("one\n")
        validator = self.seed / "scripts/validation/validate_plugin_version_bump.py"
        validator.parent.mkdir(parents=True)
        shutil.copyfile(VALIDATOR, validator)
        _git(self.seed, "add", "-A")
        _git(self.seed, "commit", "-q", "-m", "base")
        _git(self.seed, "remote", "add", "origin", str(self.origin))
        _git(self.seed, "push", "-q", "origin", "dev")

    def merge_to_dev(self, text: str, marketplace: str | None = None) -> None:
        """One more change on dev, as a squash merge would leave it."""
        (self.seed / "plugins/onex/skills/a/SKILL.md").write_text(text)
        if marketplace is not None:
            (self.seed / MARKETPLACE_JSON).write_text(marketplace)
        _git(self.seed, "add", "-A")
        _git(self.seed, "commit", "-q", "-m", f"merge {text.strip()}")
        _git(self.seed, "push", "-q", "origin", "dev")

    def _env(self, work: Path, **extra: str) -> dict[str, str]:
        return {
            **_git_env(work),
            "PATH": f"{self.shim}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(self.root / f"runner-temp-{self.runs}"),
            "GITHUB_OUTPUT": str(self.root / f"output-{self.runs}"),
            "FAKE_GH_STATE": str(self.state),
            **extra,
        }

    def run_workflow(self) -> Path:
        """One workflow run at the current dev tip: the bump step, then the publish step."""
        self.runs += 1
        work = self.root / f"run-{self.runs}"
        _git(self.root, "clone", "-q", "--branch", "dev", str(self.origin), str(work))
        env = self._env(work)
        Path(env["RUNNER_TEMP"]).mkdir()
        bump = subprocess.run(
            ["bash", "-c", _bump_step()["run"]],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert bump.returncode == 0, bump.stdout + bump.stderr
        changed = (
            Path(env["GITHUB_OUTPUT"]).read_text().strip().removeprefix("changed=")
        )
        publish = subprocess.run(
            ["bash", "-c", _publish_step()["run"]],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
            env={
                **env,
                "BUMP_BRANCH": self.branch,
                "GH_TOKEN": "unused",
                "REPO": "OmniNode-ai/omniclaude",
                "CHANGED": changed,
                "RUN_URL": f"https://example.invalid/run/{self.runs}",
                "GITHUB_WORKFLOW": "Plugin Version Bump",
            },
        )
        assert publish.returncode == 0, publish.stdout + publish.stderr
        return work

    @property
    def creates(self) -> int:
        calls = self.state / "calls"
        return calls.read_text().split().count("create") if calls.exists() else 0

    @property
    def closes(self) -> int:
        calls = self.state / "calls"
        return calls.read_text().split().count("close") if calls.exists() else 0

    @property
    def open_prs(self) -> int:
        return 1 if (self.state / "open").exists() else 0

    def branch_tip(self) -> str:
        return _git(
            self.root, "ls-remote", str(self.origin), f"refs/heads/{self.branch}"
        ).split()[0]


@pytest.mark.unit
def test_single_bump_pr_across_concurrent_dev_merges(tmp_path: Path) -> None:
    """OMN-20710 AC2: successive dev merges leave one bot bump PR, rebuilt in place.

    Each workflow run is the real bump step and the real publish step against a
    local origin, with only the pull request API replaced. The workflow's
    concurrency group queues runs one at a time, so a burst of dev merges is a
    sequence of these runs at successive dev tips.
    """
    bot = _BotHarness(tmp_path)

    # Dev merge 1: no bump PR exists, so the run opens the one PR.
    bot.merge_to_dev("two\n")
    first = bot.run_workflow()
    assert (bot.creates, bot.open_prs) == (1, 1)
    assert _versions(first) == ("1.0.1", "1.0.1")
    first_tip = bot.branch_tip()
    assert first_tip == _git(first, "rev-parse", "HEAD").strip()

    # Dev merge 2 touches the same marketplace line the bump edits: the branch no
    # longer merges cleanly, so the run rebuilds it in place and opens no second PR.
    bot.merge_to_dev(
        "three\n",
        marketplace=json.dumps(
            {"plugins": [{"name": "onex", "version": "1.0.0", "description": "x"}]}
        ),
    )
    second = bot.run_workflow()
    assert (bot.creates, bot.open_prs) == (1, 1)
    assert bot.branch_tip() == _git(second, "rev-parse", "HEAD").strip()
    assert bot.branch_tip() != first_tip
    assert _versions(second) == ("1.0.1", "1.0.1")

    # Dev merge 3 changes nothing the bump touches: the run finds the branch
    # already carrying the bump and neither pushes nor opens another PR.
    bot.merge_to_dev("four\n")
    rebuilt_tip = bot.branch_tip()
    bot.run_workflow()
    assert (bot.creates, bot.open_prs) == (1, 1)
    assert bot.branch_tip() == rebuilt_tip

    # The bump PR merges: dev carries the version, so the run closes the PR.
    bot.merge_to_dev("four\n", marketplace=(second / MARKETPLACE_JSON).read_text())
    _git(bot.seed, "checkout", "-q", "dev", "--", MARKETPLACE_JSON)
    (bot.seed / PLUGIN_JSON).write_text(
        json.dumps({"name": "onex", "version": "1.0.1"})
    )
    _git(bot.seed, "add", "-A")
    _git(bot.seed, "commit", "-q", "-m", "chore: post-merge plugin version bump")
    _git(bot.seed, "push", "-q", "origin", "dev")
    bot.run_workflow()
    assert (bot.creates, bot.closes, bot.open_prs) == (1, 1, 0)


@pytest.mark.unit
def test_single_bump_pr_is_one_fixed_branch_under_one_concurrency_group() -> None:
    """The structural half of AC2: one branch name, runs queued, a PR opened only when none is."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow["concurrency"] == {
        "group": "plugin-version-bump",
        "cancel-in-progress": False,
    }
    run = _publish_step()["run"]
    assert run.count("gh pr create") == 1
    assert run.index('if [ -n "$open" ]') < run.index("gh pr create")
    assert '--head "$BUMP_BRANCH"' in run
