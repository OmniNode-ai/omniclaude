# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""End-to-end tests for OMN-19587's bash shim/read-router integration.

All executables are local fixtures. No test invokes GitHub or uses a real token.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "scripts" / "user-bin"
SHIM = SHIM_DIR / "gh"
INSTALLER = SHIM_DIR / "install-gh-shim.sh"
REPORT = SHIM_DIR / "gh_usage_report.py"
APP_TOKEN = "ghs_" + "A" * 36
OPERATOR_TOKEN = "operator-" + "sentinel-not-a-real-token"


def _write_exe(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return path


@pytest.fixture
def routed_env(tmp_path: Path) -> dict[str, str]:
    real_dir = tmp_path / "realbin"
    real_dir.mkdir()
    _write_exe(
        real_dir / "gh",
        """
        import json, os, sys
        record = {"argv": sys.argv[1:], "gh_token": os.environ.get("GH_TOKEN")}
        if os.environ.get("FAKE_GH_RECORD_ENV"):
            # The whole environment the real gh ran with, minus what a shell
            # in between rewrites on its own.
            volatile = {"_", "SHLVL", "PWD", "OLDPWD", "__CF_USER_TEXT_ENCODING"}
            record["env"] = {
                k: v for k, v in os.environ.items() if k not in volatile
            }
        with open(os.environ["FAKE_GH_LOG"], "a") as fh:
            fh.write(json.dumps(record) + "\\n")
        sys.stdout.write(os.environ.get("FAKE_GH_STDOUT", "served\\n"))
        sys.stderr.write(os.environ.get("FAKE_GH_STDERR", ""))
        raise SystemExit(int(os.environ.get("FAKE_GH_RC", "0")))
        """,
    )
    mint = _write_exe(
        tmp_path / "mint",
        f"""
        import os, sys
        count = os.environ.get("FAKE_MINT_LOG")
        if count:
            with open(count, "a") as fh:
                fh.write("mint\\n")
        raise_code = int(os.environ.get("FAKE_MINT_RC", "0"))
        if raise_code:
            raise SystemExit(raise_code)
        sys.stdout.write({APP_TOKEN!r} + "\\n")
        """,
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "PATH": f"{SHIM_DIR}{os.pathsep}{real_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "GH_TOKEN": OPERATOR_TOKEN,
        "GH_REPO": "OmniNode-ai/omniclaude",
        "GH_READ_TOKEN_CMD": str(mint),
        "ONEX_GH_ROUTE_PYTHON": sys.executable,
        "FAKE_GH_LOG": str(tmp_path / "gh.jsonl"),
        "FAKE_MINT_LOG": str(tmp_path / "mint.log"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "REPO": str(repo),
        "REAL_GH": str(real_dir / "gh"),
    }
    subprocess.run(
        ["git", "init", "-q", "-b", "main"],
        cwd=repo,
        env=scrub_git_location_env(env),
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:OmniNode-ai/omniclaude.git"],
        cwd=repo,
        env=scrub_git_location_env(env),
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        cwd=repo,
        env=scrub_git_location_env(env),
        check=True,
    )
    return env


def _run(
    env: dict[str, str],
    *argv: str,
    extra: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    call_env = dict(env)
    call_env.update(extra or {})
    return subprocess.run(
        ["gh", *argv],
        cwd=cwd or Path(env["REPO"]),
        env=call_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _gh_calls(env: dict[str, str]) -> list[dict[str, object]]:
    path = Path(env["FAKE_GH_LOG"])
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _usage(env: dict[str, str]) -> list[dict[str, object]]:
    directory = Path(env["XDG_CACHE_HOME"]) / "omni" / "gh-usage"
    return [
        json.loads(line)
        for path in sorted(directory.glob("*.jsonl"))
        for line in path.read_text().splitlines()
    ]


def _clear_calls(env: dict[str, str]) -> None:
    Path(env["FAKE_GH_LOG"]).unlink(missing_ok=True)


def _spy_router(path: Path, log: Path, *, exit_without_result: bool = False) -> Path:
    if exit_without_result:
        body = f"""
        from pathlib import Path
        Path({str(log)!r}).write_text("invoked")
        raise SystemExit(1)
        """
    else:
        body = f"""
        import os, sys
        from pathlib import Path
        Path({str(log)!r}).write_text(os.environ.get("ONEX_LANE", ""))
        result = Path(sys.argv[sys.argv.index("--result-file") + 1])
        result.write_text("operator spy\\n")
        """
    return _write_exe(path, body)


@pytest.mark.parametrize("flag", [None, "0"], ids=["unset", "zero"])
def test_route_off_is_byte_identical_for_all_commands(
    routed_env: dict[str, str], tmp_path: Path, flag: str | None
) -> None:
    spy_log = tmp_path / "router-spy"
    spy = _spy_router(tmp_path / "spy-router", spy_log)
    cases = [
        ["pr", "view", "--json", "url"],
        ["api", "repos/OmniNode-ai/omniclaude/pulls"],
        ["pr", "merge", "1", "--squash"],
        ["api", "-X", "POST", "repos/OmniNode-ai/omniclaude/issues"],
    ]
    for index, argv in enumerate(cases):
        extra = {
            "ONEX_GH_ROUTER": str(spy),
            "FAKE_GH_STDOUT": f"out-{index}\\n",
            "FAKE_GH_STDERR": f"err-{index}\\n",
            "FAKE_GH_RC": str(index + 3),
            "FAKE_GH_RECORD_ENV": "1",
        }
        if flag is not None:
            extra["ONEX_GH_READ_ROUTING"] = flag
        direct_env = {**routed_env, **extra}
        if flag is None:
            direct_env.pop("ONEX_GH_READ_ROUTING", None)
        direct = subprocess.run(
            [routed_env["REAL_GH"], *argv],
            cwd=routed_env["REPO"],
            env=direct_env,
            capture_output=True,
            text=True,
            check=False,
        )
        via_shim = _run(routed_env, *argv, extra=direct_env)
        assert (via_shim.returncode, via_shim.stdout, via_shim.stderr) == (
            direct.returncode,
            direct.stdout,
            direct.stderr,
        )
        direct_call, shim_call = _gh_calls(routed_env)[-2:]
        # argv, GH_TOKEN and the whole environment the real gh saw.
        assert "env" in shim_call
        assert shim_call == direct_call
    assert not spy_log.exists()
    assert all("identity" not in row for row in _usage(routed_env))


@pytest.mark.parametrize(
    "argv",
    [
        ["api", "repos/OmniNode-ai/omniclaude/pulls"],
        ["pr", "view", "1", "-R", "OmniNode-ai/omniclaude"],
        ["pr", "list"],
        ["pr", "checks", "1"],
        ["run", "view", "12"],
        ["run", "list"],
    ],
)
def test_route_read_uses_app_token_for_candidates(
    routed_env: dict[str, str], argv: list[str]
) -> None:
    result = _run(routed_env, *argv, extra={"ONEX_GH_READ_ROUTING": "1"})
    assert result.returncode == 0, result.stderr
    assert _gh_calls(routed_env) == [{"argv": argv, "gh_token": APP_TOKEN}]
    assert _usage(routed_env)[0]["identity"] == "app"


def test_route_fallback_when_token_command_is_unset(routed_env: dict[str, str]) -> None:
    env = dict(routed_env)
    env.pop("GH_READ_TOKEN_CMD")
    result = _run(env, "pr", "list", extra={"ONEX_GH_READ_ROUTING": "1"})
    assert result.returncode == 0
    assert _gh_calls(env)[0]["gh_token"] == OPERATOR_TOKEN
    assert (_usage(env)[0]["identity"], _usage(env)[0]["route_reason"]) == (
        "operator-fallback",
        "token-cmd-unset",
    )


def test_route_fallback_when_mint_fails(routed_env: dict[str, str]) -> None:
    result = _run(
        routed_env,
        "pr",
        "list",
        extra={"ONEX_GH_READ_ROUTING": "1", "FAKE_MINT_RC": "1"},
    )
    assert result.returncode == 0
    assert _gh_calls(routed_env)[0]["gh_token"] == OPERATOR_TOKEN
    assert _usage(routed_env)[0]["identity"] == "operator-fallback"
    assert _usage(routed_env)[0]["route_reason"] == "token-cmd-exit-1"


def test_route_fallback_when_router_is_unavailable(routed_env: dict[str, str]) -> None:
    result = _run(
        routed_env,
        "pr",
        "list",
        extra={
            "ONEX_GH_READ_ROUTING": "1",
            "ONEX_GH_ROUTER": "/nonexistent/gh_route.py",
            "FAKE_GH_STDOUT": "operator output",
            "FAKE_GH_RC": "6",
        },
    )
    assert (result.returncode, result.stdout) == (6, "operator output")
    assert _gh_calls(routed_env)[0]["gh_token"] == OPERATOR_TOKEN
    row = _usage(routed_env)[0]
    assert (row["identity"], row["route_reason"]) == (
        "operator-fallback",
        "router-unavailable",
    )


def test_route_fallback_when_router_dies_before_recording(
    routed_env: dict[str, str], tmp_path: Path
) -> None:
    spy_log = tmp_path / "spy-log"
    spy = _spy_router(tmp_path / "dying-router", spy_log, exit_without_result=True)
    result = _run(
        routed_env,
        "pr",
        "list",
        extra={"ONEX_GH_READ_ROUTING": "1", "ONEX_GH_ROUTER": str(spy)},
    )
    assert result.returncode == 0 and spy_log.exists()
    assert _gh_calls(routed_env) == [
        {"argv": ["pr", "list"], "gh_token": OPERATOR_TOKEN}
    ]
    assert _usage(routed_env)[0]["route_reason"] == "router-failed"


@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "merge", "1"],
        ["pr", "create", "--title", "x"],
        ["pr", "comment", "1", "--body", "x"],
        ["pr", "edit", "1", "--title", "x"],
        ["api", "-X", "POST", "repos/OmniNode-ai/omniclaude/issues"],
        ["api", "-X", "PATCH", "repos/OmniNode-ai/omniclaude/pulls/1"],
        ["api", "repos/OmniNode-ai/omniclaude/issues", "-f", "title=x"],
        ["api", "graphql", "-f", "query=mutation { x }"],
        ["issue", "close", "1"],
    ],
)
def test_route_writes_never_routed_to_spy(
    routed_env: dict[str, str], tmp_path: Path, argv: list[str]
) -> None:
    spy_log = tmp_path / "write-spy"
    spy = _spy_router(tmp_path / "write-router", spy_log)
    result = _run(
        routed_env,
        *argv,
        extra={"ONEX_GH_READ_ROUTING": "1", "ONEX_GH_ROUTER": str(spy)},
    )
    assert result.returncode == 0
    assert _gh_calls(routed_env)[0]["gh_token"] == OPERATOR_TOKEN
    assert not spy_log.exists()
    row = _usage(routed_env)[0]
    assert (row["identity"], row["route_reason"]) == (
        "operator",
        "shim-not-a-read",
    )


def test_route_cache_miss_goes_through_router(routed_env: dict[str, str]) -> None:
    extra = {"ONEX_GH_READ_ROUTING": "1"}
    first = _run(routed_env, "pr", "view", "--json", "url", extra=extra)
    second = _run(routed_env, "pr", "view", "--json", "url", extra=extra)
    assert first.stdout == second.stdout == "served\n"
    assert _gh_calls(routed_env) == [
        {"argv": ["pr", "view", "--json", "url"], "gh_token": APP_TOKEN}
    ]
    first_log, second_log = _usage(routed_env)
    assert (first_log["cache"], first_log["identity"]) == ("miss", "app")
    assert second_log["cache"] == "hit" and "identity" not in second_log


def test_lane_env_and_agent_env_precedence(routed_env: dict[str, str]) -> None:
    _run(
        routed_env,
        "pr",
        "list",
        extra={"ONEX_LANE": "lane-env", "ONEX_AGENT_NAME": "ignored"},
    )
    _run(routed_env, "pr", "list", extra={"ONEX_AGENT_NAME": "lane-agent"})
    first, second = _usage(routed_env)
    assert (first["lane"], first["lane_source"]) == ("lane-env", "env")
    assert (second["lane"], second["lane_source"]) == (
        "lane-agent",
        "agent-env",
    )


def test_lane_registry_root_and_subdirectory_then_session_fallback(
    routed_env: dict[str, str], tmp_path: Path
) -> None:
    worktree = tmp_path / "omni_worktrees" / "OMN-1" / "repo"
    subdir = worktree / "a" / "b"
    subdir.mkdir(parents=True)
    key = hashlib.sha256(str(worktree.resolve()).encode()).hexdigest()[:32]
    registry = tmp_path / ".onex_state" / "lane_identity"
    registry.mkdir(parents=True)
    (registry / f"{key}.json").write_text('{"lane": "lane-x"}\n')
    extra = {"OMNI_HOME": str(tmp_path), "CLAUDE_CODE_SESSION_ID": "sess-1"}
    _run(routed_env, "pr", "list", extra=extra, cwd=worktree)
    _run(routed_env, "pr", "list", extra=extra, cwd=subdir)
    (registry / f"{key}.json").unlink()
    _run(routed_env, "pr", "list", extra=extra, cwd=subdir)
    rows = _usage(routed_env)
    assert [(row["lane"], row["lane_source"]) for row in rows] == [
        ("lane-x", "registry"),
        ("lane-x", "registry"),
        ("session:sess-1", "session"),
    ]


def test_lane_registry_value_is_passed_to_router(
    routed_env: dict[str, str], tmp_path: Path
) -> None:
    worktree = tmp_path / "omni_worktrees" / "OMN-1" / "repo"
    worktree.mkdir(parents=True)
    key = hashlib.sha256(str(worktree.resolve()).encode()).hexdigest()[:32]
    registry = tmp_path / ".onex_state" / "lane_identity"
    registry.mkdir(parents=True)
    (registry / f"{key}.json").write_text('{"lane": "lane-router"}\n')
    spy_log = tmp_path / "router-lane"
    spy = _spy_router(tmp_path / "lane-router-spy", spy_log)
    result = _run(
        routed_env,
        "pr",
        "list",
        extra={
            "OMNI_HOME": str(tmp_path),
            "ONEX_GH_READ_ROUTING": "1",
            "ONEX_GH_ROUTER": str(spy),
        },
        cwd=worktree,
    )
    assert result.returncode == 0
    assert spy_log.read_text() == "lane-router"
    row = _usage(routed_env)[0]
    assert (row["lane"], row["lane_source"], row["route_reason"]) == (
        "lane-router",
        "registry",
        "spy",
    )


def test_route_read_with_usage_log_off_still_routes(
    routed_env: dict[str, str],
) -> None:
    result = _run(
        routed_env,
        "pr",
        "checks",
        "1",
        extra={"ONEX_GH_READ_ROUTING": "1", "ONEX_GH_USAGE_LOG": "0"},
    )
    assert result.returncode == 0, result.stderr
    assert _gh_calls(routed_env)[0]["gh_token"] == APP_TOKEN
    assert not (Path(routed_env["XDG_CACHE_HOME"]) / "omni" / "gh-usage").exists()


def test_route_read_finds_python_on_path_without_override(
    routed_env: dict[str, str], tmp_path: Path
) -> None:
    pybin = tmp_path / "pybin"
    pybin.mkdir()
    (pybin / "python3").symlink_to(sys.executable)
    env = dict(routed_env)
    env.pop("ONEX_GH_ROUTE_PYTHON")
    # The fixture PATH holds no python3.13, so the shim falls back to the
    # first python3 on PATH, which is this one.
    env["PATH"] = f"{pybin}{os.pathsep}{env['PATH']}"
    result = _run(env, "run", "list", extra={"ONEX_GH_READ_ROUTING": "1"})
    assert result.returncode == 0, result.stderr
    assert _gh_calls(env)[0]["gh_token"] == APP_TOKEN
    assert _usage(env)[0]["identity"] == "app"


def test_route_secret_never_logged(routed_env: dict[str, str]) -> None:
    _run(
        routed_env,
        "pr",
        "list",
        extra={"ONEX_GH_READ_ROUTING": "1"},
    )
    raw = "".join(
        path.read_text()
        for path in (Path(routed_env["XDG_CACHE_HOME"]) / "omni" / "gh-usage").glob(
            "*.jsonl"
        )
    )
    assert APP_TOKEN not in raw
    assert OPERATOR_TOKEN not in raw


def test_install_copies_router_and_installed_shim_routes_reads(
    routed_env: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = tmp_path / "installed-bin"
    bin_dir.mkdir()
    install_env = dict(routed_env)
    install_env["PATH"] = (
        f"{bin_dir}{os.pathsep}{Path(routed_env['REAL_GH']).parent}"
        f"{os.pathsep}/usr/bin{os.pathsep}/bin"
    )
    installed = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--bin-dir", str(bin_dir)],
        env=install_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    assert (bin_dir / "gh").is_file()
    assert (bin_dir / "gh_route.py").read_bytes() == (
        SHIM_DIR / "gh_route.py"
    ).read_bytes()
    assert stat.S_IMODE((bin_dir / "gh_route.py").stat().st_mode) == 0o755
    checked = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--bin-dir", str(bin_dir), "--check"],
        env=install_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0
    assert "present and identical" in checked.stdout
    _clear_calls(routed_env)
    result = _run(
        {**routed_env, "PATH": install_env["PATH"]},
        "pr",
        "list",
        extra={"ONEX_GH_READ_ROUTING": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert _gh_calls(routed_env)[0]["gh_token"] == APP_TOKEN


def _load_report() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gh_usage_report_omn19587", REPORT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_agent_registry_attribution_and_app_calls(tmp_path: Path) -> None:
    report = _load_report()
    since = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
    until = since + timedelta(hours=1)
    records = [
        {
            "_ts": since,
            "lane": "agent-a",
            "lane_source": "agent-env",
            "cls": "pr checks",
            "method": "GET",
            "cache": "none",
            "identity": "app",
        },
        {
            "_ts": since,
            "lane": "lane-r",
            "lane_source": "registry",
            "cls": "api",
            "method": "GET",
            "cache": "none",
            "identity": "operator",
        },
    ]
    rep = report.build_report(records, since, until, None)
    by_lane = {row["lane"]: row for row in rep["lanes"]}
    assert report.core_cost(records[0]) == 0
    assert by_lane["agent-a"]["app_calls"] == 1
    assert by_lane["agent-a"]["core_requests_est"] == 0
    assert by_lane["lane-r"]["app_calls"] == 0
    assert rep["unattributed_calls"] == 0
    text = report.render_text(rep)
    assert "app_calls" in text and "agent-a" in text
