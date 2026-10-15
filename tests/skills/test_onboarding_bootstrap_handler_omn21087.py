# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The pre-Python onboarding entrypoint loads only its declared Bash handler."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"
NODE = REPO / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
HANDLER = NODE / "handler_onboarding_preflight.sh"

pytestmark = pytest.mark.unit


def test_node_declares_the_bootstrap_handler_and_its_verified_bytes() -> None:
    contract = yaml.safe_load((NODE / "contract.yaml").read_text())
    bootstrap = contract["metadata"]["bootstrap_handler"]
    assert bootstrap["language"] == "bash"
    assert NODE / bootstrap["source"] == HANDLER
    digest = hashlib.sha256(HANDLER.read_bytes()).hexdigest()
    fingerprint = bootstrap["sha256_fingerprint"]
    assert fingerprint.replace(":", "") == digest
    assert f'local digest="{fingerprint}"' in SCRIPT.read_text()
    for entrypoint in bootstrap["entrypoints"]:
        assert re.search(rf"^{entrypoint}\(\) \{{", HANDLER.read_text(), re.M)
    subprocess.run(["/bin/bash", "-n", str(HANDLER)], check=True)


@pytest.mark.parametrize("tampered", [False, True])
def test_downloaded_entrypoint_verifies_handler_before_sourcing(
    tmp_path: Path, tampered: bool
) -> None:
    """Exercise the standalone download path with no checkout and no Python."""
    script = tmp_path / "lab-onboarding.sh"
    shutil.copyfile(SCRIPT, script)
    home = tmp_path / "home"
    bindir = home / ".local/bin"
    bindir.mkdir(parents=True)
    served = tmp_path / "served.sh"
    served.write_text(
        'touch "$HOME/unverified-handler-ran"\n' if tampered else HANDLER.read_text()
    )
    curl = bindir / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = -o ]; then cp "$SERVED_HANDLER" "$2"; exit; fi\n'
        "  shift\n"
        "done\n"
        "exit 1\n"
    )
    curl.chmod(0o755)
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(tmp_path),
        "SERVED_HANDLER": str(served),
        "ONBOARD_NOTIFY": "0",
        "ONBOARD_TEST_OS": "Darwin",
        "ONBOARD_TEST_MACOS": "14.5",
        "ONBOARD_TEST_PORTS_BUSY": "",
        "ONBOARD_TEST_NO_GUI": "1",
        "ONBOARD_TEST_NO_USER_SHELL": "1",
        "ONBOARD_TEST_DISK_GB": "100",
        "ONBOARD_TEST_RAM_GB": "32",
        "ONBOARD_TEST_CPUS": "10",
        "ONBOARD_TEST_VM": "0",
        "ONBOARD_TEST_ADMIN": "1",
        "ONBOARD_TEST_NEEDS_ADMIN": "0",
    }
    result = subprocess.run(
        ["/bin/bash", str(script), "--preflight-only", "--no-containers"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert not (home / "unverified-handler-ran").exists()
    if tampered:
        assert result.returncode == 1, result.stdout + result.stderr
        assert "cannot load the checksum-pinned" in result.stderr
        assert "Phase 0" not in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Phase 0/6 PASSED" in result.stdout
        assert "Preflight only: nothing was changed." in result.stdout
    downloaded = tmp_path / "omninode-onboarding/handler_onboarding_preflight.sh"
    assert downloaded.read_bytes() == served.read_bytes()
