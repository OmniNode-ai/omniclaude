# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Regression test for OMN-14463: pre-push hook chain self-block on root
`__pycache__/`.

## The defect

`scripts/validate-clean-root.sh` runs in the `pre-push` pre-commit stage and
rejects a root-level `__pycache__/`. Two hooks in the `pre-commit` stage
(`workflow-run-script-paths-exist`, `reusable-workflow-inner-checkouts-pinned`)
invoke `uv run pytest ...`, and pytest always imports the repo-root
`conftest.py` regardless of `testpaths`. CPython writes that module's
compiled bytecode (`__pycache__/conftest.*.pyc`) as part of the import --
before any of conftest.py's own top-level code runs, so the artifact cannot
be suppressed from inside conftest.py itself. The result: the hook chain's
own pytest step deterministically creates the exact artifact a later step in
the same chain rejects. Six ledger occurrences (L3027, L15888, L17171,
L18423, L19359, L21616) over seven weeks; see the OMN-14463 evidence comment
(fingerprint `fr-pre-push-hook-self-created-pycache-self-block`) for the full
citation list.

Live reproduction of the RED case (before the fix in this PR):
    $ cd omniclaude && rm -rf __pycache__
    $ uv run pytest tests/workflows/test_workflow_run_script_paths_exist.py \\
        -q -p no:cacheprovider
    $ ls __pycache__          # conftest.cpython-*.pyc now exists at repo root
    $ bash scripts/validate-clean-root.sh; echo $?   # 1 -- FAILED

## The fix

`PYTHONDONTWRITEBYTECODE=1` is set on the pytest invocation itself (the
interpreter reads it at startup, before any user code -- including
conftest.py -- runs, which is the only point in the sequence where
suppressing conftest.py's own bytecode write is still possible). Wrapped in
`bash -c '...'` because pre-commit's `system` language execs `entry:` argv
directly with no shell, so a bare `VAR=1 uv run ...` entry would be
interpreted as attempting to execute a binary literally named `VAR=1`.

This does not touch `validate-clean-root.sh`'s forbidden-pattern list or
whitelist at all, so a genuinely stray file is still caught -- proven by
`test_validate_clean_root_still_rejects_genuinely_stray_file` below.

## Why this test copies the validator into an isolated tmp tree

`validate-clean-root.sh` resolves `PROJECT_ROOT` from its own script
location (`$SCRIPT_DIR/..`), so pointing it at a temp copy of itself is
sufficient to exercise the real, unmodified validator against a synthetic
tree without ever touching this repo's actual working-tree root (no
transient pollution of a shared clone, no interference with a concurrent
`git push` in the same worktree).

## Ties to the shipped config, not just the general mechanism

`test_shipped_pytest_hooks_set_pythondontwritebytecode` parses the real
`.pre-commit-config.yaml` and asserts the fix is present on both pytest
`entry:` lines, so a future edit that silently drops the env var is caught
even though the isolated mechanism tests above would still pass.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR_SRC = _REPO_ROOT / "scripts" / "validate-clean-root.sh"
_PRECOMMIT_CONFIG = _REPO_ROOT / ".pre-commit-config.yaml"

_CONFTEST_BODY = "# minimal conftest.py standing in for the real repo root's\n"
_TEST_BODY = "def test_noop() -> None:\n    assert True\n"


def _make_isolated_project(tmp_path: Path) -> Path:
    """Build a synthetic project root: a copy of the real validator plus a
    root-level conftest.py + one trivial test, mirroring the real repo's
    shape closely enough that pytest's root-conftest import behavior is
    identical."""
    (tmp_path / "scripts").mkdir()
    validator_copy = tmp_path / "scripts" / "validate-clean-root.sh"
    shutil.copy2(_VALIDATOR_SRC, validator_copy)
    validator_copy.chmod(0o755)
    (tmp_path / "conftest.py").write_text(_CONFTEST_BODY)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_dummy.py").write_text(_TEST_BODY)
    return tmp_path


