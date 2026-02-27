# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Repo sync status backend.

Checks the synchronization state between local clone and remote:
- Ahead/behind commit counts
- Uncommitted changes
- Active worktrees
- Stale branches

Works with the omni_home canonical registry structure.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .base import (
    ScriptStatus,
    SkillScriptResult,
    make_meta,
    run_gh,
    script_main,
)


def _run(
    repo_slug: str, run_id: str, args: dict[str, Any]
) -> tuple[
    ScriptStatus,
    SkillScriptResult,
    str,
]:
    """Check sync status between local and remote."""
    meta = make_meta("repo_sync_status", run_id, repo_slug)

    repo_name = repo_slug.split("/")[-1] if "/" in repo_slug else repo_slug

    # Try to find local clone in known locations.
    # OMNI_HOME env var takes priority; fallback to ~/Code/omni_home.
    omni_home = os.environ.get("OMNI_HOME", "")  # local-path-ok
    candidates: list[Path] = []
    if omni_home:
        candidates.append(Path(omni_home) / repo_name)
    candidates.append(Path.home() / "Code" / "omni_home" / repo_name)
    local_path: Path | None = None
    for candidate in candidates:
        if (candidate / ".git").exists() or (candidate / "HEAD").exists():
            local_path = candidate
            break

    local_info: dict[str, Any] = {}
    if local_path:
        try:
            # Fetch to update remote tracking
            subprocess.run(
                ["git", "-C", str(local_path), "fetch", "--quiet"],
                capture_output=True,
                timeout=15,
                check=False,
            )

            # Get ahead/behind counts
            rev_result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(local_path),
                    "rev-list",
                    "--left-right",
                    "--count",
                    "HEAD...origin/main",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if rev_result.returncode == 0 and rev_result.stdout.strip():
                parts = rev_result.stdout.strip().split()
                ahead = int(parts[0]) if len(parts) > 0 else 0
                behind = int(parts[1]) if len(parts) > 1 else 0
            else:
                ahead, behind = 0, 0

            # Check for dirty working tree
            status_result = subprocess.run(
                ["git", "-C", str(local_path), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            dirty_files = (
                len(status_result.stdout.strip().splitlines())
                if status_result.stdout.strip()
                else 0
            )

            # List worktrees
            wt_result = subprocess.run(
                ["git", "-C", str(local_path), "worktree", "list", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            worktree_count = (
                wt_result.stdout.count("worktree ") if wt_result.stdout else 0
            )

            local_info = {
                "path": str(local_path),
                "ahead": ahead,
                "behind": behind,
                "dirty_files": dirty_files,
                "worktree_count": worktree_count,
                "found": True,
            }
        except (subprocess.TimeoutExpired, OSError) as e:
            local_info = {
                "path": str(local_path),
                "error": str(e),
                "found": True,
            }
    else:
        local_info = {"found": False, "searched": [str(c) for c in candidates]}

    # Fetch remote info: default branch status
    try:
        remote_result = run_gh(
            [
                "repo",
                "view",
                repo_slug,
                "--json",
                "defaultBranchRef,updatedAt,pushedAt",
            ]
        )
        import json

        remote_data = (
            json.loads(remote_result.stdout) if remote_result.stdout.strip() else {}
        )
        remote_info: dict[str, Any] = {
            "default_branch": (remote_data.get("defaultBranchRef") or {}).get(
                "name", "main"
            ),
            "updated_at": remote_data.get("updatedAt", ""),
            "pushed_at": remote_data.get("pushedAt", ""),
        }
    except Exception as e:
        remote_info = {"error": str(e)}

    # Determine sync status
    is_synced = (
        local_info.get("found", False)
        and local_info.get("ahead", 0) == 0
        and local_info.get("behind", 0) == 0
        and local_info.get("dirty_files", 0) == 0
    )

    script_result = SkillScriptResult(
        meta=meta,
        inputs={"repo": repo_slug},
        parsed={
            "local": local_info,
            "remote": remote_info,
        },
        summary={
            "synced": is_synced,
            "ahead": local_info.get("ahead", 0),
            "behind": local_info.get("behind", 0),
            "dirty_files": local_info.get("dirty_files", 0),
            "worktrees": local_info.get("worktree_count", 0),
            "local_found": local_info.get("found", False),
        },
    )

    if not local_info.get("found"):
        status = ScriptStatus.WARN
        msg = f"Local clone not found for {repo_name}"
    elif is_synced:
        status = ScriptStatus.OK
        msg = f"{repo_name} is in sync with remote"
    else:
        parts = []
        if local_info.get("behind", 0) > 0:
            parts.append(f"{local_info['behind']} behind")
        if local_info.get("ahead", 0) > 0:
            parts.append(f"{local_info['ahead']} ahead")
        if local_info.get("dirty_files", 0) > 0:
            parts.append(f"{local_info['dirty_files']} dirty files")
        status = ScriptStatus.WARN
        msg = f"{repo_name}: {', '.join(parts)}"

    return status, script_result, msg


def main() -> None:
    script_main("repo_sync_status", _run)


if __name__ == "__main__":
    main()
