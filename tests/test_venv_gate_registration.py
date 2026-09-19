# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18752: the venv gates' LIVE half must be registered where it can run.

Three separate surfaces asserted that these two gates run "as BOTH a
pre-commit hook and a required CI status check": the wrapper headers in
``.pre-commit-hooks/``, the module docstring of ``check_daemon_venv_skew.py``,
and the CI workflows. Verified 2026-09-18: neither id appeared in any
``.pre-commit-config.yaml`` in the workspace, and neither was exported in
``.pre-commit-hooks.yaml``.

That is not a cosmetic gap. CI runners carry no live venv, so the gates' live
half — the entire point of them — had only ever run when a human typed it. Five
findings accumulated unseen on the fleet's own development host as a result,
including one whose only offered remedy would have downgraded a sibling 22
merged commits and taken ``onex delegate`` down for every lane.

These tests read the pre-commit CONFIG, not the hook scripts and not the
workflows. A test that greps the script or the workflow would have passed
throughout the period the gate was unregistered, which is exactly why it has
to read the config.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REQUIRED_HOOK_IDS = (
    "check-daemon-venv-skew",
    # OMN-18753: registered once its baseline was settled. OMN-18752 repointed
    # this gate at the canonical clone's checked-out head, the same fact the
    # OMN-18675 venv guard resolves, so it is no longer a gate that
    # structurally cannot pass. Both now name one expected commit.
    "check-omnimarket-dispatch-drift",
)


