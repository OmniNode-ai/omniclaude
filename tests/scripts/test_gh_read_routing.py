# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-19587 (GitHub quota T0.7): the gh read router.

WHAT THIS PINS. Every local GitHub token is one user bucket, so moving lane
reads onto a read-only App installation token is the only way to take them off
the operator's 5,000 an hour. The router decides, per ``gh`` invocation, which
identity runs it:

  * a READ (the read subcommands, GET REST under ``repos/OmniNode-ai/``, search
    scoped to the organization, a GraphQL document with no mutation and no
    viewer) runs with ``GH_TOKEN`` set to the token the read-token command
    prints;
  * EVERYTHING ELSE runs on the ambient operator credential with argv and env
    untouched, because the merging identity must stay the operator (OMN-19101);
  * a read the App cannot serve falls back to the operator, and the fallback is
    RECORDED with its reason, never hidden.

The test names carry the four words the ticket's falsifiers select with ``-k``:
``read`` (AC1), ``mutation`` (AC2), ``fallback`` (AC3) and ``cache`` (AC4).

The fake ``gh`` below records the argv it saw and the ``GH_TOKEN`` it ran with.
That is the only place a token value is written in this suite, and it is the
point: it is how a test tells which identity ran the call.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "user-bin" / "gh_route.py"
)

APP_TOKEN = "ghs_" + "A" * 36
OPERATOR_TOKEN = "operator-sentinel-not-a-real-token"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gh_route", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gh_route"] = module
    spec.loader.exec_module(module)
    return module


gr = _load()


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


