#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Route read-only ``gh`` calls onto a read-only GitHub App token (OMN-19587, T0.7).

WHY. Every local GitHub credential on this host (the gh CLI, both PAT variables,
the hosted GitHub MCP) is the operator's user and spends one bucket of 5,000
requests an hour. On 2026-09-25 that bucket ran at up to about 7,300 an hour.
An App installation token has its own bucket, so moving READS onto it is the
only local change that takes load off the operator. Writes stay on the
operator: the merging identity must remain the operator (OMN-19101).

WHAT IS A READ. Decided from argv alone, conservatively; anything not provably
a read of an ``OmniNode-ai`` repository runs on the operator unchanged:

  * the read subcommands ``pr view|checks|list|diff``, ``run view|list``,
    ``repo view`` and ``issue view|list``, aimed at an ``OmniNode-ai``
    repository (``-R``/``--repo``, a github.com URL argument, ``GH_REPO``, or
    the current directory's git remotes);
  * ``gh search`` scoped to the organization (``--owner OmniNode-ai``,
    ``org:``/``repo:``/``user:`` qualifiers);
  * ``gh api`` with an effective method of GET under ``repos/OmniNode-ai/``, or
    under ``search/`` with an organization-scoped ``q``;
  * ``gh api graphql`` whose document has no ``mutation``, no ``viewer``, and
    names no owner other than ``OmniNode-ai``.

  Anything that resolves the viewer (``@me``, ``viewer``, ``pr status``) stays
  on the operator, because on an installation token it would answer as the bot
  or not at all. Unscoped search stays on the operator because the App sees
  fewer repositories and would return fewer results WITHOUT an error.

HOW. A read runs with ``GH_TOKEN`` set to the token printed by the command in
``GH_READ_TOKEN_CMD`` (the T0.8 mint, OMN-19588). The token must be an
installation token (``ghs_``); anything else is refused, because a user token
there would put "reads" back on a user bucket without a trace. It is cached
mode 0600 under ``${XDG_CACHE_HOME:-$HOME/.cache}/omni/`` (the XDG base-directory
default, the same tree the shim logs under) for at most 50 minutes (installation
tokens live 60), minted under an ``fcntl`` lock so a burst of calls mints once.
It is never logged, never put in argv, never printed.

FALLBACK IS RECORDED, NEVER SILENT. If routing is on but the token cannot be
had (command unset, missing, failing, timing out, printing the wrong kind of
token, no cache home), the read runs on the operator and the recorder receives
``identity=operator-fallback`` with the reason. If the App answers "Resource
not accessible by integration", the call is retried once on the operator and
recorded the same way. The recorder is the usage log of T0.5 (OMN-19585).

OFF BY DEFAULT. Nothing routes unless ``ONEX_GH_READ_ROUTING=1``. The flag is
turned on only after the operator has created the App and the post-setup
readback has passed (runbook: knowledge-base-internal
``runbooks/github-app-pr-reader-setup.md``).

STDLIB ONLY. It runs on every gh call, on the canonical interpreter and outside any
venv, so its records are NamedTuples rather than Pydantic models and it imports
nothing outside the standard library.

ENTRY POINTS. ``route_and_run(argv, real_gh, env, recorder)`` for the shim to
import; ``gh_route.py exec -- <gh argv>`` for a shell shim to exec (it resolves
the real gh on PATH past this directory and logs to
``<cache>/omni/gh-route.jsonl``, or, with ``--result-file PATH``, writes only
``identity reason`` to PATH for the bash shim to add to its own usage line);
``gh_route.py classify -- <gh argv>``
prints the routing decision as JSON, for debugging, without running anything.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

ORG = "OmniNode-ai"
FLAG_ENV = "ONEX_GH_READ_ROUTING"
TOKEN_CMD_ENV = "GH_READ_TOKEN_CMD"  # noqa: S105 -- an env var name, not a secret
CACHE_SUBDIR = "omni"
TOKEN_CACHE_NAME = "gh-read-token.json"  # noqa: S105 -- a file name, not a secret
USAGE_LOG_NAME = "gh-route.jsonl"
SHIM_MARKER = b"ONEX_GH_USER_SHIM"
TOKEN_MAX_AGE_S = 50 * 60
TOKEN_CMD_TIMEOUT_S: float = 30.0
INTEGRATION_REFUSAL = "Resource not accessible by integration"

IDENTITY_APP = "app"
IDENTITY_OPERATOR = "operator"
IDENTITY_FALLBACK = "operator-fallback"

_INSTALLATION_TOKEN = re.compile(r"ghs_[A-Za-z0-9_]{20,255}")
_GITHUB_URL = re.compile(r"^https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+)")
_OWNER_REPO = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+)$")
_SEARCH_SCOPE = re.compile(r"\b(?:org|user|repo):([A-Za-z0-9-]+)", re.IGNORECASE)
_GQL_OWNER_LITERAL = re.compile(r"\b(?:owner|login)\s*:\s*\"([^\"]*)\"", re.IGNORECASE)
_GQL_OWNER_VARS = {"owner", "org", "login", "organization"}

