#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pre-mutation lane-ownership gate for destructive ``gh`` verbs (OMN-16485).

Every concurrent lane on this host drives GitHub through ONE shared ``gh``
identity, so ``timeline.actor.login`` is the same account for every lane and
per-command attribution is structurally INDETERMINATE.  Nothing mechanically
stopped a lane from closing a peer lane's PR — observed >=5 times in 48h
(omniclaude#2019 was authored by ``andywu42`` and closed by ``jonahgabriel``),
plus a duplicate concurrent ``workflow_dispatch`` fired ~19s after a peer's.

This module is the pure decision core.  It answers one question:

    "Given this Bash command, may THIS lane perform the GitHub mutation it
     contains?"

It performs NO network I/O.  Ownership resolves entirely from the local
``pr_claim_registry`` claims directory plus a locally-resolvable lane identity,
so it is safe to run in the ``PreToolUse`` hot path.

Net-negative design (OMN-15483 precedent): this extends the claim vocabulary
that ALREADY ships in ``pr_claim_registry`` rather than inventing a second one.
That registry shipped with zero production callers and zero tests; this is what
wires it as a gate instead of a suggestion (Operating Rule #5).

Two mutation classes, deliberately different verdicts:

``ownership`` — ``gh pr close`` / ``gh pr reopen`` / ``gh api -X PATCH
    .../pulls/<n>`` carrying ``state=closed``.  Destroys a peer lane's work.
    FAIL-CLOSED: an absent, expired, unreadable, or lane-less claim REFUSES the
    mutation.  "Nobody claimed it" is never read as "therefore anyone may."
    The refusal names the one command that records the claim, so the escape
    hatch IS the act of producing the missing attribution record.

``exclusivity`` — ``gh workflow run`` / ``gh run cancel``.  The hazard is a
    duplicate concurrent actor, not destruction of an owned artifact, so the
    rule is first-writer-wins: an active peer claim refuses; otherwise the
    mutation is allowed AND the claim is recorded, which is what makes the
    second, racing lane refuse.

Fail-open boundary (explicit, not accidental): this module fails CLOSED on
every ownership question it can pose.  Its shell wrapper fails CLOSED when this
module errors on a command that matched a mutation verb, and never runs at all
for commands that contain no mutation verb — so a guard bug cannot brick
unrelated Bash traffic.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

MutationClass = Literal["ownership", "exclusivity"]
ClaimStatus = Literal["absent", "active", "expired", "unreadable"]

#: Namespace prefixes keep run/dispatch keys from colliding with PR keys in the
#: shared claims directory.  PR keys are unprefixed so they stay byte-identical
#: to the canonical form ``pr_claim_registry.canonical_pr_key`` already emits.
RUN_KEY_PREFIX = "run:"
DISPATCH_KEY_PREFIX = "dispatch:"

_LANE_ENV_VARS = (
    "ONEX_LANE_ID",
    "ONEX_AGENT_NAME",
    "CLAUDE_AGENT_NAME",
    "CLAUDE_SUBAGENT_NAME",
)

_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})

#: Tokens that may precede the real command word (``env FOO=1 gh pr close ...``).
_LEADING_NOISE = frozenset({"env", "command", "nohup", "time"})

_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<org>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?$"
)
_REPO_URL_RE = re.compile(
    r"^https?://github\.com/(?P<org>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
_OWNER_REPO_RE = re.compile(r"^(?P<org>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+)$")
_API_PULLS_RE = re.compile(
    r"repos/(?P<org>[^/]+)/(?P<repo>[^/]+)/pulls/(?P<number>\d+)"
)
_LANE_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._:@/-]+")


@dataclass(frozen=True)
class Mutation:
    """One destructive GitHub mutation extracted from a Bash command."""

    verb: str
    mutation_class: MutationClass
    target_key: str | None
    detail: str
    #: Populated when the target could not be resolved, for the refusal message.
    unresolved_reason: str | None = None


@dataclass(frozen=True)
class Decision:
    """The verdict for a single mutation."""

    allowed: bool
    reason_code: str
    message: str
    verb: str
    target_key: str | None
    #: True when the caller should record a claim before letting the command run.
    record_claim: bool = False


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    text: str
    quoted: bool


