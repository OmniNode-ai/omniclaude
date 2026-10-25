# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19479: the gh user shim caches the harness PR-link lookup and nothing else.

The shim (``scripts/user-bin/gh``) sits ahead of the real ``gh`` on PATH. These
tests put it in front of a counting fake ``gh`` and assert:

* AC1 (``-k cache``): two identical PR-link lookups on one branch inside the TTL
  make exactly one real call;
* AC2 (``-k passthrough``): every other command reaches the real ``gh`` with
  identical argv, and its stdout, stderr and exit code come back unchanged;
* AC4 (``-k lock``): two status-line renders against a stale cache run one
  refresh between them, not two.

No test touches the network.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"
INSTALLER = REPO_ROOT / "scripts" / "user-bin" / "install-gh-shim.sh"
# STATUSLINE_UNDER_TEST points the lock test at a pre-fix copy for a RED proof
# (git show origin/dev:<path> > file), as tests/hooks/test_statusline_pr_segment.sh does.
STATUSLINE = Path(
    os.environ.get("STATUSLINE_UNDER_TEST")
    or REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "statusline.sh"
)

FAKE_GH = r"""#!/bin/bash
# counting fake gh: one JSON line of argv per call, behaviour from env
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
if [ -n "${FAKE_GH_STDIN:-}" ]; then cat > "$FAKE_GH_STDIN"; fi
if [ -n "${FAKE_GH_SLEEP:-}" ]; then sleep "$FAKE_GH_SLEEP"; fi
printf '%s' "${FAKE_GH_STDOUT:-out:$*}"
printf '%s' "${FAKE_GH_STDERR:-}" >&2
exit "${FAKE_GH_RC:-0}"
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    fake_dir = tmp_path / "realbin"
    fake_dir.mkdir()
    _write_exec(fake_dir / "gh", FAKE_GH)
    repo = tmp_path / "repo"
    repo.mkdir()
    base_env = {
        "PATH": f"{SHIM.parent}:{fake_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "FAKE_GH_LOG": str(tmp_path / "calls.jsonl"),
        "GIT_CONFIG_NOSYSTEM": "1",
        # These suites test shim mechanics, not callers: run them as the PR watcher so the
        # PR-state read guard (OMN-19856) lets their pass-through shapes reach the fake gh.
        "ONEX_PR_WATCHER": "1",
    }
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "i",
        ],
    ):
        subprocess.run(cmd, cwd=repo, env=base_env, check=True)
    base_env["REPO"] = str(repo)
    return base_env


def _run(
    env: dict[str, str],
    *args: str,
    extra: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    e = dict(env)
    e.update(extra or {})
    return subprocess.run(
        ["gh", *args],
        cwd=env["REPO"],
        env=e,
        capture_output=True,
        text=True,
        input=stdin,
        timeout=30,
        check=False,
    )


def _calls(env: dict[str, str]) -> list[list[str]]:
    log = Path(env["FAKE_GH_LOG"])
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


# --- AC1: the two read shapes are cached -------------------------------------


@pytest.mark.unit
def test_cache_two_branch_lookups_make_one_real_call(env: dict[str, str]) -> None:
    first = _run(
        env,
        "pr",
        "view",
        "main",
        "--json",
        "url",
        extra={"FAKE_GH_STDOUT": '{"url":"u1"}'},
    )
    second = _run(
        env,
        "pr",
        "view",
        "main",
        "--json",
        "url",
        extra={"FAKE_GH_STDOUT": '{"url":"CHANGED"}'},
    )
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout == '{"url":"u1"}'
    assert len(_calls(env)) == 1


@pytest.mark.unit
def test_cache_current_branch_number_url_state_shape(env: dict[str, str]) -> None:
    for _ in range(3):
        r = _run(
            env,
            "pr",
            "view",
            "--json",
            "number,url,state",
            extra={"FAKE_GH_STDOUT": "x"},
        )
        assert r.returncode == 0
        assert r.stdout == "x"
    assert _calls(env) == [["pr", "view", "--json", "number,url,state"]]


@pytest.mark.unit
def test_cache_is_keyed_per_branch(env: dict[str, str]) -> None:
    _run(env, "pr", "view", "main", "--json", "url")
    _run(env, "pr", "view", "feature", "--json", "url")
    _run(env, "pr", "view", "main", "--json", "url")
    assert len(_calls(env)) == 2


# --- OMN-19479: the PR watcher's state answers the lookup before the cache or gh --


def _watcher_state(
    tmp_path: Path,
    prs: dict[str, dict[str, object]],
    *,
    age_s: int = 0,
) -> dict[str, str]:
    """Write a watcher state file ``age_s`` seconds old; return the env that points the shim at it."""
    tick = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_s))
    path = tmp_path / "watcher-state.json"
    path.write_text(json.dumps({"schema": 1, "last_tick": tick, "prs": prs}))
    return {"ONEX_PR_WATCHER_STATE": str(path)}


def _pr(
    number: int, head_ref: str, *, state: str = "OPEN", repo: str = "omniclaude"
) -> dict[str, object]:
    return {
        "facts": {
            "repo": repo,
            "number": number,
            "state": state,
            "head_ref": head_ref,
            "base": "dev",
        }
    }


def _with_origin(env: dict[str, str], url: str) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", url],
        cwd=env["REPO"],
        env={"PATH": env["PATH"], "HOME": env["HOME"], "GIT_CONFIG_NOSYSTEM": "1"},
        check=True,
    )


def _usage_caches(env: dict[str, str]) -> list[str]:
    d = Path(env["XDG_CACHE_HOME"]) / "omni" / "gh-usage"
    return [
        json.loads(line)["cache"]
        for f in sorted(d.glob("*.jsonl"))
        for line in f.read_text().splitlines()
        if line.strip()
    ]


@pytest.mark.unit
def test_watcher_answers_the_link_lookup_with_no_gh_call(
    env: dict[str, str], tmp_path: Path
) -> None:
    if shutil.which("jq") is None:
        pytest.skip("the watcher lookup needs jq")
    _with_origin(env, "https://github.com/OmniNode-ai/omniclaude.git")
    extra = _watcher_state(tmp_path, {"omniclaude#7": _pr(7, "main")})
    url = _run(env, "pr", "view", "--json", "url", extra=extra)
    full = _run(env, "pr", "view", "main", "--json", "number,url,state", extra=extra)
    assert url.returncode == 0
    assert json.loads(url.stdout) == {
        "url": "https://github.com/OmniNode-ai/omniclaude/pull/7"
    }
    assert json.loads(full.stdout) == {
        "number": 7,
        "state": "OPEN",
        "url": "https://github.com/OmniNode-ai/omniclaude/pull/7",
    }
    assert _calls(env) == []
    assert _usage_caches(env) == ["watcher", "watcher"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "case",
    ["stale", "no-open-pr", "merged-only", "two-open", "other-repo", "no-state"],
)
def test_watcher_miss_runs_the_real_gh(
    env: dict[str, str], tmp_path: Path, case: str
) -> None:
    if shutil.which("jq") is None:
        pytest.skip("the watcher lookup needs jq")
    _with_origin(env, "https://github.com/OmniNode-ai/omniclaude.git")
    prs: dict[str, dict[str, object]] = {"omniclaude#7": _pr(7, "main")}
    age = 0
    if case == "stale":
        age = 3600
    elif case == "no-open-pr":
        prs = {"omniclaude#7": _pr(7, "feature")}
    elif case == "merged-only":
        prs = {"omniclaude#7": _pr(7, "main", state="MERGED")}
    elif case == "two-open":
        prs["omniclaude#8"] = _pr(8, "main")
    elif case == "other-repo":
        prs = {"omnibase_core#7": _pr(7, "main", repo="omnibase_core")}
    extra = _watcher_state(tmp_path, prs, age_s=age)
    if case == "no-state":
        extra = {"ONEX_PR_WATCHER_STATE": str(tmp_path / "absent.json")}
    r = _run(
        env,
        "pr",
        "view",
        "--json",
        "url",
        extra={**extra, "FAKE_GH_STDOUT": '{"url":"from-gh"}'},
    )
    assert r.returncode == 0 and r.stdout == '{"url":"from-gh"}'
    assert len(_calls(env)) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "ref", ["7", "OmniNode-ai:main", "https://github.com/OmniNode-ai/omniclaude/pull/7"]
)
def test_watcher_is_not_asked_about_a_pr_number_url_or_owner_ref(
    env: dict[str, str], tmp_path: Path, ref: str
) -> None:
    """Only a branch name is looked up by head ref; every other argument goes to gh."""
    if shutil.which("jq") is None:
        pytest.skip("the watcher lookup needs jq")
    _with_origin(env, "https://github.com/OmniNode-ai/omniclaude.git")
    extra = _watcher_state(tmp_path, {"omniclaude#7": _pr(7, "main")})
    r = _run(
        env,
        "pr",
        "view",
        ref,
        "--json",
        "url",
        extra={**extra, "FAKE_GH_STDOUT": '{"url":"from-gh"}'},
    )
    assert r.returncode == 0 and r.stdout == '{"url":"from-gh"}'
    assert len(_calls(env)) == 1


@pytest.mark.unit
def test_watcher_never_answers_any_other_read_shape(
    env: dict[str, str], tmp_path: Path
) -> None:
    """A different field list (here ``state``) is not a harness link shape: gh answers it."""
    if shutil.which("jq") is None:
        pytest.skip("the watcher lookup needs jq")
    _with_origin(env, "https://github.com/OmniNode-ai/omniclaude.git")
    extra = _watcher_state(tmp_path, {"omniclaude#7": _pr(7, "main")})
    r = _run(
        env,
        "pr",
        "view",
        "--json",
        "state",
        extra={**extra, "FAKE_GH_STDOUT": '{"state":"x"}'},
    )
    assert r.stdout == '{"state":"x"}'
    assert len(_calls(env)) == 1


@pytest.mark.unit
def test_cache_expires_after_ttl(env: dict[str, str]) -> None:
    ttl0 = {"ONEX_GH_SHIM_TTL": "0"}
    _run(env, "pr", "view", "main", "--json", "url", extra=ttl0)
    _run(env, "pr", "view", "main", "--json", "url", extra=ttl0)
    assert len(_calls(env)) == 2


@pytest.mark.unit
def test_cache_keeps_no_pr_found_answer(env: dict[str, str]) -> None:
    miss = {
        "FAKE_GH_RC": "1",
        "FAKE_GH_STDOUT": "",
        "FAKE_GH_STDERR": 'no pull requests found for branch "main"',
    }
    a = _run(env, "pr", "view", "--json", "url", extra=miss)
    b = _run(env, "pr", "view", "--json", "url")
    assert a.returncode == b.returncode == 1
    assert "no pull requests found" in b.stderr
    assert len(_calls(env)) == 1


@pytest.mark.unit
def test_cache_never_keeps_other_failures(env: dict[str, str]) -> None:
    quota = {
        "FAKE_GH_RC": "1",
        "FAKE_GH_STDOUT": "",
        "FAKE_GH_STDERR": "GraphQL: API rate limit exceeded",
    }
    a = _run(env, "pr", "view", "--json", "url", extra=quota)
    b = _run(
        env, "pr", "view", "--json", "url", extra={"FAKE_GH_STDOUT": '{"url":"u"}'}
    )
    assert a.returncode == 1
    assert b.returncode == 0 and b.stdout == '{"url":"u"}'
    assert len(_calls(env)) == 2


@pytest.mark.unit
@pytest.mark.parametrize("verb", ["create", "ready", "close", "reopen", "merge"])
def test_cache_is_purged_by_a_pr_mutation(env: dict[str, str], verb: str) -> None:
    _run(
        env,
        "pr",
        "view",
        "--json",
        "url",
        extra={"FAKE_GH_RC": "1", "FAKE_GH_STDERR": "no pull requests found"},
    )
    mutation = ["pr", verb]
    if verb == "merge":
        # A merge queue-safe enqueue form reaches the existing purge path without
        # requiring the guard's live verification probes.
        mutation.extend(["1", "--match-head-commit", "deadbeef"])
    _run(env, *mutation)
    after = _run(
        env, "pr", "view", "--json", "url", extra={"FAKE_GH_STDOUT": '{"url":"new"}'}
    )
    assert after.stdout == '{"url":"new"}'
    assert len(_calls(env)) == 3


@pytest.mark.unit
def test_cache_purge_is_scoped_to_the_mutated_repository(
    env: dict[str, str], tmp_path: Path
) -> None:
    def clone(name: str, remote: str) -> Path:
        d = tmp_path / name
        d.mkdir()
        for cmd in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "remote", "add", "origin", remote],
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "i",
            ],
        ):
            subprocess.run(cmd, cwd=d, env=env, check=True)
        return d

    a = clone("a", "git@github.com:OmniNode-ai/repo_a.git")
    b = clone("b", "https://github.com/OmniNode-ai/repo_b.git")

    def gh(cwd: Path, *args: str) -> None:
        subprocess.run(
            ["gh", *args], cwd=cwd, env=env, capture_output=True, check=False
        )

    gh(a, "pr", "view", "--json", "url")
    gh(b, "pr", "create", "--fill")  # another repository: the repo_a entry survives
    gh(a, "pr", "view", "--json", "url")
    assert len(_calls(env)) == 2
    gh(
        b,
        "pr",
        "merge",
        "1",
        "-R",
        "OmniNode-ai/repo_a",
        "--match-head-commit",
        "deadbeef",
    )  # names repo_a: its entries are purged
    gh(a, "pr", "view", "--json", "url")
    assert len(_calls(env)) == 4


@pytest.mark.unit
def test_cache_outside_a_git_repo_passes_through(
    env: dict[str, str], tmp_path: Path
) -> None:
    outside = tmp_path / "nogit"
    outside.mkdir()
    for _ in range(2):
        subprocess.run(
            ["gh", "pr", "view", "--json", "url"],
            cwd=outside,
            env=env,
            check=False,
            capture_output=True,
        )
    assert len(_calls(env)) == 2


# --- AC2: everything else is untouched ----------------------------------------

PASSTHROUGH_CASES = [
    ["pr", "merge", "12", "--squash", "--match-head-commit", "abc"],
    ["pr", "edit", "12", "--add-label", "x"],
    ["api", "-X", "POST", "repos/o/r/issues/1/comments", "-f", "body=hi there"],
    ["pr", "checks", "12"],
    ["pr", "view", "--json", "url", "--jq", ".url"],
    ["pr", "view", "12", "--json", "url,headRefOid"],
    ["pr", "view", "-R", "o/r", "--json", "url"],
    ["api", "graphql", "-f", "query={ viewer { login } }"],
]


@pytest.mark.unit
@pytest.mark.parametrize("argv", PASSTHROUGH_CASES)
def test_passthrough_argv_output_and_exit_code(
    env: dict[str, str], argv: list[str]
) -> None:
    extra = {"FAKE_GH_RC": "3", "FAKE_GH_STDOUT": "o\nline2", "FAKE_GH_STDERR": "e!"}
    first = _run(env, *argv, extra=extra)
    second = _run(env, *argv, extra=extra)
    for r in (first, second):
        assert r.returncode == 3
        assert r.stdout == "o\nline2"
        assert r.stderr == "e!"
    assert _calls(env) == [argv, argv]


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "view", "7", "--json", "body", "-q", ".body"],
        ["pr", "view", "--json", "url"],
    ],
)
@pytest.mark.parametrize("exit_code", [0, 3])
def test_ci_passthrough_preserves_argv_output_and_exit_without_logs_or_cache(
    env: dict[str, str], tmp_path: Path, argv: list[str], exit_code: int
) -> None:
    e = dict(env)
    e.pop("ONEX_PR_WATCHER")
    calls_log = tmp_path / "gh-calls.log"
    state_dir = tmp_path / "state"
    e.update(
        {
            "GITHUB_ACTIONS": "true",
            "ONEX_GH_CALLS_LOG": str(calls_log),
            "ONEX_STATE_DIR": str(state_dir),
            "FAKE_GH_RC": str(exit_code),
            "FAKE_GH_STDERR": "stderr from CI\n",
        }
    )
    for output in ("body\nwith spaces", "changed output\n"):
        r = _run(e, *argv, extra={"FAKE_GH_STDOUT": output})
        assert r.returncode == exit_code, r.stderr
        assert r.stdout == output
        assert r.stderr == "stderr from CI\n"
        assert "REFUSED" not in r.stdout + r.stderr
    assert _calls(e) == [argv, argv]
    assert not calls_log.exists()
    assert not state_dir.exists()
    assert not Path(e["XDG_CACHE_HOME"]).exists()


@pytest.mark.unit
@pytest.mark.parametrize("github_actions", [None, "false", "1", "TRUE"])
def test_ci_passthrough_requires_exact_true(
    env: dict[str, str], github_actions: str | None
) -> None:
    e = dict(env)
    e.pop("ONEX_PR_WATCHER")
    if github_actions is not None:
        e["GITHUB_ACTIONS"] = github_actions
    r = _run(e, "pr", "view", "7", "--json", "body", "-q", ".body")
    assert r.returncode == 1
    assert "REFUSED (OMN-19856)" in r.stderr
    assert _calls(e) == []


@pytest.mark.unit
def test_passthrough_stdin(env: dict[str, str], tmp_path: Path) -> None:
    sink = tmp_path / "stdin.txt"
    r = _run(
        env,
        "api",
        "graphql",
        "--input",
        "-",
        extra={"FAKE_GH_STDIN": str(sink)},
        stdin='{"query":"q"}',
    )
    assert r.returncode == 0
    assert sink.read_text() == '{"query":"q"}'


@pytest.mark.unit
def test_passthrough_skips_a_second_shim_copy(
    env: dict[str, str], tmp_path: Path
) -> None:
    other = tmp_path / "othershim"
    other.mkdir()
    shutil.copy(SHIM, other / "gh")
    e = dict(env)
    e["PATH"] = f"{SHIM.parent}:{other}:{e['PATH']}"
    r = subprocess.run(
        ["gh", "pr", "checks", "1"],
        cwd=env["REPO"],
        env=e,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert r.returncode == 0
    assert _calls(env) == [["pr", "checks", "1"]]


def _coreutils_dir_without_gh(tmp_path: Path) -> Path:
    """A PATH entry carrying symlinks to the external tools the shim itself
    shells out to (``head``, ``grep``, ...) before it can decide there is no
    real ``gh`` -- but never a symlink to a real ``gh``.

    ``/usr/bin:/bin`` is not safe for that: GitHub-hosted Ubuntu runners ship
    ``gh`` preinstalled there (unlike a developer Mac, where it lives under
    Homebrew's prefix), so pointing PATH at those system dirs let the real
    binary answer this "no real gh" test on CI while it stayed loud locally.
    """
    safe = tmp_path / "safe-bin"
    safe.mkdir()
    for tool in ("head", "grep"):
        found = shutil.which(tool)
        assert found, f"{tool} not found on PATH; needed by the shim itself"
        (safe / tool).symlink_to(found)
    return safe


@pytest.mark.unit
def test_passthrough_no_real_gh_is_a_loud_127(
    env: dict[str, str], tmp_path: Path
) -> None:
    e = dict(env)
    e["PATH"] = f"{SHIM.parent}:{_coreutils_dir_without_gh(tmp_path)}"
    r = subprocess.run(
        ["gh", "--version"],
        cwd=env["REPO"],
        env=e,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 127
    assert "no real gh" in r.stderr


# --- installer ----------------------------------------------------------------


def _install_default(
    env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(INSTALLER), *args],
        cwd=env["REPO"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.unit
@pytest.mark.parametrize("directory_source", ["home", "xdg", "lane"])
def test_installer_default_dir_is_lanes_only(
    env: dict[str, str], tmp_path: Path, directory_source: str
) -> None:
    e = dict(env)
    e["PATH"] = f"{tmp_path / 'realbin'}:/usr/bin:/bin"
    destination = Path(e["HOME"]) / ".local/share/omni/lane-bin"
    if directory_source in ("xdg", "lane"):
        e["XDG_DATA_HOME"] = str(tmp_path / "xdg data")
        destination = Path(e["XDG_DATA_HOME"]) / "omni/lane-bin"
    if directory_source == "lane":
        e["ONEX_LANE_BIN_DIR"] = str(tmp_path / "lane bin")
        destination = Path(e["ONEX_LANE_BIN_DIR"])
    r = _install_default(e)
    assert r.returncode == 0, r.stderr
    assert os.access(destination / "gh", os.X_OK)
    assert (destination / "gh").read_bytes() == SHIM.read_bytes()
    assert (destination / "gh_route.py").read_bytes() == (
        SHIM.parent / "gh_route.py"
    ).read_bytes()
    assert not (Path(e["HOME"]) / ".local/bin/gh").exists()
    checked = _install_default(e, "--check")
    assert checked.returncode == 0, checked.stderr
    assert "CHECK:" in checked.stdout
    assert "identical to source" in checked.stdout


@pytest.mark.unit
@pytest.mark.parametrize("legacy_is_shim", [True, False])
def test_installer_retires_legacy_shim(
    env: dict[str, str], tmp_path: Path, legacy_is_shim: bool
) -> None:
    e = dict(env)
    legacy_dir = Path(e["HOME"]) / ".local/bin"
    legacy_dir.mkdir(parents=True)
    legacy_gh = legacy_dir / "gh"
    original = SHIM.read_text() if legacy_is_shim else "#!/bin/bash\necho mine\n"
    _write_exec(legacy_gh, original)
    legacy_router = legacy_dir / "gh_route.py"
    legacy_router.write_text("legacy router\n")
    real_dir = tmp_path / "realbin"
    e["PATH"] = f"{legacy_dir}:{real_dir}:/usr/bin:/bin"
    r = _install_default(e)
    assert r.returncode == 0, r.stderr
    assert (Path(e["HOME"]) / ".local/share/omni/lane-bin/gh").exists()
    if legacy_is_shim:
        assert not legacy_gh.exists()
        assert not legacy_router.exists()
        retirement_lines = [line for line in r.stdout.splitlines() if "retired" in line]
        assert len(retirement_lines) == 1
        assert str(legacy_gh) in retirement_lines[0]
        assert str(legacy_router) in retirement_lines[0]
        ci_path = f"{legacy_dir}:{real_dir}"
        assert shutil.which("gh", path=ci_path) == str(real_dir / "gh")
        e.pop("ONEX_PR_WATCHER")
        body = _run(e, "pr", "view", "7", "--json", "body", "-q", ".body")
        assert body.returncode == 0, body.stderr
        assert _calls(e) == [["pr", "view", "7", "--json", "body", "-q", ".body"]]
    else:
        assert legacy_gh.read_text() == original
        assert legacy_router.read_text() == "legacy router\n"
        assert "retired" not in r.stdout


@pytest.mark.unit
@pytest.mark.parametrize("installed", [False, True])
def test_installer_default_dir_check_reports_legacy_without_changing_files(
    env: dict[str, str], tmp_path: Path, installed: bool
) -> None:
    e = dict(env)
    e["PATH"] = f"{tmp_path / 'realbin'}:/usr/bin:/bin"
    destination = Path(e["HOME"]) / ".local/share/omni/lane-bin"
    if installed:
        assert _install_default(e).returncode == 0
    legacy_dir = Path(e["HOME"]) / ".local/bin"
    legacy_dir.mkdir(parents=True)
    shutil.copy(SHIM, legacy_dir / "gh")
    (legacy_dir / "gh_route.py").write_text("legacy router\n")
    before = {p: p.read_bytes() for p in Path(e["HOME"]).rglob("*") if p.is_file()}
    r = _install_default(e, "--check")
    assert r.returncode == 0, r.stderr
    assert any(
        "CHECK:" in line and "legacy" in line and str(legacy_dir / "gh") in line
        for line in r.stdout.splitlines()
    )
    after = {p: p.read_bytes() for p in Path(e["HOME"]).rglob("*") if p.is_file()}
    assert before == after
    assert destination.exists() == installed


@pytest.mark.unit
def test_installer_default_dir_refuses_foreign_gh(
    env: dict[str, str], tmp_path: Path
) -> None:
    e = dict(env)
    e["PATH"] = f"{tmp_path / 'realbin'}:/usr/bin:/bin"
    destination = Path(e["HOME"]) / ".local/share/omni/lane-bin"
    destination.mkdir(parents=True)
    original = "#!/bin/bash\necho mine\n"
    _write_exec(destination / "gh", original)
    r = _install_default(e)
    assert r.returncode == 3, r.stderr
    assert "REFUSED" in r.stderr
    assert (destination / "gh").read_text() == original
    assert not (destination / "gh_route.py").exists()


@pytest.mark.unit
def test_installer_default_dir_requires_a_real_gh(
    env: dict[str, str], tmp_path: Path
) -> None:
    e = dict(env)
    # Never /usr/bin:/bin: GitHub-hosted Ubuntu runners ship a real gh there.
    tools = _coreutils_dir_without_gh(tmp_path)
    for tool in ("dirname", "tr", "mkdir", "cp", "mv", "rm", "chmod", "cmp", "which"):
        found = shutil.which(tool)
        assert found, f"{tool} not found on PATH; needed by the installer"
        (tools / tool).symlink_to(found)
    e["PATH"] = f"{SHIM.parent}:{tools}"
    # The source shim on PATH must not count as a real gh.
    r = _install_default(e)
    assert r.returncode == 2, r.stderr
    assert "no real gh on PATH" in r.stderr
    assert not (Path(e["HOME"]) / ".local/share/omni/lane-bin").exists()


def _install(
    env: dict[str, str], bin_dir: Path, path: str
) -> subprocess.CompletedProcess[str]:
    e = dict(env)
    e["PATH"] = path
    return subprocess.run(
        ["bash", str(INSTALLER), "--bin-dir", str(bin_dir)],
        env=e,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.unit
def test_installer_refuses_when_bin_dir_is_after_real_gh(
    env: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = tmp_path / "userbin"
    bin_dir.mkdir()
    real = tmp_path / "realbin"
    r = _install(env, bin_dir, f"{real}:{bin_dir}:/usr/bin:/bin")
    assert r.returncode == 2, r.stderr
    assert "REFUSED" in r.stderr
    assert not (bin_dir / "gh").exists()


@pytest.mark.unit
def test_installer_refuses_when_bin_dir_not_on_path(
    env: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = tmp_path / "userbin"
    bin_dir.mkdir()
    r = _install(env, bin_dir, f"{tmp_path / 'realbin'}:/usr/bin:/bin")
    assert r.returncode == 2
    assert not (bin_dir / "gh").exists()


@pytest.mark.unit
def test_installer_installs_ahead_and_the_installed_copy_works(
    env: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = tmp_path / "userbin"
    bin_dir.mkdir()
    path = f"{bin_dir}:{tmp_path / 'realbin'}:/usr/bin:/bin"
    r = _install(env, bin_dir, path)
    assert r.returncode == 0, r.stderr
    assert os.access(bin_dir / "gh", os.X_OK)
    e = dict(env)
    e["PATH"] = path
    for _ in range(2):
        subprocess.run(
            ["gh", "pr", "view", "--json", "url"],
            cwd=env["REPO"],
            env=e,
            capture_output=True,
            check=False,
        )
    assert len(_calls(env)) == 1


@pytest.mark.unit
def test_installer_refuses_to_overwrite_a_foreign_gh(
    env: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = tmp_path / "userbin"
    bin_dir.mkdir()
    _write_exec(bin_dir / "gh", "#!/bin/bash\necho mine\n")
    r = _install(env, bin_dir, f"{bin_dir}:{tmp_path / 'realbin'}:/usr/bin:/bin")
    assert r.returncode in (2, 3)
    assert (bin_dir / "gh").read_text() == "#!/bin/bash\necho mine\n"


# --- AC4: one status-line refresh per stale cache, however many sessions -----


def _render(env: dict[str, str], cache: Path, bin_dir: Path) -> subprocess.Popen[str]:
    e = dict(env)
    e.update(
        {
            "PATH": f"{bin_dir}:{e['PATH']}",
            "ONEX_STATUSLINE_PR_CACHE": str(cache),
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "1",
            "VALKEY_HOST": "127.0.0.1",
            "VALKEY_PORT": "1",
            "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:1",
            "OMNICLAUDE_MODE": "full",
        }
    )
    payload = json.dumps(
        {
            "workspace": {"project_dir": str(REPO_ROOT)},
            "model": {"id": "t", "display_name": "T"},
            "context_window": {},
        }
    )
    p = subprocess.Popen(
        ["bash", str(STATUSLINE)],
        env=e,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert p.stdin is not None
    p.stdin.write(payload)
    p.stdin.close()
    return p


@pytest.mark.unit
def test_lock_two_stale_renders_refresh_once(
    env: dict[str, str], tmp_path: Path
) -> None:
    if shutil.which("jq") is None:
        pytest.skip("statusline needs jq")
    bin_dir = tmp_path / "slbin"
    bin_dir.mkdir()
    refresh_log = tmp_path / "refresh.log"
    _write_exec(
        bin_dir / "gh",
        f'#!/bin/bash\necho "$*" >> "{refresh_log}"\nsleep 0.2\necho \'["dev","main"]\'\n',
    )
    cache = tmp_path / "pr-counts.json"
    cache.write_text(
        '{"schema":2,"refreshed_at":1,"status":"ok","failed":[],"repos":{}}'
    )
    old = time.time() - 3600
    os.utime(cache, (old, old))

    procs = [_render(env, cache, bin_dir) for _ in range(2)]
    for p in procs:
        p.wait(timeout=60)
    lock = Path(f"{cache}.lock")
    deadline = time.time() + 60
    while time.time() < deadline and (
        lock.exists() or time.time() - cache.stat().st_mtime > 600
    ):
        time.sleep(0.25)
    time.sleep(0.5)

    calls = refresh_log.read_text().splitlines() if refresh_log.exists() else []
    list_calls = [c for c in calls if c.startswith("pr list")]
    assert len(list_calls) == 10, calls
    assert json.loads(cache.read_text())["status"] == "ok"
    assert not lock.exists()


@pytest.mark.unit
def test_lock_default_ttl_is_900s() -> None:
    text = STATUSLINE.read_text()
    assert 'PR_TTL="${ONEX_STATUSLINE_PR_TTL:-900}"' in text
    assert "-le 300" not in text


@pytest.mark.unit
def test_passthrough_and_installer_survive_a_long_path(
    env: dict[str, str], tmp_path: Path
) -> None:
    """A long PATH resolves the real gh and installs, split without a here-string.

    Under Homebrew bash 5.3.9 a ``read <<< "$PATH"`` of this host's 1.6 kB PATH hung
    twice at 2026-09-25T14:52Z (load average 72) and did not reproduce later, so
    this is a functional check of the replacement, not a reproduction of the hang.
    """
    filler = ":".join(str(tmp_path / f"missing-dir-{i:03d}") for i in range(60))
    bin_dir = tmp_path / "userbin"
    bin_dir.mkdir()
    long_path = f"{bin_dir}:{SHIM.parent}:{tmp_path / 'realbin'}:{filler}:/usr/bin:/bin"
    assert len(long_path) > 2000
    e = dict(env)
    e["PATH"] = long_path
    # The bash the operator's shell finds (Homebrew 5.3 on this Mac), not the test PATH's /bin/bash.
    host_bash = shutil.which("bash") or "bash"
    r = subprocess.run(
        [host_bash, str(INSTALLER), "--bin-dir", str(bin_dir), "--check"],
        env=e,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    r = subprocess.run(
        ["gh", "pr", "checks", "3"],
        cwd=env["REPO"],
        env=e,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert r.returncode == 0
    assert _calls(env) == [["pr", "checks", "3"]]
