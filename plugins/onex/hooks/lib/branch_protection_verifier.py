# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Branch-protection rollout-verification guard helper.

Parses a `gh api ... PUT/PATCH .../branches/<branch>/protection` invocation and
verifies that every `required_status_checks.contexts[]` entry is actually
emitted by a workflow on the target repo. Blocks rollouts that would perma-BLOCK
every PR on the repo (the root cause of the 2026-04-17 overnight wedge).

Reads tool-use JSON from stdin, writes a Claude Code hook decision JSON to stdout,
and exits 0 (allow) or 2 (block).

Reuses the observed-check probe from
`omnibase_infra/scripts/audit-branch-protection.py:59-83` by shelling out to
`gh pr checks` — the hook lives in the `omniclaude` plugin and cannot import
from another repo, so the minimal probe is inlined here.

See OMN-9038 and retrospective §7 P0.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

_PROTECTION_URL_RE = re.compile(
    r"repos/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/branches/(?P<branch>[^/\s]+)/protection"
)

_METHOD_RE = re.compile(
    r"(?:--method|-X)\s+(?P<method>PUT|PATCH)\b",
    re.IGNORECASE,
)

_CONTEXT_F_RE = re.compile(
    r"(?:-f|--raw-field|-F|--field)\s+required_status_checks\[contexts\]\[\]=(?P<value>\S+)"
)

_INPUT_FLAG_RE = re.compile(r"--input\s+\S+")

# Common shell wrappers that hide a `gh api ...` call inside a quoted payload:
# `bash -lc '<payload>'`, `sh -c "..."`, `zsh -c ...`, `bash -euo pipefail -c ...`,
# `/usr/bin/env bash -c ...`, and nested combinations. `_unwrap_shell_wrapper`
# walks tokens to find the shell-binary and `-*c*` flag rather than relying on
# a fixed position, so interim flags (`-euo pipefail`) and env wrappers cannot
# be used to bypass the guard.
_SHELL_BIN_RE = re.compile(r"(?:^|/)(?:ba|z|k)?sh$")
_ENV_BIN_RE = re.compile(r"(?:^|/)env$")
_MAX_WRAPPER_DEPTH = 3

_GH_TIMEOUT_S = 15
_PR_SAMPLE_SIZE = 10


def _load_input() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _block(reason: str) -> None:
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
    sys.stdout.write("\n")
    sys.exit(2)


def _allow(tool_info: dict) -> None:
    sys.stdout.write(json.dumps(tool_info))
    sys.stdout.write("\n")
    sys.exit(0)


def _fail_open(tool_info: dict, log_line: str) -> None:
    # Retro design rule: hooks fail open on transient GitHub API errors. The
    # scheduled audit (OMN-9034) catches any drift within 4h.
    sys.stderr.write(f"[OMN-9038] fail-open: {log_line}\n")
    _allow(tool_info)


def _extract_protection_mutation(command: str) -> tuple[str, str, str] | None:
    """Return (owner, repo, branch) if this command is a branch-protection write."""
    if "gh api" not in command:
        return None
    method_match = _METHOD_RE.search(command)
    url_match = _PROTECTION_URL_RE.search(command)
    if url_match is None:
        return None
    # `gh api` defaults to GET; require an explicit mutating method.
    if method_match is None:
        return None
    method = method_match.group("method").upper()
    if method not in {"PUT", "PATCH"}:
        return None
    return (
        url_match.group("owner"),
        url_match.group("repo"),
        url_match.group("branch"),
    )


def _unwrap_shell_wrapper(command: str) -> str:
    """If `command` is a shell wrapper, return the inner payload; else the input.

    Handles, in one pass:
    - `bash -c '...'`, `sh -c "..."`, `zsh -c '...'`, `ksh -c ...`
    - `bash -lc '...'` (login + command)
    - `bash -euo pipefail -c '...'` (interim option flags between shell and `-c`)
    - `/usr/bin/env bash -c '...'` (env wrapper)
    - `/bin/bash -c '...'` (absolute shell path)
    - Nested wrappers up to `_MAX_WRAPPER_DEPTH` levels.

    Regression guard for CR findings on PR #1338: a rollout wrapped in any
    of the above would otherwise evade tokenization because the outer
    `shlex.split` sees the entire inner string as one token, making
    `_parse_contexts` return [] and the guard fail open.
    """
    current = command
    for _ in range(_MAX_WRAPPER_DEPTH):
        try:
            tokens = shlex.split(current, posix=True)
        except ValueError:
            return current
        if not tokens:
            return current

        # Skip an optional env wrapper: `env bash -c ...` / `/usr/bin/env bash -c ...`.
        # `env` may be followed by `-i`, `VAR=value`, etc. before the shell; walk
        # forward until we hit what looks like a shell binary.
        start = 0
        if _ENV_BIN_RE.search(tokens[0]):
            j = 1
            while j < len(tokens) and not _SHELL_BIN_RE.search(tokens[j]):
                # Stop if we run into what's clearly not an env-arg: pure `-c`
                # would mean this isn't an env-for-shell chain.
                if tokens[j] == "-c" or tokens[j].startswith("-c"):
                    break
                j += 1
            start = j

        if start >= len(tokens) or not _SHELL_BIN_RE.search(tokens[start]):
            return current

        # Find the first `-c`-family flag after the shell, skipping any interim
        # option flags (`-e`, `-u`, `-o pipefail`, `-l`, etc.).
        payload_idx = None
        i = start + 1
        while i < len(tokens) - 1:
            tok = tokens[i]
            if tok.startswith("-") and "c" in tok.lstrip("-"):
                payload_idx = i + 1
                break
            if tok == "-o" and i + 1 < len(tokens):
                # `-o pipefail` style — skip the option value.
                i += 2
                continue
            i += 1
        if payload_idx is None or payload_idx >= len(tokens):
            return current

        current = tokens[payload_idx]
    return current


