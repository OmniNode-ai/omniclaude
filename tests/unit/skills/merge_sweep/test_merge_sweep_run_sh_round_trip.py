# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Executable round-trip proof for the merge_sweep run.sh shim."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_OMNICLAUDE_ROOT = Path(__file__).resolve().parents[4]
_RUN_SH = _OMNICLAUDE_ROOT / "plugins" / "onex" / "skills" / "merge_sweep" / "run.sh"
_OMNI_HOME_ROOT = _OMNICLAUDE_ROOT.parent
_WORKTREE_TICKET = _OMNICLAUDE_ROOT.parent.name

# Prefer OMNI_HOME/omnimarket (standard CI layout); fall back to worktree path via env override.
_OMNIMARKET_ROOT_DEFAULT = _OMNI_HOME_ROOT / "omnimarket"
_OMNIMARKET_ROOT_WORKTREE = (
    _OMNI_HOME_ROOT / "omnimarket" / "omni_worktrees" / _WORKTREE_TICKET / "omnimarket"
)
_OMNIMARKET_ROOT_OVERRIDE = os.environ.get("ONEX_TEST_OMNIMARKET_ROOT")
_OMNIMARKET_ROOT = (
    Path(_OMNIMARKET_ROOT_OVERRIDE)
    if _OMNIMARKET_ROOT_OVERRIDE
    else _OMNIMARKET_ROOT_DEFAULT
    if _OMNIMARKET_ROOT_DEFAULT.is_dir()
    else _OMNIMARKET_ROOT_WORKTREE
)
_EVENT_TYPE = "omnimarket.pr-lifecycle-orchestrator-start"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _build_uv_wrapper(path: Path, real_uv: str, capture_dir: Path) -> None:
    _write_executable(
        path,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import subprocess",
                "import sys",
                "from pathlib import Path",
                "",
                f"REAL_UV = {real_uv!r}",
                f"CAPTURE_DIR = Path({str(capture_dir)!r})",
                "CAPTURE_DIR.mkdir(parents=True, exist_ok=True)",
                'with (CAPTURE_DIR / "uv-argv.jsonl").open("a", encoding="utf-8") as handle:',
                '    handle.write(json.dumps(sys.argv[1:]) + "\\n")',
                'if "-m" in sys.argv and "omnimarket.nodes.node_pr_lifecycle_orchestrator" in sys.argv:',
                "    for index, arg in enumerate(sys.argv):",
                '        if arg == "--input" and index + 1 < len(sys.argv):',
                '            (CAPTURE_DIR / "input-envelope.json").write_text(',
                "                sys.argv[index + 1],",
                '                encoding="utf-8",',
                "            )",
                "            break",
                "raise SystemExit(subprocess.run([REAL_UV, *sys.argv[1:]], check=False).returncode)",
            ]
        ),
    )


@pytest.mark.unit
def test_run_sh_executes_real_cli_and_emits_contract_envelope(tmp_path: Path) -> None:
    """run.sh must build the envelope, invoke the real CLI, and persist results."""
    if not _RUN_SH.is_file():
        pytest.skip(f"missing run.sh at {_RUN_SH}")
    if not _OMNIMARKET_ROOT.is_dir():
        pytest.skip(
            f"missing omnimarket root at {_OMNIMARKET_ROOT}; set ONEX_TEST_OMNIMARKET_ROOT to override"
        )

    real_uv = shutil.which("uv")
    assert real_uv is not None, "uv is required to execute the merge_sweep shim"

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture_dir = tmp_path / "capture"
    state_dir = tmp_path / "state"
    omni_home = tmp_path / "omni_home"
    omni_home.mkdir()
    (omni_home / "omnimarket").symlink_to(_OMNIMARKET_ROOT, target_is_directory=True)

    _build_uv_wrapper(fake_bin / "uv", real_uv, capture_dir)
    _write_executable(fake_bin / "gh", "#!/usr/bin/env bash\nexit 0\n")

    run_id = "omn-10182-run-sh"
    env = {
        **os.environ,
        "OMNI_HOME": str(omni_home),
        "ONEX_STATE_DIR": str(state_dir),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }
    completed = subprocess.run(
        [
            "bash",
            str(_RUN_SH),
            "--dry-run",
            "--inventory-only",
            "--run-id",
            run_id,
        ],
        capture_output=True,
        check=False,
        cwd=_OMNICLAUDE_ROOT,
        env=env,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr

    result = json.loads(completed.stdout)
    assert result["final_state"] == "COMPLETE"
    assert result["prs_inventoried"] == 0
    assert result["prs_merged"] == 0
    assert result["prs_fixed"] == 0

    envelope = json.loads((capture_dir / "input-envelope.json").read_text("utf-8"))
    assert envelope["event_type"] == _EVENT_TYPE
    assert envelope["correlation_id"] == envelope["payload"]["correlation_id"]
    assert envelope["payload"] == {
        "correlation_id": envelope["payload"]["correlation_id"],
        "run_id": run_id,
        "dry_run": True,
        "inventory_only": True,
        "fix_only": False,
        "merge_only": False,
        "repos": "",
        "max_parallel_polish": 20,
        "enable_auto_rebase": True,
        "use_dag_ordering": True,
        "enable_trivial_comment_resolution": True,
        "enable_admin_merge_fallback": True,
        "admin_fallback_threshold_minutes": 15,
        "verify": False,
        "verify_timeout_seconds": 30,
    }

    invocations = [
        json.loads(line)
        for line in (capture_dir / "uv-argv.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    assert any(args[:3] == ["run", "python", "-"] for args in invocations)
    assert any(
        args[:5]
        == [
            "run",
            "python",
            "-m",
            "omnimarket.nodes.node_pr_lifecycle_orchestrator",
            "--input",
        ]
        for args in invocations
    )

    result_path = state_dir / "merge-sweep" / run_id / "result.json"
    persisted = json.loads(result_path.read_text("utf-8"))
    assert persisted["status"] == "success"
    assert persisted["run_id"] == run_id
    assert persisted["final_state"] == "COMPLETE"