def _run_pytest(
    project_root: Path, *, dont_write_bytecode: bool
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if dont_write_bytecode:
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    else:
        env.pop("PYTHONDONTWRITEBYTECODE", None)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_dummy.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_validator(project_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(project_root / "scripts" / "validate-clean-root.sh")],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# RED: reproduces the defect exactly -- without the env var, pytest's own
# root-conftest import pollutes root __pycache__/, and the SAME validator
# script (unmodified) then rejects it.
# ---------------------------------------------------------------------------


def test_bare_pytest_invocation_pollutes_root_and_validator_rejects_it(tmp_path):
    project = _make_isolated_project(tmp_path)

    pytest_result = _run_pytest(project, dont_write_bytecode=False)
    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

    assert (project / "__pycache__").is_dir(), (
        "expected the bare pytest invocation to reproduce the self-block "
        "mechanism by writing root __pycache__/ (bytecode for the root "
        "conftest.py) -- if this no longer happens, the defect this test "
        "guards against may no longer be reproducible and the test should "
        "be re-examined, not just the assertion below"
    )

    validator_result = _run_validator(project)
    assert validator_result.returncode == 1, (
        "RED case did not reproduce: validate-clean-root.sh should reject "
        f"the root __pycache__/ the bare pytest run just created.\nstdout:\n"
        f"{validator_result.stdout}"
    )
    assert "__pycache__" in validator_result.stdout


# ---------------------------------------------------------------------------
# GREEN: the fix. Same tree shape, same pytest invocation, only difference
# is PYTHONDONTWRITEBYTECODE=1 -- the exact env var carried by the fixed
# .pre-commit-config.yaml entries. Proves the hook chain end-to-end: the
# producer step no longer creates the artifact, so the consumer step (the
# real, unmodified validator) does not reject the push.
# ---------------------------------------------------------------------------


def test_pythondontwritebytecode_prevents_self_block_end_to_end(tmp_path):
    project = _make_isolated_project(tmp_path)

    pytest_result = _run_pytest(project, dont_write_bytecode=True)
    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

    assert not (project / "__pycache__").exists(), (
        "PYTHONDONTWRITEBYTECODE=1 should prevent the root __pycache__/ "
        "from being written at all"
    )

    validator_result = _run_validator(project)
    assert validator_result.returncode == 0, (
        "push should not be rejected once the pytest step no longer writes "
        f"the artifact the validator scans for.\nstdout:\n{validator_result.stdout}"
    )


# ---------------------------------------------------------------------------
# Negative control: the fix must not weaken validate-clean-root.sh's actual
# protection. A genuinely stray file (never produced by any hook in this
# chain) must still be rejected.
# ---------------------------------------------------------------------------


def test_validate_clean_root_still_rejects_genuinely_stray_file(tmp_path):
    project = _make_isolated_project(tmp_path)

    # Belt-and-suspenders: prove the tree is otherwise clean before adding
    # the stray file, so a failure below is unambiguously attributable to
    # the stray file and not to leftover state from project setup.
    assert _run_validator(project).returncode == 0

    stray = project / "leftover_debug_output.txt"
    stray.write_text("not produced by any hook in the chain\n")

    validator_result = _run_validator(project)
    assert validator_result.returncode == 1, (
        "a genuinely stray root file must still be rejected -- the fix "
        "must not weaken validate-clean-root.sh's protection"
    )
    assert stray.name in validator_result.stdout


# ---------------------------------------------------------------------------
# Wiring check: ties the isolated mechanism proof above to what actually
# ships. Parses the real .pre-commit-config.yaml so a future edit that
# drops PYTHONDONTWRITEBYTECODE=1 from either pytest entry is caught even
# though the isolated tests above would keep passing.
# ---------------------------------------------------------------------------

_PYTEST_HOOK_IDS = (
    "workflow-run-script-paths-exist",
    "reusable-workflow-inner-checkouts-pinned",
)


def _entry_for(hook_id: str, config_text: str) -> str:
    config = yaml.safe_load(config_text)
    for repo_config in config["repos"]:
        for hook in repo_config.get("hooks", []):
            if hook.get("id") == hook_id:
                entry = hook.get("entry")
                assert isinstance(entry, str), f"{hook_id}: entry is not a string"
                return entry
    raise AssertionError(f"hook id {hook_id!r} not found in .pre-commit-config.yaml")


def test_shipped_pytest_hooks_set_pythondontwritebytecode():
    config_text = _PRECOMMIT_CONFIG.read_text()
    for hook_id in _PYTEST_HOOK_IDS:
        entry = _entry_for(hook_id, config_text)
        assert "uv run pytest" in entry, f"{hook_id}: expected a pytest invocation"
        assert "PYTHONDONTWRITEBYTECODE=1" in entry, (
            f"{hook_id}: pytest entry no longer sets PYTHONDONTWRITEBYTECODE=1 "
            "-- this reopens OMN-14463's pre-push self-block"
        )
