# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shape + behaviour gate for the release-synced-main steps in ``release.yml``.

OMN-16642 / OMN-16289: ``main`` on this repository is the release boundary, not
a PR-merge target. ``required_status_checks`` on ``main`` is deliberately empty
and a repository ruleset restricts updates to ``refs/heads/main`` with the org
app ``onexbot-occ-writer`` as its only bypass actor. The only thing authorised
to advance the ref is the pair of steps asserted here. If they are removed or
renamed, nothing advances ``main`` and it silently desyncs from the last
release -- which is precisely the failure that stranded the plugin marketplace
manifest on a stale ``main`` (OMN-16193, OMN-13773).

The behaviour tests execute the committed ``run:`` script under ``bash -e``
against a stubbed ``curl`` on ``PATH``. Nothing is re-implemented here, so a
regression in the committed shell is a regression in these tests. That requires
the script to stay free of inline ``${{ }}`` expressions (values arrive through
``env:``), which is asserted directly.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
)

_MINT_STEP = "Mint onexbot-occ-writer app token"
_SYNC_STEP = "Sync main to release tag"
_RELEASE_STEP = "Create GitHub Release"

# The app that is the ruleset's bypass actor. The workflow GITHUB_TOKEN is not
# an authorisable identity for the restricted ref (GH006/GH013, OMN-16343).
_APP_TOKEN_ACTION = "actions/create-github-app-token@v3"


def _release_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    return workflow["jobs"]["release"]["steps"]


def _step(name: str) -> dict:
    for step in _release_steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found in the release job")


def _step_index(name: str) -> int:
    for index, step in enumerate(_release_steps()):
        if step.get("name") == name:
            return index
    raise AssertionError(f"step {name!r} not found in the release job")


def test_mint_and_sync_steps_exist() -> None:
    assert _step(_MINT_STEP)["uses"] == _APP_TOKEN_ACTION
    assert "run" in _step(_SYNC_STEP)


def test_sync_is_sequenced_after_the_github_release() -> None:
    """main only moves once the release has actually published."""
    assert _step_index(_RELEASE_STEP) < _step_index(_MINT_STEP)
    assert _step_index(_MINT_STEP) < _step_index(_SYNC_STEP)


def test_sync_is_the_last_step_of_the_release_job() -> None:
    assert _release_steps()[-1]["name"] == _SYNC_STEP


def test_mint_requests_both_required_permission_scopes() -> None:
    """A ``permission-*`` input REPLACES the installation's full set.

    Naming ``workflows`` alone silently drops ``contents: write`` and the token
    can then push no ref at all -- omnibase_core run 34065670492 (OMN-17272).
    """
    with_block = _step(_MINT_STEP)["with"]
    assert with_block["permission-contents"] == "write"
    assert with_block["permission-workflows"] == "write"


def test_mint_reads_the_app_credentials_from_org_secrets() -> None:
    with_block = _step(_MINT_STEP)["with"]
    assert "ONEXBOT_OCC_APP_ID" in with_block["app-id"]
    assert "ONEXBOT_OCC_PRIVATE_KEY" in with_block["private-key"]


def test_neither_step_runs_for_a_prerelease_tag() -> None:
    for name in (_MINT_STEP, _SYNC_STEP):
        assert "rc" in str(_step(name)["if"]), name


def test_sync_script_carries_no_inline_expressions() -> None:
    """Values arrive through ``env:`` so the committed shell stays runnable."""
    assert "${{" not in _step(_SYNC_STEP)["run"]


def test_sync_script_takes_its_values_from_env() -> None:
    env = _step(_SYNC_STEP)["env"]
    assert "steps.app-token.outputs.token" in env["APP_TOKEN"]
    # From the derived, already charset-guarded step output -- never from
    # `inputs.tag`, which is empty on the `push: tags:` trigger a real release
    # fires. See test_sync_tag_is_not_read_from_the_dispatch_input.
    assert env["SYNC_TAG"] == "${{ steps.tag.outputs.tag }}"


def test_sync_tag_is_not_read_from_the_dispatch_input() -> None:
    """Reading `inputs.tag` here kills the sync on every tag-push release.

    `inputs.tag` is defined only for `workflow_dispatch`. A release cut by
    pushing a tag resolves it to the empty string, `git rev-list -n 1 ""`
    fails, and main silently stops advancing -- the exact failure this whole
    pair exists to prevent.
    """
    assert "inputs.tag" not in str(_step(_SYNC_STEP)["env"])


def _run_sync_script(tmp_path: Path, *, http_code: str) -> subprocess.CompletedProcess:
    """Execute the committed sync script with a stubbed ``curl``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    captured = tmp_path / "curl-args.txt"
    stub = bin_dir / "curl"
    stub.write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$@" > {captured}\n'
        # Mirror the real flags the script passes: -o <file> and -w <format>.
        "out=\n"
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in\n'
        '    -o) out="$2"; shift 2;;\n'
        "    *) shift;;\n"
        "  esac\n"
        "done\n"
        'if [ -n "$out" ]; then echo "stub response" > "$out"; fi\n'
        f'printf "%s" "{http_code}"\n'
    )
    stub.chmod(0o755)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x\n")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "tag", "v9.9.9"], cwd=repo, check=True)

    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "SYNC_TAG": "v9.9.9",
            "APP_TOKEN": "stub-token",
            "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_REPOSITORY": "OmniNode-ai/omniclaude",
        }
    )
    result = subprocess.run(
        ["bash", "-e", "-c", _step(_SYNC_STEP)["run"]],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    result.captured_curl_args = captured.read_text() if captured.exists() else ""  # type: ignore[attr-defined]
    return result


def test_sync_script_requests_a_non_forced_ref_update(tmp_path: Path) -> None:
    """``force: false`` makes GitHub itself enforce the fast-forward."""
    result = _run_sync_script(tmp_path, http_code="200")
    assert result.returncode == 0, result.stderr
    payload = (tmp_path / "repo" / "update-main-ref.json").read_text()
    assert '"force":false' in payload
    assert "git/refs/heads/main" in result.captured_curl_args  # type: ignore[attr-defined]


def test_sync_script_fails_closed_on_a_refused_ref_update(tmp_path: Path) -> None:
    """A 422 is what a non-fast-forward looks like. It must not pass silently."""
    result = _run_sync_script(tmp_path, http_code="422")
    assert result.returncode != 0
    assert "refused with HTTP 422" in result.stdout
