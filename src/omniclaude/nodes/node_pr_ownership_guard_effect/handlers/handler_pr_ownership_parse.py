# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read the guarded GitHub mutations out of a Bash command (OMN-16485, OMN-20685).

Every concurrent lane on a host drives GitHub through one shared ``gh`` identity, so
the command text is the only attribution there is. This is the parser half of the
lane-ownership gate: it tokenises a command tracking which words were quoted, so
a commit message that names ``gh pr close`` is never read as the command, and
resolves each guarded verb to the claim key it must be judged by. It performs no
I/O.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from omniclaude.nodes.node_pr_ownership_guard_effect.enums import EnumPrMutationClass

#: Namespace prefixes keep run/dispatch keys from colliding with PR keys in the
#: shared claims directory.  PR keys are unprefixed so they stay byte-identical
#: to the canonical form ``pr_claim_registry.canonical_pr_key`` already emits.
RUN_KEY_PREFIX = "run:"
DISPATCH_KEY_PREFIX = "dispatch:"

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


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class PrMutation(NamedTuple):
    """One destructive GitHub mutation, resolved to the claim key it is judged by.

    A tuple, not a model: parsing is the whole cost of a command that holds no
    guarded verb, and a pydantic import would be paid on every ``gh api`` read.
    """

    verb: str  # pr-close, pr-reopen, api-pr-close, run-cancel, workflow-dispatch
    mutation_class: EnumPrMutationClass
    target_key: str | None  # None when the target could not be resolved
    detail: str  # what a refusal message calls the target
    unresolved_reason: str | None = None  # why target_key is None


class _Token(NamedTuple):
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
) -> PrMutation:
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
        return PrMutation(
            verb=verb,
            mutation_class=EnumPrMutationClass.OWNERSHIP,
            target_key=None,
            detail=" ".join(words[:4]),
            unresolved_reason="PR number could not be parsed from the command",
        )
    if repo_pair is None:
        return PrMutation(
            verb=verb,
            mutation_class=EnumPrMutationClass.OWNERSHIP,
            target_key=None,
            detail=" ".join(words[:4]),
            unresolved_reason=(
                "target repository is unresolvable — pass --repo <owner>/<repo>"
            ),
        )

    org, repo = repo_pair
    return PrMutation(
        verb=verb,
        mutation_class=EnumPrMutationClass.OWNERSHIP,
        target_key=canonical_pr_key(org, repo, number),
        detail=f"{org}/{repo}#{number}",
    )


def _parse_api_mutation(
    words: list[str], default_repo: str | None
) -> PrMutation | None:
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
            return PrMutation(
                verb="api-pr-close",
                mutation_class=EnumPrMutationClass.OWNERSHIP,
                target_key=None,
                detail=joined[:120],
                unresolved_reason="repository in the API path is a shell variable",
            )
        org, repo = resolved

    return PrMutation(
        verb="api-pr-close",
        mutation_class=EnumPrMutationClass.OWNERSHIP,
        target_key=canonical_pr_key(org, repo, number),
        detail=f"{org}/{repo}#{number} (via gh api)",
    )


def _parse_run_cancel(words: list[str], default_repo: str | None) -> PrMutation:
    positionals = _positionals(words, skip=3)
    repo_pair = _parse_repo(_flag_value(words, "--repo", "-R")) or _parse_repo(
        default_repo
    )
    run_id = next((word for word in positionals if word.isdigit()), None)

    if run_id is None or repo_pair is None:
        return PrMutation(
            verb="run-cancel",
            mutation_class=EnumPrMutationClass.EXCLUSIVITY,
            target_key=None,
            detail=" ".join(words[:4]),
            unresolved_reason="run id or repository could not be resolved",
        )

    org, repo = repo_pair
    return PrMutation(
        verb="run-cancel",
        mutation_class=EnumPrMutationClass.EXCLUSIVITY,
        target_key=f"{RUN_KEY_PREFIX}{org.lower()}/{repo.lower()}#{run_id}",
        detail=f"run {run_id} in {org}/{repo}",
    )


def _parse_workflow_dispatch(words: list[str], default_repo: str | None) -> PrMutation:
    positionals = _positionals(words, skip=3)
    repo_pair = _parse_repo(_flag_value(words, "--repo", "-R")) or _parse_repo(
        default_repo
    )
    ref = _flag_value(words, "--ref", "-r") or "default"
    workflow = positionals[0] if positionals else None

    if workflow is None or repo_pair is None:
        return PrMutation(
            verb="workflow-dispatch",
            mutation_class=EnumPrMutationClass.EXCLUSIVITY,
            target_key=None,
            detail=" ".join(words[:4]),
            unresolved_reason="workflow name or repository could not be resolved",
        )

    org, repo = repo_pair
    key = f"{DISPATCH_KEY_PREFIX}{org.lower()}/{repo.lower()}#{workflow}@{ref}"
    return PrMutation(
        verb="workflow-dispatch",
        mutation_class=EnumPrMutationClass.EXCLUSIVITY,
        target_key=key,
        detail=f"{workflow}@{ref} in {org}/{repo}",
    )


def parse_mutations(command: str, default_repo: str | None = None) -> list[PrMutation]:
    """Extract every guarded GitHub mutation from a Bash command string.

    ``default_repo`` is the repository implied by the caller's working
    directory, used only when the command omits ``--repo``.
    """
    mutations: list[PrMutation] = []

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

__all__ = [
    "DISPATCH_KEY_PREFIX",
    "RUN_KEY_PREFIX",
    "canonical_pr_key",
    "parse_mutations",
]
