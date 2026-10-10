# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Refuse a lane's GitHub reads that go around the gh shim (OMN-20916).

RULING 2026-10-10T18:17:36Z: lanes must not be able to read GitHub at all, as
enforcement and not instruction. The gh shim (``scripts/user-bin/gh``, OMN-20911)
refuses every ``gh`` read from a lane. Three read paths do not pass through it, and
this handler refuses each one from a lane:

``MCP_TOOL`` (AC1)
    A GitHub MCP server's read tool (``pull_request_read``, ``list_pull_requests``,
    ``get_file_contents``, ``search_*``, ``list_commits``, ...). The server is any
    whose name contains ``github``; its tool is a write when its name starts with a
    write verb or ends in ``_write``, and a read otherwise, so a tool this module has
    never seen is refused rather than let through.

``RAW_API`` (AC2)
    A Bash command that names ``api.github.com`` (or ``uploads.github.com``) and an
    HTTP client: curl, wget, a script interpreter, an HTTP library. A token in the
    environment reads around the shim this way. A curl or wget with an explicit
    mutating method is a write and passes; a GraphQL POST passes only when it
    carries a mutation.

``REAL_GH`` (AC3)
    The real ``gh`` binary run by its path (``/opt/homebrew/bin/gh``,
    ``/usr/bin/gh``, ...) with a read subcommand. A path that is a copy of the shim
    (the ``ONEX_GH_USER_SHIM`` marker in its first 512 bytes, the same test the shim
    uses to skip its own copies) is the shim, and the shim judges it.

Who is a lane. A PreToolUse hook always runs inside Claude Code, so the half of the
shim's predicate that says "a Claude Code ancestor, or CLAUDECODE /
CLAUDE_CODE_SESSION_ID / CLAUDE_CODE_ENTRYPOINT set" is true of the operator's own
interactive session too and cannot tell the two apart here. The caller is a lane
when any of these holds:

* one of the shim's lane-specific environment markers is set
  (:data:`LANE_ENV_MARKERS`: ``ONEX_LANE`` and the agent and Codex names);
* the payload carries an ``agent_id``, which Claude Code sets only on a
  subagent's tool call (every Agent and Workflow lane);
* the session's entrypoint is headless (``sdk-cli``, ``sdk-py``, ``sdk-ts``):
  ``claude -p`` and the Agent SDK, which is how remote and overnight lanes run.

None of these makes a lane in lite mode (a non-OmniNode install), where a customer's
own subagents and headless runs are not lanes and are never refused.

The operator's interactive session (entrypoint ``cli``, no marker, no agent_id) is
not a lane and is never refused. A write is never refused. Every refusal names the
local reader: the PR watcher state (``pr_state_local.py``), the canonical clones,
and the pr-state-observed events on the bus.

