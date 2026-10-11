# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""omniclaude runs its own deployment-config class locally (OMN-20940).

omniclaude ships the deployment-config class of the public-repo hygiene gate
(OMN-20923) and is governed by it like every other shipped repository: the
required CI context ``public-repo-hygiene / deployment-config`` comes from the
reusable workflow in this checkout, and the local twin is declared in
``.pre-commit-config.yaml``. The local hook must run the same script, class and
arguments as the exported hook, or the local and CI verdicts diverge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORTED = REPO_ROOT / ".pre-commit-hooks.yaml"
LOCAL = REPO_ROOT / ".pre-commit-config.yaml"
CALLER = REPO_ROOT / ".github" / "workflows" / "public-repo-hygiene.yml"
REUSABLE = REPO_ROOT / ".github" / "workflows" / "public-repo-hygiene-reusable.yml"


def _exported_hook() -> dict[str, Any]:
    hooks = yaml.safe_load(EXPORTED.read_text(encoding="utf-8"))
    return next(h for h in hooks if h["id"] == "deployment-config")


def _local_hooks() -> list[dict[str, Any]]:
    config = yaml.safe_load(LOCAL.read_text(encoding="utf-8"))
    return [
        hook
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == "deployment-config"
    ]


def test_local_hook_runs_the_exported_hooks_command() -> None:
    local = _local_hooks()
    assert len(local) == 1, "exactly one deployment-config hook is declared"
    assert local[0]["entry"].replace("python3 ", "", 1) == _exported_hook()["entry"]


def test_local_hook_is_not_narrowed() -> None:
    hook = _local_hooks()[0]
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False
    assert "files" not in hook
    assert "exclude" not in hook
    assert "pre-commit" in hook["stages"]


def test_caller_runs_the_reusable_in_this_checkout_so_the_context_is_produced() -> None:
    caller = yaml.safe_load(CALLER.read_text(encoding="utf-8"))
    job = caller["jobs"]["public-repo-hygiene"]
    assert job["uses"] == "./.github/workflows/public-repo-hygiene-reusable.yml"
    reusable = yaml.safe_load(REUSABLE.read_text(encoding="utf-8"))
    assert reusable["jobs"]["deployment-config"]["name"] == "deployment-config"
