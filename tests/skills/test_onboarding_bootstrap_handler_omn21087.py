# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The pre-Python onboarding entrypoint loads only its declared Bash handler."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

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
    assert re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/[0-9a-f]{40}/\$rel",
        SCRIPT.read_text(),
    )
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
    if tampered:
        served.write_text('touch "$HOME/unverified-handler-ran"\n')
    else:
        # What GitHub serves: the handler at the commit the download URL names.
        served.write_bytes(_handler_at(_download_commit()))
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


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


def _download_commit() -> str:
    match = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        SCRIPT.read_text(),
    )
    assert match
    commit = match.group(1)
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit)
    return commit


def _handler_at(commit: str) -> bytes:
    served = _git("show", f"{commit}:{HANDLER.relative_to(REPO).as_posix()}")
    assert served.returncode == 0, served.stderr.decode(errors="replace")
    return served.stdout


def test_the_downloaded_handler_comes_from_a_commit_on_this_history() -> None:
    """A downloaded script fetches its handler from the commit its URL names.

    A commit that only a merged branch carried is unreachable once the branch
    goes, and GitHub may stop serving it; every downloaded copy would then fail
    at preflight. The URL must name a commit on this history whose handler is
    the bytes the script checks.
    """
    text = SCRIPT.read_text()
    match = re.search(
        r"https://raw\.githubusercontent\.com/OmniNode-ai/omniclaude/([0-9a-f]{40})/\$rel",
        text,
    )
    assert match
    commit = match.group(1)
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        _git("fetch", "--no-tags", "--depth=1", "origin", commit)
    assert _git("cat-file", "-e", f"{commit}^{{commit}}").returncode == 0, (
        f"the handler URL names {commit}, which origin no longer serves"
    )
    if _git("merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
        if _git("rev-parse", "--is-shallow-repository").stdout.strip() == b"true":
            _git("fetch", "--no-tags", "--unshallow", "origin")
    assert _git("merge-base", "--is-ancestor", commit, "HEAD").returncode == 0, (
        f"the handler URL names {commit}, which is not on this branch's history"
    )
    # OMN-21163: the download checks its own digest. A pull request that changes
    # the handler cannot name a dev commit holding the new bytes, so for that one
    # change the download keeps the handler already on dev.
    digest = re.search(r'local download_digest="([0-9a-f:]+)"', text)
    assert digest
    assert hashlib.sha256(_handler_at(commit)).hexdigest() == digest.group(1).replace(
        ":", ""
    )