What this does not see. A hook reads the command text only, so a script file that
reads a token from the environment and calls the API itself, or a gh path built at
run time (``"$(command -v -a gh | tail -1)"``), is not caught here; removing the
token from lane environments is the other half of the ticket.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from omniclaude.nodes.node_lane_github_read_guard_effect.enums import (
    EnumLaneGithubReadShape,
    EnumLaneGithubReadVerdict,
    EnumSessionMode,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.handlers.handler_gh_shim_probe import (
    FileGhShimProbe,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.models import (
    ModelLaneGithubReadDecision,
    ModelLaneGithubReadRequest,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.protocols import (
    ProtocolGhShimProbe,
)

#: The shim's lane-specific environment markers (scripts/user-bin/gh, _lane_context),
#: without CLAUDECODE, CLAUDE_CODE_SESSION_ID and CLAUDE_CODE_ENTRYPOINT, which every
#: Claude Code session sets, the operator's included.
LANE_ENV_MARKERS: tuple[str, ...] = (
    "ONEX_LANE",
    "ONEX_LANE_ID",
    "ONEX_AGENT_NAME",
    "CLAUDE_AGENT_NAME",
    "CLAUDE_SUBAGENT_NAME",
    "CODEX_THREAD_ID",
    "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_MANAGED_BY_NPM",
)

#: Entrypoints of a headless session: claude -p and the Agent SDKs.
HEADLESS_ENTRYPOINT_PREFIX = "sdk-"

# --- AC1: GitHub MCP tools ------------------------------------------------------

_MCP_WRITE_PREFIXES: tuple[str, ...] = (
    "add_",
    "approve_",
    "archive_",
    "assign_",
    "cancel_",
    "close_",
    "comment_",
    "create_",
    "delete_",
    "disable_",
    "dismiss_",
    "edit_",
    "enable_",
    "fork_",
    "lock_",
    "manage_",
    "mark_",
    "merge_",
    "push_",
    "remove_",
    "reopen_",
    "reprioritize_",
    "request_",
    "rerun_",
    "resolve_",
    "run_",
    "set_",
    "star_",
    "submit_",
    "transfer_",
    "unarchive_",
    "unlock_",
    "unstar_",
    "update_",
)


def _mcp_github_tool(tool_name: str) -> str | None:
    """The tool part of a GitHub MCP server's tool name, else None."""
    if not tool_name.startswith("mcp__"):
        return None
    server, sep, tool = tool_name[len("mcp__") :].partition("__")
    if not sep or not tool or "github" not in server.lower():
        return None
    return tool


def _mcp_tool_is_write(tool: str) -> bool:
    name = tool.lower()
    return name.endswith("_write") or name.startswith(_MCP_WRITE_PREFIXES)


# --- AC2: raw API calls -----------------------------------------------------------

#: The scheme and API host in front of a gh api endpoint given as a full address.
_API_ORIGIN = re.compile(r"(?i)^[a-z]+://api\.github\.com")
_API_HOST = re.compile(r"(?i)\b(?:api|uploads)\.github\.com\b")
_CLIENT_WORD = re.compile(
    r"(?<![\w.-])(curl|wget|xh|httpie|aria2c|python[0-9.]*|pypy[0-9.]*|node|nodejs|deno|"
    r"bun|ruby|perl|php|pwsh|powershell|openssl|ncat|socat|telnet|java|jshell)(?![\w-])"
)
_CURL_METHOD = re.compile(r"""(?:-X|--request|--method)(?:\s+|=)?['"]?([A-Za-z]+)""")
_DATA_FLAG = re.compile(
    r"(?<!\S)(?:-d|--data|--data-raw|--data-binary|--data-urlencode|-F|--form|--json|"
    r"--post-data|--post-file|-T|--upload-file)(?=[\s=]|$)"
)
_GET_FLAG = re.compile(r"(?<!\S)(?:-G|--get|-I|--head)(?=\s|$)")
_MUTATING_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# --- AC3: the real gh by path -----------------------------------------------------

#: Splits a command into simple-command segments. Quoting is ignored on purpose: an
#: over-split inside a quoted string can only add a segment, never hide one.
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|&()\n`]|\$\(")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: Commands that run their remaining arguments as a command.
_PREFIX_COMMANDS = frozenset(
    {
        "builtin",
        "command",
        "env",
        "exec",
        "nice",
        "nohup",
        "stdbuf",
        "sudo",
        "time",
        "timeout",
        "xargs",
    }
)
#: Prefix-command options that take a value as the next word.
_PREFIX_VALUE_OPTIONS = frozenset(
    {"-u", "-g", "-n", "-s", "-k", "-C", "-o", "-e", "-i", "-I", "-L", "-P"}
)

#: gh groups that never call the GitHub API.
_GH_LOCAL_GROUPS = frozenset(
    {
        "alias",
        "auth",
        "browse",
        "completion",
        "config",
        "extension",
        "help",
        "version",
        "--version",
        "-v",
        "--help",
        "-h",
    }
)
#: gh write verbs, per group. Every other verb is a read.
_GH_WRITE_VERBS: dict[str, frozenset[str]] = {
    "pr": frozenset(
        {
            "create",
            "edit",
            "comment",
            "review",
            "ready",
            "merge",
            "close",
            "reopen",
            "lock",
            "unlock",
            "update-branch",
            "revert",
        }
    ),
    "issue": frozenset(
        {
            "create",
            "edit",
            "comment",
            "close",
            "reopen",
            "delete",
            "transfer",
            "pin",
            "unpin",
            "lock",
            "unlock",
            "develop",
        }
    ),
    "run": frozenset({"rerun", "cancel", "delete"}),
    "workflow": frozenset({"run", "enable", "disable"}),
    "release": frozenset({"create", "edit", "delete", "upload", "delete-asset"}),
    "repo": frozenset(
        {
            "create",
            "edit",
            "delete",
            "fork",
            "archive",
            "unarchive",
            "rename",
            "sync",
            "set-default",
        }
    ),
    "label": frozenset({"create", "edit", "delete", "clone"}),
    "secret": frozenset({"set", "delete", "remove"}),
    "variable": frozenset({"set", "delete"}),
    "gist": frozenset({"create", "edit", "delete", "rename"}),
    "cache": frozenset({"delete"}),
    "codespace": frozenset({"create", "delete", "edit", "stop", "rebuild"}),
    "project": frozenset(
        {
            "create",
            "edit",
            "delete",
            "close",
            "copy",
            "field-create",
            "field-delete",
            "item-add",
            "item-archive",
            "item-create",
            "item-delete",
            "item-edit",
            "link",
            "unlink",
            "mark-template",
        }
    ),
}
#: gh flags that take a value as the next word, before the group.
_GH_GLOBAL_VALUE_FLAGS = frozenset({"-R", "--repo", "--hostname"})
_GH_API_FIELD_FLAGS = frozenset({"-f", "-F", "--field", "--raw-field", "--input"})


def _lane_reason(request: ModelLaneGithubReadRequest) -> str:
    """Why the caller is a lane, or empty when it is the operator's own session."""
    if request.mode is EnumSessionMode.LITE:
        return ""
    for marker in LANE_ENV_MARKERS:
        if marker in request.lane_markers:
            return f"environment {marker}"
    if request.agent_id:
        return f"subagent {request.agent_id}"
    if request.entrypoint.startswith(HEADLESS_ENTRYPOINT_PREFIX):
        return f"headless entrypoint {request.entrypoint}"
    return ""


def _words(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _strip_prefixes(words: list[str]) -> list[str]:
    """The words of the command a segment runs, past assignments and prefix commands."""
    i = 0
    while i < len(words):
        word = words[i]
        if _ASSIGNMENT.match(word):
            i += 1
            continue
        if os.path.basename(word) in _PREFIX_COMMANDS:
            prefix = os.path.basename(word)
            i += 1
            while i < len(words) and words[i].startswith("-"):
                option = words[i]
                i += 1
                if option in _PREFIX_VALUE_OPTIONS and i < len(words):
                    i += 1
            if prefix == "timeout" and i < len(words):
                i += 1  # the duration
            continue
        break
    return words[i:]


def _expand_path(path: str, request: ModelLaneGithubReadRequest) -> str | None:
    """The absolute path a gh path names, or None when it cannot be resolved."""
    home = request.home
    if path.startswith("~/") and home:
        path = home + path[1:]
    for spelling in ("${HOME}", "$HOME"):
        if path.startswith(spelling) and home:
            path = home + path[len(spelling) :]
    if "$" in path or path.startswith("~"):
        return None
    if not Path(path).is_absolute():
        if not request.cwd:
            return None
        path = os.path.join(request.cwd, path)
    return os.path.normpath(path)


def _gh_args_are_read(args: list[str]) -> tuple[bool, str]:
    """Whether a gh argv (after the binary) reads GitHub, and its group and verb."""
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] not in _GH_LOCAL_GROUPS:
        i += 2 if args[i] in _GH_GLOBAL_VALUE_FLAGS else 1
    if i >= len(args):
        return False, ""
    group = args[i]
    rest = args[i + 1 :]
    if group in _GH_LOCAL_GROUPS:
        return False, group
    if group == "api":
        return _gh_api_is_read(rest)
    verb = next((a for a in rest if not a.startswith("-")), "")
    label = f"{group} {verb}".strip()
    if verb in _GH_WRITE_VERBS.get(group, frozenset()):
        return False, label
    return True, label


def _gh_api_is_read(rest: list[str]) -> tuple[bool, str]:
    method = ""
    has_fields = False
    endpoint = ""
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("-X", "--method") and i + 1 < len(rest):
            method = rest[i + 1].upper()
            i += 2
            continue
        if arg.startswith("--method="):
            method = arg.split("=", 1)[1].upper()
        elif arg.startswith("-X") and len(arg) > 2:
            method = arg[2:].upper()
        elif arg in _GH_API_FIELD_FLAGS:
            has_fields = True
            i += 1  # the flag's value
        elif arg.split("=", 1)[0] in _GH_API_FIELD_FLAGS:
            has_fields = True
        elif not arg.startswith("-") and not endpoint:
            endpoint = arg
        i += 1
    endpoint = _API_ORIGIN.sub("", endpoint).lstrip("/")
    label = f"api {method or ('POST' if has_fields else 'GET')} {endpoint or '-'}"
    if endpoint == "graphql":
        return "mutation" not in " ".join(rest), label
    if endpoint == "rate_limit":
        return False, label
    if method:
        return method not in _MUTATING_METHODS, label
    return not has_fields, label


def _real_gh_read(
    request: ModelLaneGithubReadRequest, probe: ProtocolGhShimProbe
) -> tuple[str, str] | None:
    """(gh path, group and verb) of the first read by a real gh path, else None."""
    for segment in _SEGMENT_SPLIT.split(request.command):
        words = _strip_prefixes(_words(segment.strip()))
        if not words:
            continue
        program = words[0]
        if "/" not in program or os.path.basename(program) != "gh":
            continue
        resolved = _expand_path(program, request)
        if resolved is not None and probe.is_gh_shim(resolved):
            continue
        is_read, label = _gh_args_are_read(words[1:])
        if is_read:
            return program, label
    return None


def _raw_api_read(request: ModelLaneGithubReadRequest) -> str | None:
    """The HTTP client of a read that reaches the API directly, else None."""
    command = request.command
    if not _API_HOST.search(command):
        return None
    # The API host named only inside bare `gh ...` calls is the shim's to judge.
    outside_gh = False
    for segment in _SEGMENT_SPLIT.split(command):
        if not _API_HOST.search(segment):
            continue
        words = _strip_prefixes(_words(segment.strip()))
        if not words or words[0] != "gh":
            outside_gh = True
            break
    if not outside_gh:
        return None
    clients = {match.group(1) for match in _CLIENT_WORD.finditer(command)}
    if not clients:
        return None
    if clients <= {"curl", "wget"} and _raw_is_write(command):
        return None
    return ", ".join(sorted(clients))


def _raw_is_write(command: str) -> bool:
    match = _CURL_METHOD.search(command)
    if match:
        method = match.group(1).upper()
    elif _DATA_FLAG.search(command) and not _GET_FLAG.search(command):
        method = "POST"
    else:
        method = "GET"
    if method not in _MUTATING_METHODS:
        return False
    if re.search(r"(?i)api\.github\.com/graphql", command):
        return "mutation" in command
    return True


_LOCAL_READER = (
    "Read it locally instead:\n"
    "  PR state, checks, reviews, mergeability: python3 <omni plugin>/skills/merge-drain/"
    "scripts/pr_state_local.py --pr OmniNode-ai/<repo>#<n>   (--find <ticket> for PRs naming "
    "a ticket, --status for the state's age; the same records are the pr-state-observed "
    "events on the bus)\n"
    "  files, contents, diffs, commits, tags, history: git -C $OMNI_HOME/<repo> "
    "show|log|diff origin/<base>   (the canonical clones, kept fetched by canonical-clone-sync)\n"
    "  a failing-job log or one check run's detail: gh api repos/<o>/<r>/actions/jobs/<id>/logs "
    "through gh on PATH (the shim's cached read gateway; the job id is in the watcher record's "
    "ci.detail)\n"
    "Writes (gh pr create|edit|comment|review|merge, workflow run, run rerun, api "
    "POST/PATCH/PUT/DELETE, a graphql mutation, a GitHub MCP write tool) are unaffected."
)


def _refusal(
    shape: EnumLaneGithubReadShape, target: str, detail: str, lane: str
) -> str:
    if shape is EnumLaneGithubReadShape.MCP_TOOL:
        what = f"the GitHub MCP tool {target} is a GitHub read from a lane ({lane})"
    elif shape is EnumLaneGithubReadShape.RAW_API:
        what = (
            f"a direct call to the GitHub API ({target}) is a GitHub read from a lane "
            f"({lane}); a raw token call reads around the gh shim"
        )
    else:
        what = (
            f"{target} {detail} runs the real gh binary by its path, around the gh shim, "
            f"and is a GitHub read from a lane ({lane}); gh on PATH refuses it the same way"
        )
    return (
        f"REFUSED (OMN-20916): {what}. Lanes do not read GitHub; gh is for writes "
        "(RULING 2026-10-10T18:17:36Z).\n" + _LOCAL_READER
    )


class HandlerLaneGithubReadGuard:
    """Judges one PreToolUse call against the three read paths around the gh shim."""

    def __init__(self, shim_probe: ProtocolGhShimProbe | None = None) -> None:
        self._probe: ProtocolGhShimProbe = shim_probe or FileGhShimProbe()

    def handle(
        self, request: ModelLaneGithubReadRequest
    ) -> ModelLaneGithubReadDecision:
        shape = EnumLaneGithubReadShape.NONE
        target = ""
        detail = ""
        is_read = False
        mcp_tool = _mcp_github_tool(request.tool_name)
        if mcp_tool is not None:
            shape = EnumLaneGithubReadShape.MCP_TOOL
            target = request.tool_name
            is_read = not _mcp_tool_is_write(mcp_tool)
        elif request.tool_name == "Bash" and request.command:
            real_gh = _real_gh_read(request, self._probe)
            raw = _raw_api_read(request)
            if real_gh is not None:
                shape = EnumLaneGithubReadShape.REAL_GH
                target, detail = real_gh
                is_read = True
            elif raw is not None:
                shape = EnumLaneGithubReadShape.RAW_API
                target = raw
                is_read = True
        lane = _lane_reason(request)
        if not is_read or not lane:
            return ModelLaneGithubReadDecision(
                verdict=EnumLaneGithubReadVerdict.ALLOW,
                shape=shape,
                is_read=is_read,
                lane_reason=lane,
                target=target,
            )
        return ModelLaneGithubReadDecision(
            verdict=EnumLaneGithubReadVerdict.REFUSE,
            shape=shape,
            is_read=True,
            lane_reason=lane,
            target=target,
            reason=_refusal(shape, target, detail, lane),
        )


__all__ = [
    "HEADLESS_ENTRYPOINT_PREFIX",
    "LANE_ENV_MARKERS",
    "HandlerLaneGithubReadGuard",
]