READ_SUBCOMMANDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("pr", "view"),
        ("pr", "checks"),
        ("pr", "list"),
        ("pr", "diff"),
        ("run", "view"),
        ("run", "list"),
        ("repo", "view"),
        ("issue", "view"),
        ("issue", "list"),
    }
)
SEARCH_KINDS: frozenset[str] = frozenset({"prs", "issues", "repos", "commits", "code"})

# gh api flags that take a value (so the value is not the endpoint).
_API_VALUE_FLAGS: frozenset[str] = frozenset(
    {
        "-X",
        "--method",
        "-f",
        "--raw-field",
        "-F",
        "--field",
        "-H",
        "--header",
        "--input",
        "-q",
        "--jq",
        "-t",
        "--template",
        "--hostname",
        "-p",
        "--preview",
        "--cache",
    }
)


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #


class Classification(NamedTuple):
    """The routing decision for one gh argv. ``read`` True means App token."""

    read: bool
    cmd_class: str
    method: str
    repo: str | None
    reason: str


def _operator(
    cmd_class: str, reason: str, method: str = "", repo: str | None = None
) -> Classification:
    return Classification(False, cmd_class, method, repo, reason)


def _is_org(owner: str | None) -> bool:
    return owner is not None and owner.lower() == ORG.lower()


def _flag_value(args: Sequence[str], names: Sequence[str]) -> list[str]:
    """Every value given to any of ``names`` (``-R x``, ``-Rx``, ``--repo=x``)."""
    values: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        for name in names:
            if arg == name and i + 1 < len(args):
                values.append(args[i + 1])
                i += 1
                break
            if name.startswith("--") and arg.startswith(name + "="):
                values.append(arg[len(name) + 1 :])
                break
            if (
                not name.startswith("--")
                and arg.startswith(name)
                and len(arg) > len(name)
            ):
                values.append(arg[len(name) :])
                break
        i += 1
    return values


