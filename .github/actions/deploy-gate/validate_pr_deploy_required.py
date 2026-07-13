# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Wave D CI gate: runtime-change PRs must cite a ticket with deploy evidence.

Ticket: OMN-8912
Root cause: OMN-8841 — Dockerfile.runtime changed, deploy never dispatched,
            deploy-agent inactive 2 days undetected.
Canonical source: OMN-9685 (omnibase_core PR #902) — narrowed path patterns,
                  removed skip-token bypass.
DGM-Phase6: moved here for single-source reuse across all repos.
OMN-14244: re-narrowed the ``src/*/cli/*.py`` heuristic — see the comment
           above ``CLI_PATH_PATTERNS`` below for what changed and why.

Usage (CI):
    python validate_pr_deploy_required.py \
        --changed-files "docker/Dockerfile.runtime src/omnibase_infra/runtime/service_kernel.py" \
        --pr-body "$(gh pr view $PR --json body -q .body)" \
        --contracts-dir contracts/

Exit codes:
    0  - Gate passed (no runtime change, or deploy evidence found)
    1  - Gate failed (runtime change detected but no deploy evidence)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern

# ---------------------------------------------------------------------------
# Runtime path patterns — ANY file matching these triggers the gate.
# Extend this list when new runtime-touching paths are discovered.
# ---------------------------------------------------------------------------
RUNTIME_PATH_PATTERNS = [
    # Docker layer
    "docker/Dockerfile*",
    "docker/docker-compose*.yml",
    "docker/docker-compose*.yaml",
    "docker/**/*.Dockerfile",
    "Dockerfile*",
    # Node handlers + contracts (omnibase_infra)
    "src/omnibase_infra/nodes/*/handlers/*.py",
    "src/omnibase_infra/nodes/*/handlers/*/*.py",
    "src/omnibase_infra/nodes/*/contract.yaml",
    "src/omnibase_infra/nodes/*/*/contract.yaml",
    # Runtime kernel
    "src/omnibase_infra/runtime/**/*.py",
    # Alert daemon (today's incident path — OMN-8870/OMN-8841)
    "scripts/monitor_logs.py",
    # omnimarket node handlers + runtime-touching paths only
    "src/omnimarket/nodes/*/handlers/*.py",
    "src/omnimarket/nodes/*/contract.yaml",
    "src/omnimarket/nodes/*/runtime/**/*.py",
    "src/omnimarket/services/**/*.py",
    # Cross-repo node handlers and runtime paths (OMN-9685: narrowed from catch-all)
    # Use both flat and nested forms since ** requires at least one path segment
    "src/*/nodes/*.py",
    "src/*/nodes/**/*.py",
    "src/*/runtime/*.py",
    "src/*/runtime/**/*.py",
    "src/*/handlers/*.py",
    "src/*/handlers/**/*.py",
    "src/*/services/*.py",
    "src/*/services/**/*.py",
    # Docker-management packages (OMN-14244): any file under a top-level
    # src/<pkg>/docker/ tree is deploy code by construction (compose
    # generation/validation, docker-compose CLI dispatch — e.g.
    # omnibase_infra's docker/catalog/cli.py, which the old cli/-directory
    # heuristic below MISSED entirely because "cli" is the filename here, not
    # a directory segment). The middle "*" binds exactly one path segment, so
    # this does NOT match src/*/models/docker/* (pure Pydantic/dataclass
    # models with zero I/O, one level deeper) — verified via _glob_to_regex.
    "src/*/docker/*.py",
    "src/*/docker/**/*.py",
    # Contract files trigger deploy (behavior change) — scoped to src/ to avoid
    # matching test fixtures and example directories.
    "src/**/contract.yaml",
]

# CLI modules (OMN-14244): OMN-9685 gated EVERY file under a src/*/cli/ tree,
# which is provably too broad — a pure PR-metadata/text-processing CLI (e.g.
# omnibase_infra's cli_occ.py: click plumbing over a text parser, zero
# docker/subprocess/kafka/ssh surface) is not deploy-relevant just because it
# lives in a directory named "cli". These paths are matched separately from
# RUNTIME_PATH_PATTERNS above and additionally require a deploy-signal content
# hit (see CLI_DEPLOY_SIGNAL_PATTERN / _cli_file_has_deploy_signal) before
# they trigger the gate. A file that cannot be read fails CLOSED (still
# gated) — see _cli_file_has_deploy_signal.
CLI_PATH_PATTERNS = [
    "src/*/cli/*.py",
    "src/*/cli/**/*.py",
]