def _executable_source(path: Path) -> str:
    """The module's code with every docstring and comment removed.

    Both are stripped and neither may be skipped. The docstrings of this
    module DESCRIBE the removed remote-branch probe on purpose, so a plain
    substring search over the file matches the prose that records the removal
    and can never go green. Stripping strings wholesale would be the opposite
    error: the probe, if it came back, would be the literal ``"ls-remote"`` in
    a ``subprocess`` argument list, so the one thing the check must still see
    is a string.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring_spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        first = node.body[0]
        assert first.end_lineno is not None
        docstring_spans.append((first.lineno, first.end_lineno))

    kept: list[str] = []
    for number, line in enumerate(source.splitlines(), start=1):
        if any(start <= number <= end for start, end in docstring_spans):
            continue
        if line.lstrip().startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _local_hooks() -> dict[str, dict[str, Any]]:
    config = yaml.safe_load(
        (_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    hooks: dict[str, dict[str, Any]] = {}
    for repo in config.get("repos", []):
        if repo.get("repo") != "local":
            continue
        for hook in repo.get("hooks", []):
            hook_id = hook.get("id")
            if isinstance(hook_id, str):
                hooks[hook_id] = hook
    return hooks


@pytest.mark.parametrize("hook_id", _REQUIRED_HOOK_IDS)
def test_gate_is_registered_in_the_precommit_config(hook_id: str) -> None:
    """AC4: the live half runs locally, which is the only place it can run."""
    hooks = _local_hooks()
    assert hook_id in hooks, (
        f"{hook_id!r} is absent from .pre-commit-config.yaml. Its wrapper header "
        f"and its CI workflow both claim it runs as a pre-commit hook; CI has no "
        f"live venv, so an unregistered hook means the live check never runs"
    )


@pytest.mark.parametrize("hook_id", _REQUIRED_HOOK_IDS)
def test_gate_runs_on_the_files_that_define_the_pin_set(hook_id: str) -> None:
    """The trigger must cover both inputs to the pin set, not just the lock.

    ``pyproject.toml`` carries the ``[tool.onex.git-source-authority]`` table
    and the ``[tool.uv.sources]`` revs, so a change there moves what the gate
    checks even when ``uv.lock`` is untouched.
    """
    hook = _local_hooks().get(hook_id)
    assert hook is not None, f"{hook_id!r} not registered"
    pattern = hook.get("files", "")
    assert "uv" in pattern and "lock" in pattern, (
        f"{hook_id!r} does not trigger on uv.lock (files={pattern!r})"
    )
    assert "pyproject" in pattern, (
        f"{hook_id!r} does not trigger on pyproject.toml (files={pattern!r}); the "
        f"authority table and the source revs live there"
    )


@pytest.mark.parametrize("hook_id", _REQUIRED_HOOK_IDS)
def test_gate_is_hard_fail_not_warn_only(hook_id: str) -> None:
    """Rule 5: a gate that cannot block is detection, and detection is ignored."""
    hook = _local_hooks().get(hook_id)
    assert hook is not None, f"{hook_id!r} not registered"
    assert hook.get("verbose") is not True or "entry" in hook
    assert "|| true" not in str(hook.get("entry", "")), (
        f"{hook_id!r} swallows its own exit status"
    )


@pytest.mark.parametrize("hook_id", _REQUIRED_HOOK_IDS)
def test_the_wrapper_the_config_names_exists_and_is_executable(hook_id: str) -> None:
    """A registered hook pointing at a missing wrapper passes by accident."""
    hook = _local_hooks().get(hook_id)
    assert hook is not None, f"{hook_id!r} not registered"
    entry = str(hook["entry"])
    script = next(part for part in entry.split() if part.endswith(".sh"))
    path = _REPO_ROOT / script
    assert path.is_file(), f"{hook_id!r} entry names {script}, which does not exist"


@pytest.mark.parametrize("hook_id", _REQUIRED_HOOK_IDS)
def test_gate_is_also_wired_in_ci(hook_id: str) -> None:
    """AC4's other half: pre-commit alone leaves a push with no gate at all."""
    workflows = list((_REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    script = hook_id.replace("-", "_")
    assert any(
        script in wf.read_text(encoding="utf-8")
        or hook_id in wf.read_text(encoding="utf-8")
        for wf in workflows
    ), f"no workflow in .github/workflows references {hook_id!r}"


def test_the_two_gates_resolve_one_authority_not_two() -> None:
    """OMN-18753 AC1/AC3: the reason the sibling gate was deferred is gone.

    It was deferred because it resolved its expected commit from
    ``git ls-remote <remote> refs/heads/main`` while the OMN-18675 venv guard
    resolves the canonical clone's checked-out ``dev`` head. omnimarket's
    ``main`` is release-synced, so it lags ``dev`` and the two demanded
    different commits at every moment except the instant main caught up —
    observed live 2026-09-18, the venv guard requiring ``cfd5b4eb`` while the
    dispatch gate required ``7f77f9d8`` on the same host in the same minute.
    Registering a gate that structurally cannot pass would have been worse
    than leaving it unregistered.

    OMN-18752 deleted that resolution source. This test reads the gate's
    source for the probe rather than trusting the comment that says it is
    gone, because the deferral can only be lifted for as long as it stays
    gone: re-adding a remote-branch probe would restore the contradiction and
    a registered gate would then block every commit on this host.
    """
    code = _executable_source(
        _REPO_ROOT / "scripts" / "check_omnimarket_dispatch_drift.py"
    )
    assert "ls-remote" not in code and "ls_remote" not in code, (
        "check_omnimarket_dispatch_drift.py resolves a remote branch again. That "
        "is the split OMN-18752 removed and OMN-18753 registered the gate on the "
        "strength of; with the gate now registered it would block every commit"
    )


@pytest.mark.parametrize("hook_id", _REQUIRED_HOOK_IDS)
def test_the_wrapper_does_not_prescribe_a_remedy_that_breaks_the_host(
    hook_id: str,
) -> None:
    """A registered gate's header is the first thing a blocked committer reads.

    ``uv lock --upgrade-package omnimarket`` cannot move the pin: the rev is
    immutable and is INPUT to the resolve, not output. A committer who reaches
    for it and then hand-edits the rev to make it "work" desynchronises the
    lock from the canonical clone, and the OMN-18675 in-process guard then
    refuses every ``onex delegate`` on the host. OMN-18753 names that standing
    trap, and it was printed by the dispatch gate's own wrapper header.
    """
    hook = _local_hooks()[hook_id]
    entry = str(hook["entry"])
    script = next(part for part in entry.split() if part.endswith(".sh"))
    header = (_REPO_ROOT / script).read_text(encoding="utf-8")
    offending = "uv lock --upgrade-package omnimarket"
    for line in header.splitlines():
        stripped = line.lstrip("# ").strip()
        if stripped.startswith(offending):
            raise AssertionError(
                f"{script} prescribes {offending!r} as a remedy. It cannot move an "
                f"immutable rev, and hand-editing the rev instead breaks "
                f"`onex delegate` for every lane on the host. The sanctioned "
                f"advance is sibling-lock-refresh.yml (OMN-18752)."
            )