def _tokenize(command: str) -> list[_Token]:
    """Split a Bash command into tokens, tracking whether each was quoted.

    Quote tracking is the whole point: a commit message containing the literal
    text ``gh pr close`` must NOT be read as a mutation.  ``shlex.split`` throws
    that information away, so it cannot be used here.
    """
    tokens: list[_Token] = []
    buf: list[str] = []
    saw_quote = False
    quote_char: str | None = None
    index = 0
    length = len(command)

    def flush() -> None:
        nonlocal buf, saw_quote
        if buf or saw_quote:
            tokens.append(_Token("".join(buf), saw_quote))
        buf = []
        saw_quote = False

    while index < length:
        char = command[index]

        if quote_char is not None:
            if char == "\\" and quote_char == '"' and index + 1 < length:
                buf.append(command[index + 1])
                index += 2
                continue
            if char == quote_char:
                quote_char = None
                index += 1
                continue
            buf.append(char)
            index += 1
            continue

        if char in ("'", '"'):
            quote_char = char
            saw_quote = True
            index += 1
            continue

        if char == "\\" and index + 1 < length:
            nxt = command[index + 1]
            if nxt == "\n":
                index += 2
                continue
            buf.append(nxt)
            index += 2
            continue

        if char == "\n":
            flush()
            tokens.append(_Token("\n", False))
            index += 1
            continue

        if char.isspace():
            flush()
            index += 1
            continue

        if command[index : index + 2] in ("&&", "||"):
            flush()
            tokens.append(_Token(command[index : index + 2], False))
            index += 2
            continue

        if char in ";|&":
            flush()
            tokens.append(_Token(char, False))
            index += 1
            continue

        buf.append(char)
        index += 1

    flush()
    return tokens


def _segments(command: str) -> list[list[_Token]]:
    """Split tokens into individual command segments on unquoted separators."""
    result: list[list[_Token]] = []
    current: list[_Token] = []
    for token in _tokenize(command):
        if not token.quoted and token.text in _SEPARATORS:
            if current:
                result.append(current)
            current = []
            continue
        current.append(token)
    if current:
        result.append(current)
    return result


def _strip_leading_noise(segment: list[_Token]) -> list[_Token]:
    """Drop ``env``/``VAR=value`` style prefixes so ``gh`` is at index 0."""
    index = 0
    while index < len(segment):
        text = segment[index].text
        if _ASSIGNMENT_RE.match(text) or text in _LEADING_NOISE:
            index += 1
            continue
        break
    return segment[index:]


# ---------------------------------------------------------------------------
# Argument extraction
# ---------------------------------------------------------------------------


def _flag_value(words: list[str], *names: str) -> str | None:
    """Return the value of ``--name value`` or ``--name=value``."""
    for position, word in enumerate(words):
        for name in names:
            if word == name and position + 1 < len(words):
                return words[position + 1]
            prefix = f"{name}="
            if word.startswith(prefix):
                return word[len(prefix) :]
    return None


def _positionals(words: list[str], *, skip: int) -> list[str]:
    """Return non-flag arguments after ``skip`` leading words.

    Values consumed by a preceding ``--flag`` are excluded so that
    ``gh pr close --repo O/R 123`` yields ``["123"]`` and not ``["O/R", "123"]``.
    """
    result: list[str] = []
    index = skip
    while index < len(words):
        word = words[index]
        if word.startswith("-"):
            # A bare `--flag` consumes the next word unless it used `--flag=value`.
            if (
                "=" not in word
                and index + 1 < len(words)
                and not words[index + 1].startswith("-")
            ):
                index += 2
                continue
            index += 1
            continue
        result.append(word)
        index += 1
    return result


def _parse_repo(raw: str | None) -> tuple[str, str] | None:
    """Parse ``owner/repo`` or a GitHub URL into ``(org, repo)``."""
    if not raw:
        return None
    candidate = raw.strip()
    url_match = _REPO_URL_RE.match(candidate)
    if url_match:
        return url_match.group("org"), url_match.group("repo")
    owner_match = _OWNER_REPO_RE.match(candidate)
    if owner_match:
        return owner_match.group("org"), owner_match.group("repo")
    return None


