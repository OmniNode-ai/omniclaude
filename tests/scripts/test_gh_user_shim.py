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
    _run(env, "pr", verb)
    after = _run(
        env, "pr", "view", "--json", "url", extra={"FAKE_GH_STDOUT": '{"url":"new"}'}
    )
    assert after.stdout == '{"url":"new"}'
    assert len(_calls(env)) == 3


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


@pytest.mark.unit
def test_passthrough_no_real_gh_is_a_loud_127(env: dict[str, str]) -> None:
    e = dict(env)
    e["PATH"] = f"{SHIM.parent}:/usr/bin:/bin"
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
    assert len(list_calls) == 11, calls
    assert json.loads(cache.read_text())["status"] == "ok"
    assert not lock.exists()


@pytest.mark.unit
def test_lock_default_ttl_is_900s() -> None:
    text = STATUSLINE.read_text()
    assert 'PR_TTL="${ONEX_STATUSLINE_PR_TTL:-900}"' in text
    assert "-le 300" not in text