def _remote_repo(env: Mapping[str, str]) -> str | None:
    """The OmniNode-ai repository of the cwd's git remotes, if they all agree."""
    try:
        out = subprocess.run(
            ["git", "remote", "-v"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=dict(env),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    repos: set[str] = set()
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?$", parts[1])
        if m:
            repos.add(f"{m.group(1)}/{m.group(2)}")
    return repos.pop() if len(repos) == 1 else None


def _resolve_repo(
    args: Sequence[str], env: Mapping[str, str], *, positional_repo: bool
) -> str | None:
    explicit = _flag_value(args, ["-R", "--repo"])
    if explicit:
        return explicit[-1]
    for arg in args:
        m = _GITHUB_URL.match(arg)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    if positional_repo:
        for arg in args:
            if not arg.startswith("-") and _OWNER_REPO.match(arg):
                return arg
    if env.get("GH_REPO"):
        return env["GH_REPO"]
    return _remote_repo(env)


def _owner(repo: str | None) -> str | None:
    if not repo:
        return None
    repo = repo.split("github.com/")[-1]
    return repo.split("/", 1)[0] if "/" in repo else None


def _search_scoped(texts: Sequence[str], owners: Sequence[str]) -> bool:
    """True when a search is limited to the organization and to nothing else."""
    scopes = [m.group(1) for t in texts for m in _SEARCH_SCOPE.finditer(t)]
    scopes += [o.split("/", 1)[0] for o in owners]
    return bool(scopes) and all(_is_org(s) for s in scopes)


def _classify_subcommand(args: Sequence[str], env: Mapping[str, str]) -> Classification:
    group, verb = args[0], (args[1] if len(args) > 1 else "")
    cmd_class = f"{group} {verb}".strip()
    rest = list(args[2:])
    if group == "search":
        if verb not in SEARCH_KINDS:
            return _operator(cmd_class, "not-a-routed-read")
        owners = _flag_value(rest, ["--owner"]) + _flag_value(rest, ["--repo", "-R"])
        if not _search_scoped([a for a in rest if not a.startswith("-")], owners):
            return _operator(cmd_class, "search-unscoped", "GET")
        return Classification(True, cmd_class, "GET", ORG, "read-search")
    if (group, verb) not in READ_SUBCOMMANDS:
        return _operator(cmd_class, "not-a-routed-read")
    repo = _resolve_repo(rest, env, positional_repo=(group, verb) == ("repo", "view"))
    if not _is_org(_owner(repo)):
        return _operator(cmd_class, "repo-outside-org", "GET", repo)
    return Classification(True, cmd_class, "GET", repo, "read-subcommand")


def _read_graphql_query(
    fields: Sequence[tuple[str, str, bool]], input_path: str | None
) -> str | None:
    """The GraphQL document, or None if it cannot be read without side effects."""
    for name, value, typed in fields:
        if name != "query":
            continue
        if typed and value.startswith("@"):
            if value == "@-":
                return None
            try:
                return Path(value[1:]).read_text()
            except OSError:
                return None
        return value
    if input_path and input_path != "-":
        try:
            body = json.loads(Path(input_path).read_text())
        except (OSError, ValueError):
            return None
        query = body.get("query") if isinstance(body, dict) else None
        return query if isinstance(query, str) else None
    return None


def _classify_api(args: Sequence[str], env: Mapping[str, str]) -> Classification:
    method: str | None = None
    fields: list[tuple[str, str, bool]] = []
    input_path: str | None = None
    hostname: str | None = None
    endpoint: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        name, value = arg, None
        if arg.startswith("--") and "=" in arg:
            name, value = arg.split("=", 1)
        elif (
            not arg.startswith("--")
            and len(arg) > 2
            and arg[:2] in {"-X", "-f", "-F", "-H", "-q", "-t", "-p"}
        ):
            name, value = arg[:2], arg[2:]
        if name in _API_VALUE_FLAGS:
            if value is None:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if name in {"-X", "--method"}:
                method = value.upper()
            elif name in {"-f", "--raw-field", "-F", "--field"}:
                key, _, val = value.partition("=")
                fields.append((key, val, name in {"-F", "--field"}))
            elif name == "--input":
                input_path = value
            elif name == "--hostname":
                hostname = value
        elif not arg.startswith("-") and endpoint is None:
            endpoint = arg
        i += 1

    if endpoint is None:
        return _operator("api", "no-endpoint")
    host = hostname or env.get("GH_HOST") or "github.com"
    if host.lower() not in {"github.com", "api.github.com"}:
        return _operator("api", "host-not-github.com")

    if endpoint == "graphql":
        query = _read_graphql_query(fields, input_path)
        if query is None:
            return _operator("graphql", "graphql-query-unreadable", "POST")
        if re.search(r"\bmutation\b", query):
            return _operator("graphql", "graphql-mutation", "POST")
        if re.search(r"\bviewer\b", query):
            return _operator("graphql", "viewer-resolving", "POST")
        owners = [m.group(1) for m in _GQL_OWNER_LITERAL.finditer(query)]
        owners += [v for k, v, _ in fields if k.lower() in _GQL_OWNER_VARS]
        if any(not _is_org(o) for o in owners):
            return _operator("graphql", "graphql-owner-outside-org", "POST")
        if re.search(r"\bsearch\s*\(", query):
            texts = [query] + [v for _, v, _ in fields]
            if not _search_scoped(texts, []):
                return _operator("graphql", "search-unscoped", "POST")
        return Classification(True, "graphql", "POST", None, "read-graphql")

    effective = method or ("POST" if fields or input_path else "GET")
    if effective not in {"GET", "HEAD"}:
        return _operator("api", f"method-{effective}", effective)

    path = endpoint
    if path.startswith(("http://", "https://")):
        parts = urlsplit(path)
        if parts.netloc.lower() != "api.github.com":
            return _operator("api", "host-not-github.com", effective)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
    path = path.lstrip("/")
    if "{owner}" in path or "{repo}" in path:
        repo = env.get("GH_REPO") or _remote_repo(env)
        if not repo or "/" not in repo:
            return _operator("api", "placeholder-unresolved", effective)
        owner, name = repo.split("/", 1)
        path = path.replace("{owner}", owner).replace("{repo}", name)

    route, _, query_string = path.partition("?")
    segments = route.split("/")
    if segments[0] == "repos" and len(segments) >= 3:
        repo = f"{segments[1]}/{segments[2]}"
        if _is_org(segments[1]):
            return Classification(True, "api", effective, repo, "read-rest")
        return _operator("api", "repo-outside-org", effective, repo)
    if segments[0] == "search":
        texts = parse_qs(query_string).get("q", [])
        texts += [v for k, v, _ in fields if k == "q"]
        if "@me" in " ".join(texts):
            return _operator("api", "viewer-resolving", effective)
        if _search_scoped(texts, []):
            return Classification(True, "api", effective, ORG, "read-search")
        return _operator("api", "search-unscoped", effective)
    return _operator("api", "endpoint-not-routed", effective)


def classify(argv: Sequence[str], env: Mapping[str, str]) -> Classification:
    """Decide whether ``gh <argv>`` is a read the App token may serve."""
    if not argv or argv[0].startswith("-"):
        return _operator("meta", "not-a-routed-read")
    if any("@me" in a for a in argv):
        return _operator(" ".join(argv[:2]), "viewer-resolving")
    if argv[0] == "api":
        return _classify_api(list(argv[1:]), env)
    return _classify_subcommand(list(argv), env)


# --------------------------------------------------------------------------- #
# the read token
# --------------------------------------------------------------------------- #


class TokenResult(NamedTuple):
    token: str | None
    reason: str


def _read_cached(path: Path) -> str | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        # Readable by someone else: do not use it, replace it.
        path.unlink(missing_ok=True)
        return None
    try:
        data = json.loads(path.read_text())
        token, minted_at = data["token"], float(data["minted_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    age = _now() - minted_at
    if not isinstance(token, str) or not _INSTALLATION_TOKEN.fullmatch(token):
        return None
    if age < -60 or age >= TOKEN_MAX_AGE_S:
        return None
    return token


def _write_cached(path: Path, token: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, json.dumps({"token": token, "minted_at": _now()}).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.replace(path)


@contextlib.contextmanager
def _mint_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def cache_base(env: Mapping[str, str]) -> Path | None:
    """``$XDG_CACHE_HOME``, else ``$HOME/.cache`` (the XDG spec default), else None."""
    xdg = env.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        return Path(xdg)
    home = env.get("HOME", "").strip()
    return Path(home) / ".cache" if home else None


def acquire_read_token(env: Mapping[str, str]) -> TokenResult:
    """The cached read token, or a freshly minted one, or the reason there is none."""
    cmd = env.get(TOKEN_CMD_ENV, "").strip()
    if not cmd:
        return TokenResult(None, "token-cmd-unset")
    base = cache_base(env)
    if base is None:
        return TokenResult(None, "cache-home-unresolvable")
    cache = base / CACHE_SUBDIR / TOKEN_CACHE_NAME
    cached = _read_cached(cache)
    if cached:
        return TokenResult(cached, "cache-hit")
    with _mint_lock(cache.with_suffix(".lock")):
        cached = _read_cached(cache)  # a peer may have minted while we waited
        if cached:
            return TokenResult(cached, "cache-hit")
        try:
            proc = subprocess.run(
                shlex.split(cmd),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=TOKEN_CMD_TIMEOUT_S,
                check=False,
                env={k: v for k, v in env.items() if k not in {"GH_TOKEN", FLAG_ENV}},
            )
        except FileNotFoundError:
            return TokenResult(None, "token-cmd-not-found")
        except subprocess.TimeoutExpired:
            return TokenResult(None, "token-cmd-timeout")
        except (OSError, ValueError) as exc:
            return TokenResult(None, f"token-cmd-error-{type(exc).__name__}")
        if proc.returncode != 0:
            return TokenResult(None, f"token-cmd-exit-{proc.returncode}")
        token = proc.stdout.decode("utf-8", "replace").strip()
        if not _INSTALLATION_TOKEN.fullmatch(token):
            return TokenResult(None, "token-not-installation-token")
        _write_cached(cache, token)
        return TokenResult(token, "minted")


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #


class RouteRecord(NamedTuple):
    """What the usage log records for one call. Never carries a token."""

    identity: str
    reason: str
    cmd_class: str
    method: str
    repo: str | None
    exit_code: int


Recorder = Callable[[RouteRecord], None]


def routing_enabled(env: Mapping[str, str]) -> bool:
    return env.get(FLAG_ENV, "") == "1"


def _run_inherit(real_gh: str, argv: Sequence[str], env: Mapping[str, str]) -> int:
    return subprocess.run([real_gh, *argv], env=dict(env), check=False).returncode


def route_and_run(
    argv: Sequence[str], real_gh: str, env: Mapping[str, str], recorder: Recorder
) -> int:
    """Run ``real_gh argv`` on the identity the routing picks; return its exit code."""
    cls = classify(argv, env)

    def record(identity: str, reason: str, code: int) -> int:
        recorder(
            RouteRecord(identity, reason, cls.cmd_class, cls.method, cls.repo, code)
        )
        return code

    if not routing_enabled(env):
        return record(
            IDENTITY_OPERATOR, "routing-disabled", _run_inherit(real_gh, argv, env)
        )
    if not cls.read:
        return record(IDENTITY_OPERATOR, cls.reason, _run_inherit(real_gh, argv, env))

    tok = acquire_read_token(env)
    if tok.token is None:
        return record(IDENTITY_FALLBACK, tok.reason, _run_inherit(real_gh, argv, env))

    app_env = {**env, "GH_TOKEN": tok.token}
    proc = subprocess.run(
        [real_gh, *argv], env=app_env, stderr=subprocess.PIPE, check=False
    )
    if proc.returncode != 0 and INTEGRATION_REFUSAL.encode() in proc.stderr:
        return record(
            IDENTITY_FALLBACK, "integration-refused", _run_inherit(real_gh, argv, env)
        )
    sys.stderr.buffer.write(proc.stderr)
    sys.stderr.flush()
    return record(IDENTITY_APP, cls.reason, proc.returncode)


def _lane(env: Mapping[str, str]) -> str:
    for key in ("ONEX_LANE", "CLAUDE_CODE_SESSION_ID"):
        if env.get(key):
            return env[key]
    try:
        out = subprocess.run(
            ["ps", "-o", "comm=", "-p", str(os.getppid())],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return f"parent:{Path(out.stdout.strip()).name or 'unknown'}"
    except (OSError, subprocess.SubprocessError):
        return "parent:unknown"


def jsonl_recorder(path: Path, env: Mapping[str, str]) -> Recorder:
    """A recorder appending one JSON line per call. Fields only; no token."""

    def _record(rec: RouteRecord) -> None:
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "lane": _lane(env),
            **rec._asdict(),
        }
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, sort_keys=True) + "\n")
        except OSError as exc:
            sys.stderr.write(
                f"gh_route: usage log not written ({exc.__class__.__name__})\n"
            )

    return _record


def resolve_real_gh(path_env: str, shim_dir: Path) -> str | None:
    """The first ``gh`` on PATH that is not this directory's shim."""
    own = shim_dir.resolve()
    for entry in path_env.split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry) / "gh"
        try:
            real = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if real.parent == own or Path(entry).resolve() == own:
            continue
        try:
            with open(real, "rb") as fh:
                if SHIM_MARKER in fh.read(8192):
                    continue  # an installed copy of the shim, not the real gh
        except OSError:
            continue
        if os.access(real, os.X_OK) and real.is_file():
            return str(candidate)
    return None


def _result_file_recorder(path: Path) -> Recorder:
    """Write ``identity reason`` for the calling shim's own usage line. No token."""

    def _record(rec: RouteRecord) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{rec.identity} {rec.reason}\n")

    return _record


def main(argv: Sequence[str]) -> int:
    args = list(argv)
    result_file: Path | None = None
    if len(args) >= 3 and args[0] == "exec" and args[1] == "--result-file":
        result_file = Path(args[2])
        del args[1:3]
    if len(args) < 2 or args[0] not in {"exec", "classify"} or args[1] != "--":
        sys.stderr.write(
            "usage: gh_route.py exec [--result-file PATH] -- <gh arguments>\n"
            "       gh_route.py classify -- <gh arguments>\n"
        )
        return 2
    argv = args
    gh_argv = list(argv[2:])
    env = dict(os.environ)
    if argv[0] == "classify":
        print(json.dumps(classify(gh_argv, env)._asdict(), sort_keys=True))
        return 0
    real_gh = resolve_real_gh(env.get("PATH", ""), Path(__file__).parent)
    if real_gh is None:
        sys.stderr.write("gh_route: no real gh found on PATH past the shim\n")
        return 127
    base = cache_base(env)

    def _unlogged(rec: RouteRecord) -> None:
        # Say so rather than drop the line silently; only when routing is on,
        # so a disabled router adds nothing to any caller's stderr.
        if routing_enabled(env):
            sys.stderr.write(
                f"gh_route: no cache home (XDG_CACHE_HOME, HOME); {rec.identity} "
                "call not logged\n"
            )

    recorder: Recorder
    if result_file is not None:
        recorder = _result_file_recorder(result_file)
    elif base is not None:
        recorder = jsonl_recorder(base / CACHE_SUBDIR / USAGE_LOG_NAME, env)
    else:
        recorder = _unlogged
    return route_and_run(gh_argv, real_gh, env, recorder)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