def _parse_contexts(command: str) -> list[str]:
    """Extract required_status_checks.contexts[] values from inline -f args.

    Tokenizes the command with shlex so quoted context names (e.g.,
    'gate / CodeRabbit Thread Check') survive. Unwraps `bash -lc '...'`
    style wrappers first so they cannot be used to bypass the guard.
    """
    inner = _unwrap_shell_wrapper(command)
    try:
        tokens = shlex.split(inner, posix=True)
    except ValueError:
        # Unbalanced quotes — fall back to a regex on the raw string so we
        # don't silently miss contexts.
        return [m.group("value").strip("'\"") for m in _CONTEXT_F_RE.finditer(inner)]

    contexts: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-f", "--raw-field", "-F", "--field") and i + 1 < len(tokens):
            kv = tokens[i + 1]
            if kv.startswith("required_status_checks[contexts][]="):
                contexts.append(kv.split("=", 1)[1])
            i += 2
            continue
        i += 1
    return contexts


def _has_input_flag(command: str) -> bool:
    return _INPUT_FLAG_RE.search(_unwrap_shell_wrapper(command)) is not None


def _get_observed_checks(owner: str, repo: str) -> set[str] | None:
    """Return the union of check-run names observed across recent PRs.

    Samples `_PR_SAMPLE_SIZE` recent PRs (any state) and unions their check
    names so path-scoped or infrequently-run workflows — absent from any
    single PR — are not falsely treated as unknown.

    Regression for CR on PR #1338: a one-PR sample produced false-block
    rollouts when the sampled PR happened to exclude a legitimate
    path-scoped workflow.

    Returns None only when no checks are observed at all so the caller can
    fail-open.
    """
    try:
        listing = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                f"{owner}/{repo}",
                "--state",
                "all",
                "--limit",
                str(_PR_SAMPLE_SIZE),
                "--json",
                "number",
            ],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_S,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if listing.returncode != 0 or not listing.stdout.strip():
        return None
    try:
        prs = json.loads(listing.stdout)
    except json.JSONDecodeError:
        return None
    if not prs or not isinstance(prs, list):
        return None

    pr_numbers = [
        str(p["number"]) for p in prs if isinstance(p, dict) and "number" in p
    ]
    if not pr_numbers:
        return None

    observed: set[str] = set()
    for pr_number in pr_numbers:
        try:
            checks = subprocess.run(
                ["gh", "pr", "checks", pr_number, "--repo", f"{owner}/{repo}"],
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_S,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Transient failure on a single PR: skip, keep aggregating.
            continue
        combined = (checks.stdout or "") + (checks.stderr or "")
        for line in combined.strip().split("\n"):
            if "\t" in line:
                observed.add(line.split("\t")[0].strip())
    return observed or None


def verify(command: str, tool_info: dict) -> None:
    """Main decision function. Exits 0 (allow) or 2 (block)."""
    target = _extract_protection_mutation(command)
    if target is None:
        _allow(tool_info)
        return

    owner, repo, branch = target

    if _has_input_flag(command):
        # MVP: payload body lives in a file we can't safely parse here.
        _fail_open(
            tool_info,
            f"--input form on {owner}/{repo}:{branch} — MVP pass-through "
            "(follow-up: parse payload file to enforce contexts).",
        )
        return

    contexts = _parse_contexts(command)
    if not contexts:
        # Mutation without inline contexts (may be removing the block entirely,
        # or tweaking an unrelated field). Nothing to verify; allow.
        _allow(tool_info)
        return

    observed = _get_observed_checks(owner, repo)
    if observed is None:
        _fail_open(
            tool_info,
            f"could not probe observed checks for {owner}/{repo} "
            "(no PRs, gh error, or timeout).",
        )
        return

    unmatched = [c for c in contexts if c not in observed]
    if not unmatched:
        _allow(tool_info)
        return

    reason_lines = [
        "BLOCKED: branch-protection rollout would perma-BLOCK every PR on "
        f"{owner}/{repo}:{branch}.",
        "",
        "The following required_status_checks contexts are not emitted by any "
        "workflow on this repo:",
    ]
    for name in unmatched:
        reason_lines.append(f"  - {name!r}")
    reason_lines.extend(
        [
            "",
            f"Observed check names (union across up to {_PR_SAMPLE_SIZE} recent PRs):",
            *(f"  - {name!r}" for name in sorted(observed)),
            "",
            "Fix the workflow job name or the protection context string before "
            "proceeding. See retrospective §7 P0 and OMN-9038. The scheduled "
            "audit (OMN-9034) runs every 4h as a complementary check.",
        ]
    )
    _block("\n".join(reason_lines))


def main() -> None:
    tool_info = _load_input()
    if tool_info.get("tool_name") != "Bash":
        _allow(tool_info)
        return

    command = (tool_info.get("tool_input") or {}).get("command") or ""
    if not command:
        _allow(tool_info)
        return

    if os.environ.get("OMN_9038_BP_GUARD_DISABLED") == "1":
        _fail_open(tool_info, "disabled via OMN_9038_BP_GUARD_DISABLED=1")
        return

    verify(command, tool_info)


if __name__ == "__main__":
    main()
