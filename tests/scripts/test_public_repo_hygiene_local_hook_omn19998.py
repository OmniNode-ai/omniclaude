# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""omniclaude runs its own enforced hygiene classes locally (OMN-19998).

omniclaude ships the public-repo hygiene gate (OMN-18014) and is governed by
it like every other shipped repository: the required CI context
``public-repo-hygiene / public-repo-hygiene`` comes from the reusable workflow
in this checkout, and the local twin is declared in ``.pre-commit-config.yaml``.
The local hook must run the exported command without overriding the repository's
enforced classes or scope, or the local and CI verdicts diverge.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORTED = REPO_ROOT / ".pre-commit-hooks.yaml"
LOCAL = REPO_ROOT / ".pre-commit-config.yaml"
CALLER = REPO_ROOT / ".github" / "workflows" / "public-repo-hygiene.yml"
POLICY = REPO_ROOT / ".public-repo-hygiene.yaml"


def _exported_hook() -> dict[str, Any]:
    hooks = yaml.safe_load(EXPORTED.read_text(encoding="utf-8"))
    return next(h for h in hooks if h["id"] == "public-repo-hygiene")


def _local_hooks() -> list[dict[str, Any]]:
    config = yaml.safe_load(LOCAL.read_text(encoding="utf-8"))
    return [
        hook
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo.get("hooks", [])
        if hook.get("id") == "public-repo-hygiene"
    ]


def test_local_hook_runs_the_exported_hooks_command() -> None:
    local = _local_hooks()
    assert len(local) == 1, "exactly one local public-repo-hygiene hook is declared"
    assert local[0]["entry"].replace("python3 ", "", 1) == _exported_hook()["entry"]


def test_local_hook_is_not_narrowed() -> None:
    hook = _local_hooks()[0]
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False
    assert "files" not in hook
    assert "exclude" not in hook
    assert "pre-commit" in hook["stages"]


def test_local_hook_leaves_the_verdict_to_repository_policy() -> None:
    arguments = {
        arg.split("=", 1)[0] for arg in shlex.split(_local_hooks()[0]["entry"])
    }
    assert "--mode" not in arguments
    assert "--only-classes" not in arguments
    assert "--enforce-scope" not in arguments


def test_repository_policy_enforces_private_repo_names_on_added_lines() -> None:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    assert policy["enforce_scope"] == "added-lines"
    assert isinstance(policy["enforce_classes"], list)
    assert policy["enforce_classes"]
    assert "private-repo-name" in policy["enforce_classes"]


def test_caller_runs_the_reusable_in_this_checkout_so_the_context_is_produced() -> None:
    caller = yaml.safe_load(CALLER.read_text(encoding="utf-8"))
    job = caller["jobs"]["public-repo-hygiene"]
    assert job["uses"] == "./.github/workflows/public-repo-hygiene-reusable.yml"
