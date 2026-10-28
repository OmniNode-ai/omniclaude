# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21466: phase 6 reads the shell's answer, not the banner the shell prints.

Terminal.app's /etc/zshrc_Apple_Terminal prints a "Restored session:" line on
stdout of every new interactive shell, ahead of the answer. The check must pass
on a correct install anyway, and still fail for an alias, a function, or an
onex outside the workspace, naming what the shell returned.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
HANDLER = (
    REPO / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    "/handler_onboarding_preflight.sh"
)
BANNER = "Restored session: Tue Oct 27 18:49:00 CDT 2026"

STUB_SHELL = """#!/bin/bash
# stands in for the developer's zsh: banner first, then the answer to -ic CMD
{banner}
whence() {{
  case "$1" in
    -p) printf '%s\\n' "$STUB_PATH" ;;
    -w) printf 'onex: %s\\n' "$STUB_KIND" ;;
  esac
}}
eval "$2"
"""


def _check(tmp_path: Path, kind: str, path: str, banner: bool = True) -> tuple[int, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "zsh"
    stub.write_text(STUB_SHELL.format(banner=f"echo '{BANNER}'" if banner else ":"))
    stub.chmod(0o755)
    ws = tmp_path / "ws"
    funcs = subprocess.run(
        [
            "awk",
            '/^user_shell\\(\\) \\{/ {on=1} /^masked\\(\\)/ {on=0} on {print}',
            str(HANDLER),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    check_fn = subprocess.run(
        [
            "awk",
            '/^shell_runs_workspace_onex\\(\\) \\{/ {on=1} on {print} on && /^\\}/ {exit}',
            str(HANDLER),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "shell_onex_path()" in funcs and "shell_runs_workspace_onex" in check_fn
    done = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'WORKSPACE="$1"\n{funcs}\n{check_fn}\nshell_runs_workspace_onex; echo "rc=$?"',
            "h",
            str(ws),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SHELL": str(stub),
            "HOME": str(tmp_path),
            "STUB_KIND": kind,
            "STUB_PATH": path,
        },
    )
    out = done.stdout
    rc = int(out.rsplit("rc=", 1)[1])
    return rc, out.rsplit("rc=", 1)[0]


def test_banner_before_the_wrapper_path_still_passes(tmp_path: Path) -> None:
    wrapper = tmp_path / "ws/omnibase_infra/scripts/onex"
    rc, out = _check(tmp_path, "command", str(wrapper))
    assert rc == 0, out
    assert "Restored session" not in out


@pytest.mark.parametrize("kind", ["alias", "function"])
def test_alias_or_function_fails_naming_what_the_shell_said(
    tmp_path: Path, kind: str
) -> None:
    rc, out = _check(tmp_path, kind, "")
    assert rc == 1
    assert f'"{kind}"' in out
    assert "Restored session" not in out


def test_path_outside_the_workspace_fails_naming_the_path(tmp_path: Path) -> None:
    other = "/opt/elsewhere/bin/onex"
    rc, out = _check(tmp_path, "file", other)
    assert rc == 1
    assert f'"{other}"' in out
    assert "Restored session" not in out