def canonical_pr_key(org: str, repo: str, number: int | str) -> str:
    """Canonical PR key — identical to ``pr_claim_registry.canonical_pr_key``.

    Duplicated as a one-liner rather than imported so this decision core stays
    importable (and unit-testable) without the registry's state-dir machinery.
    The shared format is asserted by test, not by convention.
    """
    return f"{org.lower()}/{repo.lower()}#{number}"


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------


def _parse_pr_mutation(
    words: list[str], verb: str, default_repo: str | None
) -> Mutation:
    positionals = _positionals(words, skip=3)
    repo_pair = _parse_repo(_flag_value(words, "--repo", "-R"))
    number: str | None = None

    for candidate in positionals:
        url_match = _PR_URL_RE.match(candidate)
        if url_match:
            repo_pair = (url_match.group("org"), url_match.group("repo"))
            number = url_match.group("number")
            break
        if candidate.isdigit():
            number = candidate
            break

    if repo_pair is None:
        repo_pair = _parse_repo(default_repo)

    if number is None:
        return Mutation(
            verb=verb,
            mutation_class="ownership",
            target_key=None,
            detail=" ".join(words[:4]),
            unresolved_reason="PR number could not be parsed from the command",
        )
    if repo_pair is None:
        return Mutation(
            verb=verb,
            mutation_class="ownership",
            target_key=None,
            detail=" ".join(words[:4]),
            unresolved_reason=(
                "target repository is unresolvable — pass --repo <owner>/<repo>"
            ),
        )

    org, repo = repo_pair
    return Mutation(
        verb=verb,
        mutation_class="ownership",
        target_key=canonical_pr_key(org, repo, number),
        detail=f"{org}/{repo}#{number}",
    )


def _parse_api_mutation(words: list[str], default_repo: str | None) -> Mutation | None:
    method = (_flag_value(words, "-X", "--method") or "GET").upper()
    if method not in {"PATCH", "POST", "PUT", "DELETE"}:
        return None

    joined = " ".join(words)
    pulls_match = _API_PULLS_RE.search(joined)
    if pulls_match is None:
        return None

    # Only a state=closed edit destroys a peer's work; a label or body PATCH does not.
    if not re.search(r"state=[\"']?closed", joined):
        return None

    org = pulls_match.group("org")
    repo = pulls_match.group("repo")
    number = pulls_match.group("number")
    if org.startswith("$") or repo.startswith("$"):
        resolved = _parse_repo(default_repo)
        if resolved is None:
            return Mutation(
                verb="api-pr-close",
                mutation_class="ownership",
                target_key=None,
                detail=joined[:120],
                unresolved_reason="repository in the API path is a shell variable",
            )
        org, repo = resolved

    return Mutation(
        verb="api-pr-close",
        mutation_class="ownership",
        target_key=canonical_pr_key(org, repo, number),
        detail=f"{org}/{repo}#{number} (via gh api)",
    )


def _parse_run_cancel(words: list[str], default_repo: str | None) -> Mutation:
    positionals = _positionals(words, skip=3)
    repo_pair = _parse_repo(_flag_value(words, "--repo", "-R")) or _parse_repo(
        default_repo
    )
    run_id = next((word for word in positionals if word.isdigit()), None)

    if run_id is None or repo_pair is None:
        return Mutation(
            verb="run-cancel",
            mutation_class="exclusivity",
            target_key=None,
            detail=" ".join(words[:4]),
            unresolved_reason="run id or repository could not be resolved",
        )

    org, repo = repo_pair
    return Mutation(
        verb="run-cancel",
        mutation_class="exclusivity",
        target_key=f"{RUN_KEY_PREFIX}{org.lower()}/{repo.lower()}#{run_id}",
        detail=f"run {run_id} in {org}/{repo}",
    )