def _write_exe(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_gh(tmp_path: Path) -> Path:
    """A fake real ``gh`` that logs argv and the token it ran with."""
    bindir = tmp_path / "realbin"
    bindir.mkdir()
    return _write_exe(
        bindir / "gh",
        """
        import json, os, sys
        with open(os.environ["FAKE_GH_LOG"], "a") as fh:
            fh.write(json.dumps({"argv": sys.argv[1:],
                                 "gh_token": os.environ.get("GH_TOKEN")}) + "\\n")
        refuse = os.environ.get("FAKE_GH_REFUSE_TOKEN")
        if refuse and os.environ.get("GH_TOKEN") == refuse:
            sys.stderr.write("GraphQL: Resource not accessible by integration\\n")
            sys.exit(1)
        sys.stdout.write("served\\n")
        sys.exit(int(os.environ.get("FAKE_GH_EXIT", "0")))
        """,
    )


@pytest.fixture
def token_cmd(tmp_path: Path) -> Path:
    """A fake read-token command that prints a token and counts its runs."""
    return _write_exe(
        tmp_path / "mint",
        f"""
        import os, sys
        with open(os.environ["FAKE_MINT_COUNT"], "a") as fh:
            fh.write("x")
        code = int(os.environ.get("FAKE_MINT_EXIT", "0"))
        if code:
            sys.exit(code)
        sys.stdout.write(os.environ.get("FAKE_MINT_OUTPUT", "{APP_TOKEN}") + "\\n")
        """,
    )


@pytest.fixture
def env(tmp_path: Path, fake_gh: Path, token_cmd: Path) -> dict[str, str]:
    cache = tmp_path / "cache"
    return {
        "PATH": f"{fake_gh.parent}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(tmp_path),
        "XDG_CACHE_HOME": str(cache),
        "GH_TOKEN": OPERATOR_TOKEN,
        "GH_REPO": "OmniNode-ai/omniclaude",
        gr.FLAG_ENV: "1",
        gr.TOKEN_CMD_ENV: str(token_cmd),
        "FAKE_GH_LOG": str(tmp_path / "gh.log"),
        "FAKE_MINT_COUNT": str(tmp_path / "mint.count"),
    }


@pytest.fixture
def records() -> list[object]:
    return []


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # No git remote in cwd: repository resolution comes from argv or GH_REPO only.
    monkeypatch.chdir(tmp_path)
    return


def _run(
    argv: list[str], fake_gh: Path, env: dict[str, str], records: list[object]
) -> int:
    return int(gr.route_and_run(argv, str(fake_gh), env, records.append))


def _calls(env: dict[str, str]) -> list[dict[str, object]]:
    log = Path(env["FAKE_GH_LOG"])
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _mint_count(env: dict[str, str]) -> int:
    path = Path(env["FAKE_MINT_COUNT"])
    return len(path.read_text()) if path.exists() else 0


# --------------------------------------------------------------------------- #
# AC1 -- reads run on the App token
# --------------------------------------------------------------------------- #

READS: list[list[str]] = [
    ["pr", "view", "12", "--repo", "OmniNode-ai/omniclaude", "--json", "state"],
    ["pr", "checks", "https://github.com/OmniNode-ai/omnibase_infra/pull/4079"],
    ["pr", "list", "-R", "OmniNode-ai/omnimarket", "--state", "open"],
    ["pr", "diff", "12", "--repo=OmniNode-ai/omniclaude", "--name-only"],
    ["pr", "view", "12"],  # repository from GH_REPO
    ["run", "view", "123", "-R", "OmniNode-ai/omniclaude", "--log-failed"],
    ["run", "list", "-R", "OmniNode-ai/omniclaude"],
    ["repo", "view", "OmniNode-ai/omnibase_core", "--json", "name"],
    ["issue", "view", "5", "-R", "OmniNode-ai/omniclaude"],
    ["issue", "list", "-R", "OmniNode-ai/omniclaude"],
    ["api", "repos/OmniNode-ai/omniclaude/pulls/12"],
    ["api", "/repos/OmniNode-ai/omniclaude/commits/abc/check-runs", "--paginate"],
    ["api", "-i", "https://api.github.com/repos/OmniNode-ai/omniclaude/pulls"],
    ["api", "-X", "GET", "repos/OmniNode-ai/omniclaude/pulls", "-f", "state=open"],
    ["api", "--method=GET", "repos/omninode-ai/omniclaude/branches"],
    ["api", "repos/{owner}/{repo}/pulls"],  # placeholders resolved from GH_REPO
    ["api", "search/issues?q=org:OmniNode-ai+is:pr+is:open"],
    ["api", "-X", "GET", "search/issues", "-f", "q=repo:OmniNode-ai/omniclaude is:pr"],
    ["search", "prs", "--owner", "OmniNode-ai", "--state", "open"],
    ["search", "prs", "repo:OmniNode-ai/omniclaude", "is:open"],
    [
        "api",
        "graphql",
        "-f",
        'query={ repository(owner: "OmniNode-ai", name: "omniclaude") '
        "{ pullRequest(number: 1) { state } } }",
    ],
    [
        "api",
        "graphql",
        "-F",
        "owner=OmniNode-ai",
        "-f",
        "query=query($owner: String!) { organization(login: $owner) { id } }",
    ],
]


@pytest.mark.parametrize("argv", READS, ids=[" ".join(a)[:60] for a in READS])
def test_read_runs_on_app_token(
    argv: list[str], fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    assert _run(argv, fake_gh, env, records) == 0
    calls = _calls(env)
    assert calls == [{"argv": argv, "gh_token": APP_TOKEN}]
    (rec,) = records
    assert rec.identity == gr.IDENTITY_APP  # type: ignore[attr-defined]


def test_read_classification_names_repo_and_class() -> None:
    cls = gr.classify(["pr", "view", "1", "-R", "OmniNode-ai/omniclaude"], {})
    assert cls.read and cls.cmd_class == "pr view"
    assert cls.repo == "OmniNode-ai/omniclaude" and cls.method == "GET"


def test_read_graphql_file_query_is_inspected(
    tmp_path: Path, fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    q = tmp_path / "q.graphql"
    q.write_text('query { repository(owner: "OmniNode-ai", name: "x") { id } }')
    argv = ["api", "graphql", "-F", f"query=@{q}"]
    assert _run(argv, fake_gh, env, records) == 0
    assert _calls(env)[0]["gh_token"] == APP_TOKEN


# --------------------------------------------------------------------------- #
# AC2 -- every other call runs on the operator credential, unchanged
# --------------------------------------------------------------------------- #

OPERATOR_CALLS: list[list[str]] = [
    ["pr", "merge", "12", "--squash", "-R", "OmniNode-ai/omniclaude"],
    ["pr", "edit", "12", "--add-label", "x", "-R", "OmniNode-ai/omniclaude"],
    ["pr", "create", "--title", "t", "--body", "b"],
    ["pr", "comment", "12", "--body", "hi", "-R", "OmniNode-ai/omniclaude"],
    ["pr", "ready", "12", "-R", "OmniNode-ai/omniclaude"],
    ["pr", "status"],
    ["issue", "edit", "5", "--add-label", "bug", "-R", "OmniNode-ai/omniclaude"],
    ["label", "create", "x", "-R", "OmniNode-ai/omniclaude"],
    ["run", "rerun", "123", "-R", "OmniNode-ai/omniclaude"],
    ["workflow", "run", "ci.yml", "-R", "OmniNode-ai/omniclaude"],
    ["api", "-X", "POST", "repos/OmniNode-ai/omniclaude/issues/1/comments"],
    ["api", "--method", "PATCH", "repos/OmniNode-ai/omniclaude/pulls/1"],
    ["api", "-XPUT", "repos/OmniNode-ai/omniclaude/pulls/1/merge"],
    ["api", "repos/OmniNode-ai/omniclaude/issues/1/labels", "-f", "labels[]=x"],
    ["api", "repos/OmniNode-ai/omniclaude/pulls", "--input", "body.json"],
    ["api", "-X", "DELETE", "repos/OmniNode-ai/omniclaude/git/refs/heads/x"],
    [
        "api",
        "graphql",
        "-f",
        "query=mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }",
    ],
    ["api", "graphql", "-f", "query={ viewer { login } }"],
    ["api", "graphql", "-F", "query=@-"],
    ["api", "user"],
    ["api", "rate_limit"],
    ["api", "orgs/OmniNode-ai/installations"],
    ["api", "repos/SomeoneElse/tool/pulls"],
    ["api", "--hostname", "ghe.example.com", "repos/OmniNode-ai/x/pulls"],
    ["api", "search/issues?q=is:pr+author:someone"],
    ["search", "prs", "--author", "@me"],
    ["search", "prs", "is:open", "label:bug"],
    ["pr", "list", "--author", "@me", "-R", "OmniNode-ai/omniclaude"],
    ["pr", "view", "1", "-R", "SomeoneElse/tool"],
    ["auth", "status"],
    ["auth", "token"],
    ["--version"],
    [],
]


@pytest.mark.parametrize(
    "argv", OPERATOR_CALLS, ids=[" ".join(a)[:60] or "<empty>" for a in OPERATOR_CALLS]
)
def test_mutation_and_non_read_run_on_operator_unchanged(
    argv: list[str], fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    assert _run(argv, fake_gh, env, records) == 0
    assert _calls(env) == [{"argv": argv, "gh_token": OPERATOR_TOKEN}]
    (rec,) = records
    assert rec.identity == gr.IDENTITY_OPERATOR  # type: ignore[attr-defined]
    # A non-read never mints: the App is not touched for an operator call.
    assert _mint_count(env) == 0


def test_mutation_exit_code_and_ambient_env_pass_through(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    env = {**env, "FAKE_GH_EXIT": "7"}
    argv = ["pr", "merge", "1", "-R", "OmniNode-ai/omniclaude"]
    assert _run(argv, fake_gh, env, records) == 7
    assert records[0].exit_code == 7  # type: ignore[attr-defined]


def test_mutation_when_operator_has_no_gh_token_env_stays_unset(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    env = {k: v for k, v in env.items() if k != "GH_TOKEN"}
    assert _run(["pr", "merge", "1"], fake_gh, env, records) == 0
    assert _calls(env)[0]["gh_token"] is None


# --------------------------------------------------------------------------- #
# AC3 -- fallbacks run on the operator and are recorded with their reason
# --------------------------------------------------------------------------- #

READ_ARGV = ["pr", "view", "1", "-R", "OmniNode-ai/omniclaude"]


def _assert_fallback(
    env: dict[str, str], records: list[object], reason_prefix: str
) -> None:
    assert _calls(env)[-1]["gh_token"] == OPERATOR_TOKEN
    rec = records[-1]
    assert rec.identity == gr.IDENTITY_FALLBACK  # type: ignore[attr-defined]
    assert rec.reason.startswith(reason_prefix), rec.reason  # type: ignore[attr-defined]


def test_fallback_when_token_cmd_unset(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    env.pop(gr.TOKEN_CMD_ENV)
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    _assert_fallback(env, records, "token-cmd-unset")


def test_fallback_when_token_cmd_fails(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    env["FAKE_MINT_EXIT"] = "3"
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    _assert_fallback(env, records, "token-cmd-exit-3")


def test_fallback_when_token_cmd_missing(
    tmp_path: Path, fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    env[gr.TOKEN_CMD_ENV] = str(tmp_path / "no-such-mint")
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    _assert_fallback(env, records, "token-cmd-not-found")


def test_fallback_when_token_cmd_prints_a_user_token(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    # A personal token would put "reads" back on a user bucket without a trace.
    env["FAKE_MINT_OUTPUT"] = "ghp_" + "B" * 36
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    _assert_fallback(env, records, "token-not-installation-token")


def test_fallback_when_token_cmd_times_out(
    tmp_path: Path,
    fake_gh: Path,
    env: dict[str, str],
    records: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow = _write_exe(tmp_path / "slow-mint", "import time\ntime.sleep(5)\n")
    env[gr.TOKEN_CMD_ENV] = str(slow)
    monkeypatch.setattr(gr, "TOKEN_CMD_TIMEOUT_S", 0.3)
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    _assert_fallback(env, records, "token-cmd-timeout")


def test_fallback_when_no_cache_home_at_all(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    env.pop("XDG_CACHE_HOME")
    env.pop("HOME")
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    _assert_fallback(env, records, "cache-home-unresolvable")
    assert _mint_count(env) == 0


def test_cache_uses_home_dot_cache_when_xdg_unset(
    tmp_path: Path, fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    # The XDG base-directory default, the same tree the T0.5 shim logs under.
    env.pop("XDG_CACHE_HOME")
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    assert _calls(env)[0]["gh_token"] == APP_TOKEN
    cached = tmp_path / ".cache" / gr.CACHE_SUBDIR / gr.TOKEN_CACHE_NAME
    assert stat.S_IMODE(cached.stat().st_mode) == 0o600


def test_fallback_when_app_refuses_retries_once_on_operator(
    fake_gh: Path,
    env: dict[str, str],
    records: list[object],
    capfd: pytest.CaptureFixture[str],
) -> None:
    env["FAKE_GH_REFUSE_TOKEN"] = APP_TOKEN
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    calls = _calls(env)
    assert [c["gh_token"] for c in calls] == [APP_TOKEN, OPERATOR_TOKEN]
    assert all(c["argv"] == READ_ARGV for c in calls)
    _assert_fallback(env, records, "integration-refused")
    out, err = capfd.readouterr()
    assert out == "served\n"
    # The refused attempt's stderr is not replayed to the caller.
    assert "not accessible by integration" not in err
    assert len(records) == 1


def test_fallback_not_taken_for_an_ordinary_read_failure(
    fake_gh: Path,
    env: dict[str, str],
    records: list[object],
) -> None:
    env["FAKE_GH_EXIT"] = "1"
    assert _run(READ_ARGV, fake_gh, env, records) == 1
    assert len(_calls(env)) == 1
    assert records[0].identity == gr.IDENTITY_APP  # type: ignore[attr-defined]


def test_fallback_routing_disabled_is_a_pure_pass_through(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    env[gr.FLAG_ENV] = "0"
    assert _run(READ_ARGV, fake_gh, env, records) == 0
    assert _calls(env) == [{"argv": READ_ARGV, "gh_token": OPERATOR_TOKEN}]
    assert _mint_count(env) == 0
    assert records[0].reason == "routing-disabled"  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# AC4 -- the token cache: 0600, at most 50 minutes, never in the usage log
# --------------------------------------------------------------------------- #


def _cache_file(env: dict[str, str]) -> Path:
    return Path(env["XDG_CACHE_HOME"]) / gr.CACHE_SUBDIR / gr.TOKEN_CACHE_NAME


def test_cache_file_is_mode_0600_and_reused(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    _run(READ_ARGV, fake_gh, env, records)
    _run(READ_ARGV, fake_gh, env, records)
    assert _mint_count(env) == 1
    mode = stat.S_IMODE(_cache_file(env).stat().st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(_cache_file(env).parent.stat().st_mode) & 0o077 == 0
    assert [c["gh_token"] for c in _calls(env)] == [APP_TOKEN, APP_TOKEN]


def test_cache_expires_after_fifty_minutes(
    fake_gh: Path,
    env: dict[str, str],
    records: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr(gr, "_now", lambda: clock[0])
    _run(READ_ARGV, fake_gh, env, records)
    clock[0] += 49 * 60
    _run(READ_ARGV, fake_gh, env, records)
    assert _mint_count(env) == 1
    clock[0] += 60 + 1  # 50 min + 1 s after the mint
    _run(READ_ARGV, fake_gh, env, records)
    assert _mint_count(env) == 2


def test_cache_with_loose_mode_is_discarded_and_reminted(
    fake_gh: Path, env: dict[str, str], records: list[object]
) -> None:
    _run(READ_ARGV, fake_gh, env, records)
    _cache_file(env).chmod(0o644)
    _run(READ_ARGV, fake_gh, env, records)
    assert _mint_count(env) == 2
    assert stat.S_IMODE(_cache_file(env).stat().st_mode) == 0o600


def test_cache_token_never_in_records_or_usage_log(
    tmp_path: Path, fake_gh: Path, env: dict[str, str]
) -> None:
    log = tmp_path / "usage.jsonl"
    recorder = gr.jsonl_recorder(log, env)
    gr.route_and_run(READ_ARGV, str(fake_gh), env, recorder)
    env["FAKE_MINT_EXIT"] = "4"
    _cache_file(env).unlink()
    gr.route_and_run(READ_ARGV, str(fake_gh), env, recorder)
    text = log.read_text()
    assert APP_TOKEN not in text and OPERATOR_TOKEN not in text
    lines = [json.loads(line) for line in text.splitlines()]
    assert [ln["identity"] for ln in lines] == [
        gr.IDENTITY_APP,
        gr.IDENTITY_FALLBACK,
    ]
    for ln in lines:
        assert set(ln) >= {"ts", "lane", "cmd_class", "method", "repo", "exit_code"}


def test_cache_exec_entrypoint_end_to_end(
    tmp_path: Path, fake_gh: Path, env: dict[str, str]
) -> None:
    """The CLI entry the shim calls: resolves the real gh past itself, logs one line."""
    shim_dir = _MODULE_PATH.parent
    run_env = {**env, "PATH": f"{shim_dir}{os.pathsep}{env['PATH']}"}
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "exec", "--", *READ_ARGV],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "served\n"
    log = Path(env["XDG_CACHE_HOME"]) / gr.CACHE_SUBDIR / gr.USAGE_LOG_NAME
    (line,) = [json.loads(x) for x in log.read_text().splitlines()]
    assert line["identity"] == gr.IDENTITY_APP
    assert APP_TOKEN not in log.read_text()


def test_cache_exec_result_file_for_the_bash_shim(
    tmp_path: Path, fake_gh: Path, env: dict[str, str]
) -> None:
    """With --result-file the router writes only identity and reason, for the shim's line."""
    result = tmp_path / "route.result"
    env["FAKE_MINT_EXIT"] = "5"
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "exec", "--result-file", str(result), "--"]
        + READ_ARGV,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert result.read_text() == f"{gr.IDENTITY_FALLBACK} token-cmd-exit-5\n"
    assert stat.S_IMODE(result.stat().st_mode) == 0o600
    assert not (
        Path(env["XDG_CACHE_HOME"]) / gr.CACHE_SUBDIR / gr.USAGE_LOG_NAME
    ).exists()


def test_mutation_real_gh_resolution_skips_an_installed_shim_copy(
    tmp_path: Path, fake_gh: Path
) -> None:
    installed = tmp_path / "localbin"
    installed.mkdir()
    _write_exe(installed / "gh", "# ONEX_GH_USER_SHIM\nraise SystemExit(9)\n")
    path_env = f"{installed}{os.pathsep}{fake_gh.parent}"
    assert gr.resolve_real_gh(path_env, _MODULE_PATH.parent) == str(fake_gh)