# Deploy-relevant surfaces referenced by a CLI module's own source: any of
# these mean the module can act on docker/compose, shell out, reach a remote
# host, or dispatch onto Kafka (rpk / redeploy) — i.e. it is a genuine deploy
# CLI, not a pure data/text-processing one. Word-boundary, case-insensitive.
CLI_DEPLOY_SIGNAL_PATTERN = re.compile(
    r"\b(docker|subprocess|paramiko|fabric|kafka|rpk|compose|ssh|deploy)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Deploy evidence falsifiability (OMN-14505).
#
# The legacy rule was a substring test:
#
#     DEPLOY_KEYWORDS = ["docker exec", "rpk topic produce", "deploy"]
#     if any(kw in check_value.lower() for kw in DEPLOY_KEYWORDS): return True
#
# Because the bare word "deploy" was a keyword, ANY check_value containing the
# word "deploy" satisfied a REQUIRED merge gate — including one that verifies
# nothing. Worse, the receipt paths are themselves named `dod-deploy-*`, so a
# check_value passed on the *filename* alone. An audit of onex_change_control@dev
# (6,944 contracts) found 1,123 of 1,268 satisfying checks were circular greps of
# the receipt file the same OCC companion PR authored:
#
#     grep -q '^status: PASS$' drift/dod_receipts/OMN-X/dod-deploy-assessment/command.yaml
#
# — they grep their own receipt for text their own author wrote into it, so they
# can never go RED.
#
# Tightening the word list does NOT fix this: 66 of those circular checks ALREADY
# embed `docker exec` / `rpk topic produce` as *quoted text* inside the grep, so a
# stricter list passes them unchanged. A substring test structurally cannot tell
# "the probe executes" from "the probe's name appears as an argument to echo".
#
# The rule below is two-part, and the DENY runs first and unconditionally:
#
#   1. DENY self-reference — a check that reads back the receipt/contract tree the
#      evidence author writes is circular by construction. This is what defeats
#      embedding a probe keyword inside a quoted string.
#   2. ALLOW only a live-surface probe in COMMAND POSITION — the check_value is
#      shell-parsed (split on && || ; |, recursing into $(...) and `bash -c`), and
#      at least one segment's *command* must be a probe binary. `echo 'docker exec'`
#      does not qualify: shlex keeps "docker exec" as a single quoted argument to
#      `echo`, so `docker` never reaches command position.
#
# The distinguishing property is where the check's exit status gets its information.
# A real probe queries a live external surface whose state is NOT under the author's
# control at authoring time; a vacuous check reads back artifacts the author wrote.
#
# Fails CLOSED: an empty, non-string, or unparseable check_value is REJECTED.
# ---------------------------------------------------------------------------

# Retained ONLY for the report-only rollout stage (see FALSIFIABILITY_MODE_ENV):
# the legacy verdict is still computed so CI can log the old-vs-new delta before
# the new rule becomes load-bearing.
LEGACY_DEPLOY_KEYWORDS = ["docker exec", "rpk topic produce", "deploy"]

# Commands that probe a LIVE runtime surface. Their exit status depends on the
# state of a deployed system, not on the content of a file the author wrote.
LIVE_PROBE_COMMANDS = frozenset(
    {
        # containers / orchestrators
        "docker",
        "docker-compose",
        "podman",
        "nerdctl",
        "kubectl",
        # message broker
        "rpk",
        "kcat",
        "kafkacat",
        # datastores
        "psql",
        "mysql",
        "redis-cli",
        "valkey-cli",
        "mongosh",
        # HTTP surfaces
        "curl",
        "wget",
        "httpie",
        # remote hosts
        "ssh",
        # ONEX node dispatch against the live runtime
        "onex",
    }
)

# Transparent wrappers: they execute their argument, so the real command is the
# next token. `env -u PYTHONPATH docker exec ...` must still resolve to `docker`.
WRAPPER_COMMANDS = frozenset(
    {
        "env",
        "sudo",
        "time",
        "timeout",
        "nohup",
        "stdbuf",
        "nice",
        "command",
        "exec",
        "xargs",
        "then",
        "do",
    }
)

# Shells whose `-c <string>` argument is itself a script to parse.
SHELL_COMMANDS = frozenset({"bash", "sh", "zsh", "dash"})

# Artifact trees the evidence author writes in the SAME OCC companion PR. A
# check_value that reads these back is self-referential: its verdict is decided by
# text the author typed, not by the state of any deployed system.
SELF_REFERENTIAL_PATTERNS: list[Pattern[str]] = [
    # the DoD receipt tree — drift/dod_receipts/OMN-X/<item>/command.yaml
    re.compile(r"dod_receipts", re.IGNORECASE),
    # $CONTRACT_REPO_DIR / ${CONTRACT_REPO_DIR} — the OCC checkout root
    re.compile(r"\$\{?CONTRACT_REPO_DIR\b", re.IGNORECASE),
    # the ticket's own contract file
    re.compile(r"contracts/OMN-\d+\.ya?ml", re.IGNORECASE),
]

# Rollout control (OMN-14505). "report" computes the falsifiability verdict and
# logs it, but the gate's exit status stays on the legacy rule — zero merge risk
# while the true failure population is measured across the 4 consuming repos.
# "enforce" makes falsifiability load-bearing. The flip is an env change, not a
# code change: the enforce path is fully implemented and tested.
FALSIFIABILITY_MODE_ENV = "DEPLOY_GATE_FALSIFIABILITY"
FALSIFIABILITY_MODE_DEFAULT = "report"

# Author-facing guidance. It deliberately describes the PROPERTY required, not a
# word to type — the whole defect was that the gate advertised a magic substring,
# so authors supplied the substring instead of the evidence.
DEPLOY_EVIDENCE_GUIDANCE = (
    "Add a dod_evidence item to onex_change_control/contracts/OMN-XXXX.yaml whose "
    "check_value is a FALSIFIABLE deploy probe: it must execute a command against a "
    "live surface (docker/kubectl/rpk/psql/curl/ssh/onex) so that its exit status "
    "depends on the state of the deployed system. It must NOT read back the receipt "
    "or contract your own PR authors (drift/dod_receipts/..., $CONTRACT_REPO_DIR) — "
    "such a check greps text you wrote and can never go RED. "
    "Good: docker exec ${RUNTIME_CONTAINER:-omninode-runtime} python -c 'import <changed_module>'. "
    "Rejected: grep -q '^status: PASS$' drift/dod_receipts/OMN-XXXX/dod-deploy/command.yaml."
)

_CMD_SUBST_RE = re.compile(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
_BACKTICK_RE = re.compile(r"`([^`]*)`")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Shell operators that terminate one command and begin the next. Split on these
# only AFTER lexing — a `;` inside a quoted python -c string is data, not an
# operator, and splitting the raw text on it corrupts the quoting.
_OPERATOR_TOKENS = frozenset({"&&", "||", "|", ";", "&", "(", ")", "\n"})

# Wrapper flags that consume the following token as their value, so the real
# command is two tokens further on (`env -u PYTHONPATH docker exec ...`).
_WRAPPER_FLAGS_WITH_ARG = frozenset(
    {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
)

# `timeout 30`, `timeout 1m` — a bare duration argument to a wrapper.
_DURATION_RE = re.compile(r"^\d+(\.\d+)?[smhd]?$")


@dataclass(frozen=True)
class CheckVerdict:
    """Why one check_value was accepted or rejected as deploy evidence."""

    falsifiable: bool
    reason: str


def _lex(script: str) -> list[str]:
    """Lex a shell script into tokens, with operators kept as their own tokens.

    ``punctuation_chars=True`` is what makes this correct: it groups ``&&`` / ``||``
    as single tokens AND — critically — it lexes *after* quote handling, so a ``;``
    inside ``python -c "a; b"`` stays inside the quoted token instead of being
    mistaken for a command separator.

    Quote-stripping is also what makes the whole rule work: ``echo 'docker exec x'``
    lexes to ``['echo', 'docker exec x']``, so the probe name inside the quotes is a
    single *argument* token and can never reach command position.

    An unparseable script (unbalanced quotes) fails CLOSED — no tokens, no probe.
    """
    lexer = shlex.shlex(script, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def _command_of(tokens: list[str]) -> tuple[str | None, list[str]]:
    """Return (command, remaining_args) for one pipeline segment.

    Skips leading ``!`` negation, ``VAR=value`` assignments, and transparent
    wrappers (``env -u PYTHONPATH docker exec ...`` must still resolve to
    ``docker``; ``timeout 30 kubectl ...`` to ``kubectl``).

    ``command -v``/``command -V`` is a POSIX PATH-lookup builtin, not
    execution: ``command -v docker`` only tests that ``docker`` resolves to
    an executable, so its exit status carries no information about whether
    docker itself would succeed. Unwrapping it to ``docker`` (as with a real
    wrapper like ``env``) would let a lookup-only check pass as a live probe
    — the same vacuous-acceptance defect this file exists to close. Detected
    before generic wrapper-flag consumption so it can short-circuit to "no
    command" instead of falling through to the wrapped executable.
    """
    idx = 0
    in_wrapper = False
    while idx < len(tokens):
        word = tokens[idx]
        if word == "!" or _ASSIGNMENT_RE.match(word):
            idx += 1
            continue
        if Path(word).name.lower() in WRAPPER_COMMANDS:
            if Path(word).name.lower() == "command" and idx + 1 < len(tokens) and (
                tokens[idx + 1] in ("-v", "-V")
            ):
                return None, []
            in_wrapper = True
            idx += 1
            continue
        if in_wrapper:
            # Consume the wrapper's own flags/arguments until the real command.
            if word in _WRAPPER_FLAGS_WITH_ARG:
                idx += 2
                continue
            if word.startswith("-") or _DURATION_RE.match(word):
                idx += 1
                continue
        break
    if idx >= len(tokens):
        return None, []
    return Path(tokens[idx]).name.lower(), tokens[idx + 1 :]


def _commands_in(script: str, depth: int = 0) -> set[str]:
    """Return the commands appearing in COMMAND POSITION in a shell script.

    Recurses into ``$(...)`` / backtick substitutions and ``bash -c '<script>'``,
    because a probe genuinely executes in all three positions. Depth-bounded so
    pathological nesting cannot spin.
    """
    if depth > 4 or not script.strip():
        return set()

    found: set[str] = set()

    # Commands inside substitutions ARE executed — recurse before stripping them.
    for match in _CMD_SUBST_RE.finditer(script):
        found |= _commands_in(match.group(1), depth + 1)
    for match in _BACKTICK_RE.finditer(script):
        found |= _commands_in(match.group(1), depth + 1)

    # Replace substitutions with a space so their inner text is not re-read as a
    # top-level argument. Substituting a space (not "") keeps surrounding quotes
    # balanced: `test "$(docker ...)" = x` -> `test " " = x`.
    stripped = _BACKTICK_RE.sub(" ", _CMD_SUBST_RE.sub(" ", script))

    # Split the LEXED token stream on operator tokens — never the raw text.
    segment: list[str] = []
    segments: list[list[str]] = []
    for token in _lex(stripped):
        if token in _OPERATOR_TOKENS:
            segments.append(segment)
            segment = []
        else:
            segment.append(token)
    segments.append(segment)

    for tokens in segments:
        command, rest = _command_of(tokens)
        if command is None:
            continue

        # `bash -c '<script>'` — the -c argument is a script, not an argument.
        if command in SHELL_COMMANDS:
            if "-c" in rest:
                c_at = rest.index("-c")
                if c_at + 1 < len(rest):
                    found |= _commands_in(rest[c_at + 1], depth + 1)
            continue

        found.add(command)

    return found


def classify_check_value(value: object) -> CheckVerdict:
    """Decide whether a check_value is a FALSIFIABLE deploy probe.

    Falsifiable means: run it against un-deployed / unfixed code and it goes RED.
    Fails CLOSED — anything not provably a live probe is rejected.
    """
    if not isinstance(value, str) or not value.strip():
        return CheckVerdict(False, "check_value is empty or not a string")

    # (1) DENY self-reference FIRST and unconditionally. This is the rule that
    # defeats embedding a probe keyword as quoted text beside a circular grep.
    for pattern in SELF_REFERENTIAL_PATTERNS:
        if pattern.search(value):
            return CheckVerdict(
                False,
                "self-referential: reads back the receipt/contract tree the "
                "evidence author writes in the same PR, so its verdict is decided "
                "by text the author typed, not by the state of a deployed system "
                f"(matched {pattern.pattern!r})",
            )

    # (2) ALLOW only a live-surface probe in COMMAND POSITION.
    commands = _commands_in(value)
    probes = commands & LIVE_PROBE_COMMANDS
    if not probes:
        return CheckVerdict(
            False,
            "no live-surface probe in command position — the check's exit status "
            "cannot depend on the state of the deployed system (commands found: "
            f"{sorted(commands) or 'none'}; expected one of: "
            f"{sorted(LIVE_PROBE_COMMANDS)})",
        )

    return CheckVerdict(
        True, f"live-surface probe in command position: {sorted(probes)}"
    )


def _legacy_has_deploy_keyword(value: object) -> bool:
    """The pre-OMN-14505 substring rule. Retained only for report-mode delta logs."""
    if not isinstance(value, str):
        return False
    return any(kw in value.lower() for kw in LEGACY_DEPLOY_KEYWORDS)


def falsifiability_mode() -> str:
    """Resolve the rollout mode: 'report' (default) or 'enforce'."""
    mode = os.environ.get(FALSIFIABILITY_MODE_ENV, FALSIFIABILITY_MODE_DEFAULT)
    return mode.strip().lower() or FALSIFIABILITY_MODE_DEFAULT


def _glob_to_regex(pattern: str) -> Pattern[str]:
    """Convert a glob pattern (with ** support) to a compiled regex."""
    # Escape everything except * and ?
    parts = re.split(r"(\*\*|\*|\?)", pattern)
    regex_parts: list[str] = []
    for part in parts:
        if part == "**":
            regex_parts.append(".*")
        elif part == "*":
            regex_parts.append("[^/]*")
        elif part == "?":
            regex_parts.append("[^/]")
        else:
            regex_parts.append(re.escape(part))
    return re.compile("^" + "".join(regex_parts) + "$")


_COMPILED_RUNTIME_PATTERNS: list[Pattern[str]] = [
    _glob_to_regex(p) for p in RUNTIME_PATH_PATTERNS
]
_COMPILED_CLI_PATTERNS: list[Pattern[str]] = [
    _glob_to_regex(p) for p in CLI_PATH_PATTERNS
]

# Ticket ID pattern in PR body / commit messages
TICKET_PATTERN = re.compile(r"\bOMN-(\d+)\b", re.IGNORECASE)
EVIDENCE_SOURCE_PATTERN = re.compile(
    r"^Evidence-Source:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE
)
EVIDENCE_TICKET_PATTERN = re.compile(
    r"^Evidence-Ticket:\s*(OMN-\d+)\s*$", re.IGNORECASE | re.MULTILINE
)

DEFAULT_OCC_REF = "dev"


@dataclass
class DeployGateResult:
    passed: bool
    skipped: bool = False
    message: str = ""
    runtime_paths_hit: list[str] = field(default_factory=list)
    tickets_checked: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceMetadata:
    source: str | None = None
    ticket: str | None = None


@dataclass(frozen=True)
class OccEvidenceResolution:
    passed: bool
    occ_ref: str = DEFAULT_OCC_REF
    deploy_gate_required: bool = False
    skipped: bool = False
    source_kind: str = "canonical"
    evidence_ticket: str | None = None
    message: str = ""


def _cli_file_has_deploy_signal(path: str) -> bool:
    """Return True if a src/*/cli/ file references a deploy-relevant surface.

    Reads the file relative to the current working directory (CI runs this
    validator from the checked-out caller-repo root, so changed-file paths
    resolve directly). A file that cannot be read — deleted, renamed, or the
    working tree isn't checked out — fails CLOSED: treated as a hit so an
    unreadable CLI file is never silently exempted from the gate.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    return bool(CLI_DEPLOY_SIGNAL_PATTERN.search(text))


def find_runtime_paths(changed_files: list[str]) -> list[str]:
    """Return subset of changed_files that match runtime path patterns.

    CLI_PATH_PATTERNS files (src/*/cli/**) are matched separately from the
    unconditional RUNTIME_PATH_PATTERNS: they only count as a hit when their
    own content carries a deploy-relevant signal (see
    _cli_file_has_deploy_signal / OMN-14244).
    """
    hits: list[str] = []
    for f in changed_files:
        if any(regex.match(f) for regex in _COMPILED_RUNTIME_PATTERNS):
            hits.append(f)
            continue
        if any(regex.match(f) for regex in _COMPILED_CLI_PATTERNS) and (
            _cli_file_has_deploy_signal(f)
        ):
            hits.append(f)
    return hits


def parse_evidence_metadata(pr_body: str) -> EvidenceMetadata:
    """Extract deploy-gate Evidence-* metadata from a PR body."""
    source_match = EVIDENCE_SOURCE_PATTERN.search(pr_body)
    ticket_match = EVIDENCE_TICKET_PATTERN.search(pr_body)
    return EvidenceMetadata(
        source=source_match.group(1).strip() if source_match else None,
        ticket=ticket_match.group(1).upper() if ticket_match else None,
    )


def _run_gh_json(args: list[str]) -> dict | list | str | int | float | bool | None:
    """Run gh and parse JSON output. Separated for focused unit tests."""
    completed = subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    output = completed.stdout.strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def _resolve_occ_pr_source(source: str) -> tuple[str | None, str]:
    occ_pr_num = re.sub(r"^OCC#", "", source, flags=re.IGNORECASE)
    pr_json = _run_gh_json(
        [
            "pr",
            "view",
            occ_pr_num,
            "--repo",
            "OmniNode-ai/onex_change_control",
            "--json",
            "state,headRefOid,mergeCommit",
        ]
    )
    if not isinstance(pr_json, dict):
        return None, "open-pr"
    if pr_json.get("state") == "MERGED":
        merge_commit = pr_json.get("mergeCommit")
        if isinstance(merge_commit, dict):
            return merge_commit.get("oid"), "merged"
        return None, "merged"
    head_ref_oid = pr_json.get("headRefOid")
    return head_ref_oid if isinstance(head_ref_oid, str) else None, "open-pr"


def _resolve_occ_sha_source(source: str) -> tuple[str | None, str]:
    compare_json = _run_gh_json(
        [
            "api",
            f"repos/OmniNode-ai/onex_change_control/compare/HEAD...{source}",
        ]
    )
    if isinstance(compare_json, dict) and compare_json.get("status") in {
        "behind",
        "identical",
    }:
        commit_json = _run_gh_json(
            ["api", f"repos/OmniNode-ai/onex_change_control/commits/{source}"]
        )
        if isinstance(commit_json, dict):
            commit_sha = commit_json.get("sha")
            return commit_sha if isinstance(commit_sha, str) else None, "merged"
        return None, "merged"

    open_prs_json = _run_gh_json(
        [
            "pr",
            "list",
            "--repo",
            "OmniNode-ai/onex_change_control",
            "--state",
            "open",
            "--json",
            "headRefOid",
        ]
    )
    if isinstance(open_prs_json, list):
        for item in open_prs_json:
            if not isinstance(item, dict):
                continue
            head_ref_oid = item.get("headRefOid")
            if isinstance(head_ref_oid, str) and head_ref_oid.startswith(source):
                return head_ref_oid, "open-pr"
    return None, "unknown"


def resolve_occ_evidence_source(
    changed_files: list[str],
    pr_body: str,
    default_occ_ref: str = DEFAULT_OCC_REF,
) -> OccEvidenceResolution:
    """Resolve deploy-gate OCC checkout ref from PR Evidence-* metadata."""
    runtime_hits = find_runtime_paths(changed_files)
    metadata = parse_evidence_metadata(pr_body)

    if not runtime_hits:
        return OccEvidenceResolution(
            passed=True,
            occ_ref=default_occ_ref,
            skipped=True,
            deploy_gate_required=False,
            message="No runtime paths touched — deploy-gate OCC checkout skipped.",
        )

    if not metadata.source:
        return OccEvidenceResolution(
            passed=True,
            occ_ref=default_occ_ref,
            deploy_gate_required=True,
            message=(
                "Evidence-Source not present — using canonical OCC contract source."
            ),
        )

    if not metadata.ticket:
        return OccEvidenceResolution(
            passed=False,
            deploy_gate_required=True,
            source_kind="invalid",
            message=(
                "DEPLOY GATE FAILED: PR body has Evidence-Source but is missing "
                "Evidence-Ticket: OMN-XXXX. Add Evidence-Ticket so deploy-gate "
                "can validate the contract at the pinned OCC source."
            ),
        )

    if re.match(r"^OCC#[0-9]+$", metadata.source, re.IGNORECASE):
        occ_ref, source_kind = _resolve_occ_pr_source(metadata.source)
    elif re.match(r"^[0-9a-f]{7,40}$", metadata.source, re.IGNORECASE):
        occ_ref, source_kind = _resolve_occ_sha_source(metadata.source.lower())
    else:
        return OccEvidenceResolution(
            passed=False,
            deploy_gate_required=True,
            source_kind="invalid",
            evidence_ticket=metadata.ticket,
            message=(
                f"DEPLOY GATE FAILED: Evidence-Source value {metadata.source!r} "
                "is not valid. Accepted forms: OCC#<number> or a 7-40 "
                "character OCC commit SHA."
            ),
        )

    if not occ_ref:
        return OccEvidenceResolution(
            passed=False,
            deploy_gate_required=True,
            source_kind=source_kind,
            evidence_ticket=metadata.ticket,
            message=(
                f"DEPLOY GATE FAILED: Evidence-Source {metadata.source!r} "
                "could not be resolved to an OCC PR head or merged OCC commit."
            ),
        )

    return OccEvidenceResolution(
        passed=True,
        occ_ref=occ_ref,
        deploy_gate_required=True,
        source_kind=source_kind,
        evidence_ticket=metadata.ticket,
        message=(
            f"Evidence-Source resolved to OCC ref {occ_ref} "
            f"for {metadata.ticket} ({source_kind})."
        ),
    )


def iter_check_values(contract_path: Path) -> list[tuple[str, object]]:
    """Yield (evidence_item_id, check_value) for every check in a ticket contract."""
    if not contract_path.exists():
        return []
    import yaml

    try:
        with contract_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (yaml.YAMLError, OSError):
        return []

    dod_evidence = data.get("dod_evidence", []) if isinstance(data, dict) else []
    out: list[tuple[str, object]] = []
    for item in dod_evidence:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or item.get("evidence_id") or "?")
        for check in item.get("checks", []) or []:
            if isinstance(check, dict):
                out.append((item_id, check.get("check_value", "")))
    return out


def has_deploy_evidence(contract_path: Path) -> bool:
    """Return True if the contract declares at least one FALSIFIABLE deploy probe.

    OMN-14505: this used to be a substring test for the word "deploy", which any
    string containing that word satisfied. It is now a falsifiability test — see
    ``classify_check_value``. In "report" mode (the rollout default) the returned
    verdict stays on the legacy rule so no repo's merges are wedged, but the
    falsifiability verdict is computed and logged so the delta is measurable.
    """
    checks = iter_check_values(contract_path)
    enforce = falsifiability_mode() == "enforce"

    falsifiable = [(i, v) for i, v in checks if classify_check_value(v).falsifiable]
    legacy = [(i, v) for i, v in checks if _legacy_has_deploy_keyword(v)]

    if enforce:
        return bool(falsifiable)

    # Report mode: surface the vacuous checks the legacy rule is about to accept.
    if legacy and not falsifiable:
        print(
            f"::warning::deploy-gate falsifiability (OMN-14505, report-only): "
            f"{contract_path.name} passes the LEGACY substring rule but declares NO "
            f"falsifiable deploy probe. Under enforcement this ticket would FAIL. "
            f"Vacuous checks: "
            + "; ".join(
                f"[{i}] {classify_check_value(v).reason}" for i, v in legacy[:3]
            )
        )
    return bool(legacy)


def validate_pr_deploy_gate(
    changed_files: list[str],
    pr_body: str,
    contracts_dir: Path,
) -> DeployGateResult:
    """Check runtime-change PRs for deploy evidence in cited ticket contracts."""
    runtime_hits = find_runtime_paths(changed_files)

    if not runtime_hits:
        return DeployGateResult(
            passed=True,
            skipped=True,
            message="No runtime paths touched — deploy gate skipped.",
        )

    metadata = parse_evidence_metadata(pr_body)
    if metadata.source and not metadata.ticket:
        return DeployGateResult(
            passed=False,
            runtime_paths_hit=runtime_hits,
            message=(
                "DEPLOY GATE FAILED: PR body has Evidence-Source but is missing "
                "Evidence-Ticket: OMN-XXXX. Add Evidence-Ticket so deploy-gate "
                "can validate the contract at the pinned OCC source."
            ),
        )

    # Extract cited ticket IDs from PR body
    if metadata.source and metadata.ticket:
        ticket_ids = [metadata.ticket]
    else:
        ticket_ids = [f"OMN-{m}" for m in TICKET_PATTERN.findall(pr_body)]

    if not ticket_ids:
        return DeployGateResult(
            passed=False,
            runtime_paths_hit=runtime_hits,
            message=(
                "DEPLOY GATE FAILED: PR touches runtime paths but cites no OMN-XXXX ticket. "
                f"Runtime paths: {runtime_hits}. "
                f"{DEPLOY_EVIDENCE_GUIDANCE} "
                "See OMN-8912, OMN-9685, OMN-11423, and OMN-14505."
            ),
        )

    # Check each cited ticket for deploy evidence
    tickets_checked: list[str] = []
    for ticket_id in ticket_ids:
        contract_path = contracts_dir / f"{ticket_id}.yaml"
        tickets_checked.append(ticket_id)
        if has_deploy_evidence(contract_path):
            return DeployGateResult(
                passed=True,
                runtime_paths_hit=runtime_hits,
                tickets_checked=tickets_checked,
                message=(
                    f"DEPLOY GATE PASSED: {ticket_id} has deploy evidence. "
                    f"Runtime paths: {runtime_hits}."
                ),
            )

    # No ticket had deploy evidence
    missing = [t for t in ticket_ids if not (contracts_dir / f"{t}.yaml").exists()]
    no_deploy = [
        t
        for t in ticket_ids
        if (contracts_dir / f"{t}.yaml").exists()
        and not has_deploy_evidence(contracts_dir / f"{t}.yaml")
    ]

    parts: list[str] = [
        "DEPLOY GATE FAILED: PR touches runtime paths but no cited ticket has deploy DoD evidence.",
        f"Runtime paths: {runtime_hits}.",
    ]
    if missing:
        parts.append(
            f"Tickets with no contract file in onex_change_control/contracts/: {missing}. "
            "Create the contract YAML in the onex_change_control repo, not in the caller repo."
        )
    if no_deploy:
        parts.append(
            f"Tickets found but declaring no falsifiable deploy probe: {no_deploy}."
        )
        for ticket_id in no_deploy:
            for item_id, value in iter_check_values(
                contracts_dir / f"{ticket_id}.yaml"
            ):
                verdict = classify_check_value(value)
                if not verdict.falsifiable and _legacy_has_deploy_keyword(value):
                    parts.append(
                        f"  {ticket_id} [{item_id}] REJECTED — {verdict.reason}"
                    )
    parts.append(DEPLOY_EVIDENCE_GUIDANCE)
    parts.append(
        "Root cause: OMN-8841 (deploy-agent inactive 2 days post-Dockerfile change). "
        "Gate: OMN-8912. Contract source fix: OMN-11423. "
        "Falsifiability fix: OMN-14505."
    )

    return DeployGateResult(
        passed=False,
        runtime_paths_hit=runtime_hits,
        tickets_checked=tickets_checked,
        message=" ".join(parts),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wave D: validate that runtime-change PRs have deploy evidence.",
    )
    parser.add_argument(
        "--changed-files",
        required=True,
        help="Space-separated list of changed file paths (from gh pr diff --name-only)",
    )
    parser.add_argument(
        "--pr-body",
        required=True,
        help="Full PR description text",
    )
    parser.add_argument(
        "--contracts-dir",
        default="contracts",
        help="Directory containing OMN-XXXX.yaml ticket contracts (default: contracts/)",
    )
    parser.add_argument(
        "--resolve-occ-ref",
        action="store_true",
        help=(
            "Resolve deploy-gate Evidence-Source metadata to an OCC checkout ref "
            "and exit without validating contracts."
        ),
    )
    parser.add_argument(
        "--default-occ-ref",
        default=DEFAULT_OCC_REF,
        help="Fallback OCC ref when no Evidence-Source is present (default: dev).",
    )
    parser.add_argument(
        "--github-output",
        default="",
        help="Optional path to append GitHub Actions output values.",
    )

    args = parser.parse_args(argv)
    changed = [f for f in args.changed_files.split() if f]
    contracts_dir = Path(args.contracts_dir)

    if args.resolve_occ_ref:
        resolution = resolve_occ_evidence_source(
            changed_files=changed,
            pr_body=args.pr_body,
            default_occ_ref=args.default_occ_ref,
        )
        if args.github_output:
            with Path(args.github_output).open("a", encoding="utf-8") as fh:
                fh.write(f"occ_ref={resolution.occ_ref}\n")
                fh.write(
                    "deploy_gate_required="
                    f"{str(resolution.deploy_gate_required).lower()}\n"
                )
                fh.write(f"occ_source_kind={resolution.source_kind}\n")
                if resolution.evidence_ticket:
                    fh.write(f"evidence_ticket={resolution.evidence_ticket}\n")
        if resolution.passed:
            print(f"::notice::{resolution.message}")
        else:
            print(f"::error::{resolution.message}")
        return 0 if resolution.passed else 1

    result = validate_pr_deploy_gate(
        changed_files=changed,
        pr_body=args.pr_body,
        contracts_dir=contracts_dir,
    )

    if result.passed:
        print(f"::notice::{result.message}")
    else:
        print(f"::error::{result.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