def _parse_workflow_dispatch(words: list[str], default_repo: str | None) -> Mutation:
    positionals = _positionals(words, skip=3)
    repo_pair = _parse_repo(_flag_value(words, "--repo", "-R")) or _parse_repo(
        default_repo
    )
    ref = _flag_value(words, "--ref", "-r") or "default"
    workflow = positionals[0] if positionals else None

    if workflow is None or repo_pair is None:
        return Mutation(
            verb="workflow-dispatch",
            mutation_class="exclusivity",
            target_key=None,
            detail=" ".join(words[:4]),
            unresolved_reason="workflow name or repository could not be resolved",
        )

    org, repo = repo_pair
    key = f"{DISPATCH_KEY_PREFIX}{org.lower()}/{repo.lower()}#{workflow}@{ref}"
    return Mutation(
        verb="workflow-dispatch",
        mutation_class="exclusivity",
        target_key=key,
        detail=f"{workflow}@{ref} in {org}/{repo}",
    )


def parse_mutations(command: str, default_repo: str | None = None) -> list[Mutation]:
    """Extract every guarded GitHub mutation from a Bash command string.

    ``default_repo`` is the repository implied by the caller's working
    directory, used only when the command omits ``--repo``.
    """
    mutations: list[Mutation] = []

    for segment in _segments(command):
        stripped = _strip_leading_noise(segment)
        if not stripped:
            continue
        head = stripped[0]
        if head.quoted or head.text != "gh":
            continue

        words = [token.text for token in stripped]
        if len(words) < 3:
            continue

        noun, verb = words[1], words[2]

        if noun == "pr" and verb in ("close", "reopen"):
            mutations.append(_parse_pr_mutation(words, f"pr-{verb}", default_repo))
        elif noun == "run" and verb == "cancel":
            mutations.append(_parse_run_cancel(words, default_repo))
        elif noun == "workflow" and verb == "run":
            mutations.append(_parse_workflow_dispatch(words, default_repo))
        elif noun == "api":
            api_mutation = _parse_api_mutation(words, default_repo)
            if api_mutation is not None:
                mutations.append(api_mutation)

    return mutations


# ---------------------------------------------------------------------------
# Lane identity
# ---------------------------------------------------------------------------


def _sanitize_lane(raw: str) -> str:
    return _LANE_SANITIZE_RE.sub("-", raw.strip())[:96]


