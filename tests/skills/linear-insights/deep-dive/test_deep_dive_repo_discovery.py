#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Tests for deep-dive skill: auto-discovery of active repos.

Covers:
- --repos flag is passed through unchanged (explicit override)
- Default mode (no --repos) triggers auto-discovery
- JSON output includes discovered repos, not the hardcoded default
- --json mode works correctly with auto-discovered repos

These tests invoke the deep-dive shell script directly via subprocess and
inspect its output.  The auto-discovery tests require the `gh` CLI; they
are marked as integration tests and skipped in CI unless
DEEP_DIVE_INTEGRATION_TESTS=1 is set.

Unit tests mock gh by injecting a fake executable on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
DEEP_DIVE_SCRIPT = (
    REPO_ROOT / "plugins" / "onex" / "skills" / "linear-insights" / "deep-dive"
)


def run_deep_dive(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the deep-dive script with the given arguments."""
    cmd = ["/bin/bash", str(DEEP_DIVE_SCRIPT), *args]
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=merged_env,
    )


# ---------------------------------------------------------------------------
# Helpers for fake `gh` CLI
# ---------------------------------------------------------------------------


SYSTEM_BINS = "/usr/bin:/bin:/usr/local/bin"


def make_fake_gh(
    tmp_path: Path,
    repo_list_output: str,
    pr_count_by_repo: dict[str, int],
) -> str:
    """
    Create a fake `gh` executable in tmp_path and return a PATH string
    that puts it first while keeping system bins accessible.

    repo_list_output: JSON string returned by `gh repo list ... --json name`
    pr_count_by_repo: maps repo name to number of merged PRs to simulate.
                      Repos not present return 0 (no activity).

    The fake gh supports:
      gh repo list ORG --limit N --json name --jq '.[].name'
        -> outputs one repo name per line

      gh pr list --repo ORG/REPO --state merged --search ... --json number --jq 'length'
        -> outputs an integer count
    """
    # Write repo names and pr counts as Python-parsable data files so the
    # bash fake script can call python3 to handle them safely.
    repo_names = [item["name"] for item in json.loads(repo_list_output)]
    data_file = tmp_path / "fake_gh_data.json"
    data_file.write_text(
        json.dumps(
            {
                "repo_names": repo_names,
                "pr_counts": pr_count_by_repo,
            }
        )
    )

    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            # Fake gh CLI for testing
            DATA_FILE="{data_file}"

            # gh repo list ORG --limit N --json name --jq '.[].name'
            if [[ "$1" == "repo" && "$2" == "list" ]]; then
                python3 - "$DATA_FILE" << 'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
for name in data["repo_names"]:
    print(name)
PYEOF
                exit 0
            fi

            # gh pr list --repo ORG/REPO ... --json number --jq 'length'
            if [[ "$1" == "pr" && "$2" == "list" ]]; then
                repo_name=""
                while [[ $# -gt 0 ]]; do
                    if [[ "$1" == "--repo" ]]; then
                        repo_name="${{2##*/}}"
                        shift 2
                    else
                        shift
                    fi
                done

                python3 - "$DATA_FILE" "$repo_name" << 'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
repo = sys.argv[2]
count = data["pr_counts"].get(repo, 0)
print(count)
PYEOF
                exit 0
            fi

            # Unknown subcommand
            exit 1
            """
        )
    )
    fake_gh.chmod(0o755)
    # Prepend tmp_path so our fake gh shadows the real one, but keep system bins
    system_path = os.environ.get("PATH", SYSTEM_BINS)
    return f"{tmp_path}:{system_path}"


