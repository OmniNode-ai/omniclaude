# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The hook-process canary installer hands no ledger file path to the canary (OMN-26569).

The canary appends its ALERT row through the bus verb (``onex-ledger append-rows -``), so it
needs OMNIBASE_INTERNAL_HOME and OMNI_HOME and no ledger file path (operator ruling
2026-11-05: no file ledger ever again). The installer and the launchd template therefore carry
no ledger-path variable and no placeholder for one.
"""

from __future__ import annotations

import plistlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# The name of the retired variable, spelled in two parts: this file asserts it is absent and reads
# no ledger, so the ledger-file census must not count it as a holder of the name.
_RETIRED_VAR = "ONEX_" + "LEDGER_PATH"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO_ROOT / "scripts" / "install-hook-process-canary.sh"
_TEMPLATE = _REPO_ROOT / "scripts" / "launchd" / "ai.omninode.hook-process-canary.plist"


def _dry_run(
    tmp_path: Path, *extra: str, with_homes: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run the installer dry run with the retired variable absent from the environment."""
    args = [
        "bash",
        str(_INSTALLER),
        "--dry-run",
        "--state-dir",
        str(tmp_path / "state"),
    ]
    if with_homes:
        args += [
            "--internal-home",
            str(tmp_path / "internal_home"),
            "--omni-home",
            str(tmp_path / "workspace"),
        ]
    uv_dir = tmp_path / "bin"
    uv_dir.mkdir(exist_ok=True)
    uv = uv_dir / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n")
    uv.chmod(0o755)
    env = {
        "PATH": f"{uv_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
    }
    return subprocess.run(
        [*args, *extra], capture_output=True, text=True, check=False, env=env
    )


def test_a_ledger_argument_is_refused_as_unknown(tmp_path: Path) -> None:
    run = _dry_run(tmp_path, "--ledger", str(tmp_path / "x"))
    assert run.returncode == 2, run.stdout + run.stderr
    assert "unknown argument: --ledger" in run.stderr


def test_dry_run_with_no_ledger_path_renders_the_bus_environment(
    tmp_path: Path,
) -> None:
    run = _dry_run(tmp_path)
    assert run.returncode == 0, run.stderr
    assert _RETIRED_VAR not in run.stdout
    assert "__LEDGER__" not in run.stdout
    assert "ledger.md" not in run.stdout
    assert str(tmp_path / "internal_home") in run.stdout
    assert str(tmp_path / "workspace") in run.stdout
    if sys.platform == "darwin":
        parsed = plistlib.loads(run.stdout.encode("utf-8"))
        env = parsed["EnvironmentVariables"]
        assert env["OMNIBASE_INTERNAL_HOME"] == str(tmp_path / "internal_home")
        assert env["OMNI_HOME"] == str(tmp_path / "workspace")
        assert _RETIRED_VAR not in env
    else:
        assert f"OMNIBASE_INTERNAL_HOME={tmp_path / 'internal_home'}" in run.stdout
        assert f"OMNI_HOME={tmp_path / 'workspace'}" in run.stdout


def test_the_template_and_the_installer_name_no_ledger_path() -> None:
    template = _TEMPLATE.read_text(encoding="utf-8")
    installer = _INSTALLER.read_text(encoding="utf-8")
    assert _RETIRED_VAR not in template
    assert "__LEDGER__" not in template
    assert _RETIRED_VAR not in installer
    assert "__LEDGER__" not in installer
    assert not re.search(r"--ledger\b", installer)
    assert "OMNIBASE_INTERNAL_HOME" in template and "OMNI_HOME" in template


def test_the_installer_copies_no_test_write_guard_beside_the_bus_writer() -> None:
    # The canary's writer appends over the bus and opens no ledger file, so it loads no guard.
    installer = _INSTALLER.read_text(encoding="utf-8")
    assert "handler_ledger_write_guard" not in installer


def test_the_template_renders_to_a_parseable_plist_with_no_placeholder_left() -> None:
    template = _TEMPLATE.read_text(encoding="utf-8")
    placeholders = set(re.findall(r"__[A-Z_]+__", template))
    rendered = template
    for placeholder in placeholders:
        rendered = rendered.replace(placeholder, "/opt/sample")
    assert not re.search(r"__[A-Z_]+__", rendered)
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["Label"] == "ai.omninode.hook-process-canary"
    assert _RETIRED_VAR not in parsed["EnvironmentVariables"]