def resolve_lane_id(
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> str | None:
    """Resolve this lane's identity, deterministically and without network I/O.

    Resolution order, most explicit first:

    1. ``ONEX_LANE_ID`` (or an agent-name env var) — an explicitly declared lane.
    2. The worktree the caller is standing in (``<ticket>/<repo>``).  Per
       Operating Rule #9 every lane gets its own worktree, so this is a real
       per-lane discriminator, not a guess.
    3. ``CLAUDE_CODE_SESSION_ID`` — a stable per-session fallback.

    Returns ``None`` when nothing is resolvable, which every caller must treat
    as INDETERMINATE and therefore refusing.

    Two lanes sharing one worktree collapse to a single id.  That is a
    deliberate under-block: it can permit a mutation between co-located lanes,
    but it never blocks an unrelated lane's own work.
    """
    environment = dict(os.environ) if env is None else env

    for name in _LANE_ENV_VARS:
        value = environment.get(name, "").strip()
        if value:
            return _sanitize_lane(value)

    worktree_lane = _lane_from_worktree(environment, cwd)
    if worktree_lane:
        return worktree_lane

    session = environment.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if session:
        return _sanitize_lane(f"session:{session[:16]}")

    return None


def _lane_from_worktree(
    environment: dict[str, str], cwd: str | Path | None
) -> str | None:
    raw_cwd = Path(cwd) if cwd is not None else Path(environment.get("PWD", "") or ".")
    try:
        resolved = raw_cwd.resolve()
    except OSError:
        return None

    roots: list[Path] = []
    for name in ("ONEX_WORKTREES_ROOT", "OMNI_WORKTREES_DIR"):
        value = environment.get(name, "").strip()
        if value:
            roots.append(Path(value))
    omni_home = environment.get("OMNI_HOME", "").strip()
    if omni_home:
        roots.append(Path(omni_home) / "omni_worktrees")

    for root in roots:
        try:
            relative = resolved.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        parts = relative.parts
        if len(parts) >= 2:
            return _sanitize_lane(f"wt:{parts[0]}/{parts[1]}")
        if len(parts) == 1:
            return _sanitize_lane(f"wt:{parts[0]}")

    return None


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _claim_command(target_key: str) -> str:
    return (
        "python3 omniclaude/scripts/pr_claim_registry_cli.py claim "
        f"'{target_key}' --action close"
    )


def decide(
    mutation: Mutation,
    lane_id: str | None,
    claim_status: ClaimStatus,
    claim_lane: str | None,
) -> Decision:
    """Return the verdict for one mutation. Pure; no I/O."""
    verb = mutation.verb
    target = mutation.target_key

    if lane_id is None:
        return Decision(
            allowed=False,
            reason_code="INDETERMINATE_LANE",
            verb=verb,
            target_key=target,
            message=(
                f"REFUSED ({verb}): this lane has no resolvable identity, so the "
                "mutation cannot be attributed. Attribution that cannot be "
                "established fails closed — it is never assumed. Export "
                "ONEX_LANE_ID=<your-lane-handle> (the handle you registered in "
                "the rolling work ledger) and retry."
            ),
        )

    if target is None:
        reason = mutation.unresolved_reason or "target could not be resolved"
        return Decision(
            allowed=False,
            reason_code="INDETERMINATE_TARGET",
            verb=verb,
            target_key=None,
            message=(
                f"REFUSED ({verb}): {reason}. Ownership cannot be checked against "
                "an unresolved target, so this fails closed. Re-run with an "
                "explicit --repo <owner>/<repo> and an explicit id."
            ),
        )

    if claim_status == "unreadable":
        return Decision(
            allowed=False,
            reason_code="INDETERMINATE_CLAIM",
            verb=verb,
            target_key=target,
            message=(
                f"REFUSED ({verb}) on {mutation.detail}: the ownership claim for "
                f"'{target}' exists but is unreadable or malformed. An "
                "unreadable claim is INDETERMINATE, not absent, and fails closed. "
                "Inspect it with: python3 omniclaude/scripts/pr_claim_registry_cli.py list"
            ),
        )

    if claim_status == "active":
        if claim_lane is None:
            return Decision(
                allowed=False,
                reason_code="INDETERMINATE_CLAIM",
                verb=verb,
                target_key=target,
                message=(
                    f"REFUSED ({verb}) on {mutation.detail}: an active claim exists "
                    f"on '{target}' but it records no lane, so it cannot prove this "
                    "lane owns the work. Re-claim it with: " + _claim_command(target)
                ),
            )
        if claim_lane != lane_id:
            return Decision(
                allowed=False,
                reason_code="CROSS_LANE",
                verb=verb,
                target_key=target,
                message=(
                    f"REFUSED ({verb}) on {mutation.detail}: owned by lane "
                    f"'{claim_lane}', and you are lane '{lane_id}'. A lane may not "
                    "mutate a peer lane's work. Coordinate with that lane in the "
                    "rolling work ledger; if it is finished, it releases the claim "
                    "with: python3 omniclaude/scripts/pr_claim_registry_cli.py "
                    f"release '{target}' <run-id>"
                ),
            )
        return Decision(
            allowed=True,
            reason_code="OWNED_BY_SELF",
            verb=verb,
            target_key=target,
            message=f"allowed: lane '{lane_id}' holds an active claim on {target}",
        )

    # claim_status is "absent" or "expired" from here on.
    if mutation.mutation_class == "exclusivity":
        return Decision(
            allowed=True,
            reason_code="FIRST_WRITER",
            verb=verb,
            target_key=target,
            record_claim=True,
            message=(
                f"allowed: lane '{lane_id}' is the first writer for {target}; "
                "claim recorded so a racing peer refuses"
            ),
        )

    return Decision(
        allowed=False,
        reason_code="UNCLAIMED",
        verb=verb,
        target_key=target,
        message=(
            f"REFUSED ({verb}) on {mutation.detail}: no lane holds a claim on "
            f"'{target}', so this close cannot be attributed to any lane. An "
            "unclaimed target is INDETERMINATE, not free — >=5 green PRs were "
            "closed unmerged this way in 48h under the shared gh identity "
            "(OMN-16485). If this work is yours, record ownership first:\n"
            f"    {_claim_command(target)}\n"
            "Recording the claim IS the attribution record that is otherwise "
            "missing; it is not a formality to route around."
        ),
    )


# ---------------------------------------------------------------------------
# Registry-backed evaluation
# ---------------------------------------------------------------------------


def _read_claim(claims_dir: Path, target_key: str) -> tuple[ClaimStatus, str | None]:
    """Read a claim, distinguishing absent from unreadable (fail-closed input)."""
    from plugins.onex.hooks.lib.pr_claim_registry import filesystem_key, is_active

    claim_file = claims_dir / f"{filesystem_key(target_key)}.json"
    if not claim_file.exists():
        return "absent", None
    try:
        data = json.loads(claim_file.read_text())
    except (json.JSONDecodeError, OSError):
        return "unreadable", None
    if not isinstance(data, dict):
        return "unreadable", None

    lane = data.get("lane_id")
    lane_value = lane if isinstance(lane, str) and lane.strip() else None
    try:
        active = is_active(data)
    except (TypeError, ValueError):
        return "unreadable", lane_value
    return ("active" if active else "expired"), lane_value


def evaluate_command(
    command: str,
    *,
    claims_dir: Path,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    default_repo: str | None = None,
) -> list[Decision]:
    """Evaluate every guarded mutation in ``command``.

    Returns one :class:`Decision` per detected mutation; an empty list means the
    command contains nothing this guard governs.
    """
    mutations = parse_mutations(command, default_repo=default_repo)
    if not mutations:
        return []

    lane_id = resolve_lane_id(env=env, cwd=cwd)
    decisions: list[Decision] = []
    for mutation in mutations:
        if mutation.target_key is None:
            decisions.append(decide(mutation, lane_id, "absent", None))
            continue
        status, claim_lane = _read_claim(claims_dir, mutation.target_key)
        decisions.append(decide(mutation, lane_id, status, claim_lane))
    return decisions


# ---------------------------------------------------------------------------
# CLI (invoked by the PreToolUse shell wrapper)
# ---------------------------------------------------------------------------

EXIT_ALLOW = 0
EXIT_BLOCK = 3
EXIT_ERROR = 1


def main(argv: list[str] | None = None) -> int:
    """Evaluate a command file and print a JSON verdict.

    Exit codes: 0 allow, 3 block, 1 internal error (the wrapper treats an
    internal error on a verb-matching command as a block).
    """
    parser = argparse.ArgumentParser(description="Lane-ownership gate for gh mutations")
    parser.add_argument(
        "--command-file", required=True, help="File holding the Bash command"
    )
    parser.add_argument(
        "--default-repo", default=None, help="owner/repo implied by the cwd"
    )
    parser.add_argument("--cwd", default=None, help="Caller working directory")
    args = parser.parse_args(argv)

    command = Path(args.command_file).read_text()

    from plugins.onex.hooks.lib.pr_claim_registry import get_registry

    registry = get_registry()
    claims_dir = registry._claims_dir  # noqa: SLF001 — same-package accessor

    decisions = evaluate_command(
        command,
        claims_dir=claims_dir,
        cwd=args.cwd,
        default_repo=args.default_repo,
    )

    blocked = [decision for decision in decisions if not decision.allowed]
    payload = {
        "blocked": bool(blocked),
        "decisions": [
            {
                "allowed": decision.allowed,
                "reason_code": decision.reason_code,
                "verb": decision.verb,
                "target_key": decision.target_key,
                "message": decision.message,
            }
            for decision in decisions
        ],
        "reason": "\n\n".join(decision.message for decision in blocked),
    }
    print(json.dumps(payload))

    if blocked:
        return EXIT_BLOCK

    # Record claims for allowed first-writer (exclusivity) mutations so the next
    # racing lane sees a live claim rather than an empty registry.
    from plugins.onex.hooks.lib.session_id import resolve_session_id

    lane_id = resolve_lane_id(cwd=args.cwd)
    for decision in decisions:
        if decision.record_claim and decision.target_key and lane_id:
            registry.acquire(
                pr_key=decision.target_key,
                run_id=resolve_session_id(default=lane_id),
                action=decision.verb,
                lane_id=lane_id,
            )

    return EXIT_ALLOW


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - wrapper converts this to a block
        print(json.dumps({"blocked": True, "error": str(exc)}), file=sys.stderr)
        sys.exit(EXIT_ERROR)