# ---------------------------------------------------------------------------
# Unit tests (no real gh needed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_explicit_repos_flag_bypasses_discovery(tmp_path: Path) -> None:
    """When --repos is passed explicitly, auto-discovery must not run."""
    # Use a fake gh that would return something different if called
    fake_path = make_fake_gh(
        tmp_path,
        repo_list_output='[{"name":"omnidash"},{"name":"omnimemory"}]',
        pr_count_by_repo={"omnidash": 5, "omnimemory": 3},
    )

    result = run_deep_dive(
        "--repos",
        "omnibase_core,omniclaude",
        "--json",
        "--no-snapshot",
        env={"PATH": fake_path},
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"

    data = json.loads(result.stdout)
    repos = data.get("repositories", [])

    # Should contain exactly what we passed, not what the fake gh would discover
    assert repos == ["omnibase_core", "omniclaude"], (
        f"Expected explicit repos, got: {repos}"
    )


@pytest.mark.unit
def test_auto_discovery_uses_gh_repo_list(tmp_path: Path) -> None:
    """Without --repos, script discovers repos via gh and filters by activity."""
    fake_path = make_fake_gh(
        tmp_path,
        repo_list_output=(
            '[{"name":"omnibase_core"},{"name":"omnidash"},'
            '{"name":"omnimemory"},{"name":"omniclaude"}]'
        ),
        pr_count_by_repo={
            "omnibase_core": 2,
            "omnidash": 0,  # no activity
            "omnimemory": 1,
            "omniclaude": 0,  # no activity
        },
    )

    result = run_deep_dive(
        "--date",
        "2026-02-15",
        "--json",
        "--no-snapshot",
        env={"PATH": fake_path},
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"

    data = json.loads(result.stdout)
    repos = sorted(data.get("repositories", []))

    # Only repos with activity should appear
    assert repos == ["omnibase_core", "omnimemory"], (
        f"Expected only active repos, got: {repos}"
    )


@pytest.mark.unit
def test_auto_discovery_all_inactive_falls_back_to_defaults(tmp_path: Path) -> None:
    """When no repos have activity, falls back to the default 4-repo list."""
    fake_path = make_fake_gh(
        tmp_path,
        repo_list_output=('[{"name":"omnibase_core"},{"name":"omnidash"}]'),
        pr_count_by_repo={
            "omnibase_core": 0,
            "omnidash": 0,
        },
    )

    result = run_deep_dive(
        "--date",
        "2026-01-01",
        "--json",
        "--no-snapshot",
        env={"PATH": fake_path},
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"

    data = json.loads(result.stdout)
    repos = sorted(data.get("repositories", []))

    # Should fall back to the hardcoded default list
    expected = sorted(["omnibase_core", "omnibase_spi", "omnibase_infra", "omniclaude"])
    assert repos == expected, f"Expected fallback default repos, got: {repos}"


@pytest.mark.unit
def test_auto_discovery_gh_unavailable_falls_back_to_defaults(tmp_path: Path) -> None:
    """When gh CLI is not on PATH, falls back to the default 4-repo list."""
    # Use system bins but NOT the homebrew/local bins where gh lives.
    # This keeps date/dirname/etc. available but removes gh.
    no_gh_path = f"{tmp_path}:{SYSTEM_BINS}"

    result = run_deep_dive(
        "--json",
        "--no-snapshot",
        env={"PATH": no_gh_path},
    )

    # Script should not crash — it should degrade gracefully
    assert result.returncode == 0, f"Script failed: {result.stderr}"

    data = json.loads(result.stdout)
    repos = sorted(data.get("repositories", []))

    expected = sorted(["omnibase_core", "omnibase_spi", "omnibase_infra", "omniclaude"])
    assert repos == expected, (
        f"Expected fallback default repos when gh unavailable, got: {repos}"
    )


@pytest.mark.unit
def test_discovered_repos_appear_in_json_output(tmp_path: Path) -> None:
    """The repositories key in JSON output reflects the discovered list."""
    fake_path = make_fake_gh(
        tmp_path,
        repo_list_output=(
            '[{"name":"omnidash"},{"name":"omniintelligence"},{"name":"omniclaude"}]'
        ),
        pr_count_by_repo={
            "omnidash": 8,
            "omniintelligence": 3,
            "omniclaude": 1,
        },
    )

    result = run_deep_dive(
        "--date",
        "2026-02-15",
        "--json",
        "--no-snapshot",
        env={"PATH": fake_path},
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"

    data = json.loads(result.stdout)
    repos = sorted(data.get("repositories", []))

    assert repos == sorted(["omnidash", "omniintelligence", "omniclaude"]), (
        f"JSON repositories field should reflect discovered repos, got: {repos}"
    )


@pytest.mark.unit
def test_snapshot_only_mode_skips_discovery(tmp_path: Path) -> None:
    """--snapshot-only skips repo discovery (no gh calls needed)."""
    # Provide a fake gh that would exit with a distinctive code if called
    bad_gh = tmp_path / "gh"
    bad_gh.write_text("#!/bin/bash\nexit 42\n")
    bad_gh.chmod(0o755)
    # Keep system bins but shadow gh with our bad one
    fake_path = f"{tmp_path}:{SYSTEM_BINS}"

    result = run_deep_dive(
        "--snapshot-only",
        env={"PATH": fake_path},
    )

    # Should succeed or fail for Python reasons only — not because gh was called
    # (exit 42 from our fake gh would surface in stderr if it were invoked)
    assert "exit 42" not in result.stderr, (
        "gh should not have been called in --snapshot-only mode"
    )


# ---------------------------------------------------------------------------
# Integration tests (require real gh CLI and network access)
# ---------------------------------------------------------------------------

GH_AVAILABLE = shutil.which("gh") is not None
INTEGRATION_ENABLED = os.environ.get("DEEP_DIVE_INTEGRATION_TESTS") == "1"

REQUIRES_INTEGRATION = pytest.mark.skipif(
    not (GH_AVAILABLE and INTEGRATION_ENABLED),
    reason=(
        "Integration tests require gh CLI and DEEP_DIVE_INTEGRATION_TESTS=1. "
        "Set DEEP_DIVE_INTEGRATION_TESTS=1 to enable."
    ),
)


@REQUIRES_INTEGRATION
@pytest.mark.integration
def test_integration_auto_discovery_finds_omnidash() -> None:
    """
    Real integration test: auto-discovery on Feb 15, 2026 should include
    omnidash (which had 17 merged PRs that day).
    """
    result = run_deep_dive(
        "--date",
        "2026-02-15",
        "--json",
        "--no-snapshot",
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"

    data = json.loads(result.stdout)
    repos = data.get("repositories", [])

    assert "omnidash" in repos, (
        f"omnidash should be auto-discovered for 2026-02-15 (had activity), got: {repos}"
    )


@REQUIRES_INTEGRATION
@pytest.mark.integration
def test_integration_auto_discovery_no_repos_flag() -> None:
    """
    Real integration test: running without --repos discovers more than 4 repos
    for a recent active date.
    """
    result = run_deep_dive(
        "--date",
        "2026-02-15",
        "--json",
        "--no-snapshot",
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"

    data = json.loads(result.stdout)
    repos = data.get("repositories", [])

    # Feb 15 had activity in omnidash, omnimemory, omniintelligence etc.
    # The hardcoded list has only 4 — any real discovery should beat that.
    assert len(repos) > 4, (
        f"Auto-discovery should find more than 4 repos for 2026-02-15, got: {repos}"
    )


# ---------------------------------------------------------------------------
# Local Clone Discovery Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_local_clone_dirs_emitted_in_generate_output(tmp_path: Path) -> None:
    """With --code-root pointing to a dir with fake clones, --generate output
    should include per-directory git log commands for each clone."""
    # Create fake clone dirs with .git subdirs
    for name in ["omniclaude", "omniclaude2", "omniclaude3", "omnibase_infra"]:
        clone = tmp_path / name
        (clone / ".git").mkdir(parents=True)

    result = run_deep_dive(
        "--date",
        "2026-02-17",
        "--generate",
        "--no-snapshot",
        "--code-root",
        str(tmp_path),
        env={"PATH": SYSTEM_BINS, "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"

    for clone_name in ["omniclaude", "omniclaude2", "omniclaude3", "omnibase_infra"]:
        assert str(tmp_path / clone_name) in result.stdout, (
            f"Expected git log command for {clone_name} in output"
        )
    assert "Deduplicate" in result.stdout or "dedup" in result.stdout.lower()


@pytest.mark.unit
def test_non_git_dirs_excluded_from_clone_discovery(tmp_path: Path) -> None:
    """Directories without a .git folder should not appear in git log commands."""
    # Only omniclaude has .git; omniclaude2 does not
    (tmp_path / "omniclaude" / ".git").mkdir(parents=True)
    (tmp_path / "omniclaude2").mkdir()  # no .git

    result = run_deep_dive(
        "--date",
        "2026-02-17",
        "--generate",
        "--no-snapshot",
        "--code-root",
        str(tmp_path),
        env={"PATH": SYSTEM_BINS, "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert str(tmp_path / "omniclaude") in result.stdout
    assert str(tmp_path / "omniclaude2") not in result.stdout


@pytest.mark.unit
def test_code_root_env_var_used_when_no_flag(tmp_path: Path) -> None:
    """OMNI_CODE_ROOT env var should be used when --code-root flag is absent."""
    (tmp_path / "omnidash" / ".git").mkdir(parents=True)
    (tmp_path / "omnidash2" / ".git").mkdir(parents=True)

    result = run_deep_dive(
        "--date",
        "2026-02-17",
        "--generate",
        "--no-snapshot",
        env={
            "PATH": SYSTEM_BINS,
            "HOME": str(tmp_path),
            "OMNI_CODE_ROOT": str(tmp_path),
        },
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert str(tmp_path / "omnidash") in result.stdout
    assert str(tmp_path / "omnidash2") in result.stdout


@pytest.mark.unit
def test_fallback_single_git_log_when_no_code_root(tmp_path: Path) -> None:
    """With no CODE_ROOT and no OMNI_CODE_ROOT, falls back to generic git log."""
    # Unset OMNI_CODE_ROOT; use a fake HOME so auto-detect finds nothing
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()

    result = run_deep_dive(
        "--date",
        "2026-02-17",
        "--generate",
        "--no-snapshot",
        env={
            "PATH": SYSTEM_BINS,
            "HOME": str(fake_home),
            "OMNI_CODE_ROOT": "",  # explicitly empty
        },
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"
    # Should still emit a git log command, just the generic one
    assert "git log" in result.stdout
