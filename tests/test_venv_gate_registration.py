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

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REQUIRED_HOOK_IDS = ("check-daemon-venv-skew",)

# Deliberately NOT registered — see test_dispatch_drift_gate_deferral_is_recorded.
_DEFERRED_HOOK_IDS = ("check-omnimarket-dispatch-drift",)


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


@pytest.mark.parametrize("hook_id", _DEFERRED_HOOK_IDS)
def test_dispatch_drift_gate_deferral_is_recorded(hook_id: str) -> None:
    """The sibling gate stays unregistered, and the config says why.

    ``check_omnimarket_dispatch_drift.py`` resolves its expected commit from
    ``git ls-remote <remote> refs/heads/main``. The OMN-18675 venv guard
    resolves the canonical clone's checked-out ``dev`` HEAD. omnimarket's
    ``main`` is release-synced, so it lags ``dev`` by the unreleased commits
    and the two gates demand different commits at every moment except the
    instant main catches up. Observed live 2026-09-18: the venv guard required
    ``cfd5b4eb`` (dev) while the dispatch gate required ``7f77f9d8`` (main).

    Neither had its live half registered, which is why the contradiction had
    never surfaced. Registering a gate that structurally cannot pass would be
    worse than leaving it unregistered, so it stays out until the baseline
    question is settled — and this test exists so "not registered" stays a
    recorded decision rather than drifting back into an oversight.
    """
    assert hook_id not in _local_hooks(), (
        f"{hook_id!r} was registered without settling its baseline against the "
        f"clone authority; see this test's docstring"
    )
    config_text = (_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert hook_id in config_text, (
        "the config must carry the reason this gate is absent, or the next "
        "reader sees only an omission"
    )
