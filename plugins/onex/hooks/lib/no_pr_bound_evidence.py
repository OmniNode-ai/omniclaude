# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Repo-owned Done evidence and acceptance-criteria readers.

A merged product PR must carry ``contracts/<TICKET>.yaml`` binding every
labelled acceptance criterion and a green ``repo-evidence / dod-verify`` check
on the head verifying the same contract that merged. Of several merged PRs
carrying a repository's contract, the newest merged one decides. Missing repo
evidence is reported as NOT_ENGAGED; the Done guard refuses it.

The criterion reader and label canonicaliser mirror the evidence closer in
omnibase_infra. Keep their parsing semantics aligned. GitHub reads are injected
and importing this module performs no network I/O.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote

from linear_done_verify import PRStatus, _gh_api_json

_RETIREMENT_FIELD = "supersedes_ac_binding"


# --------------------------------------------------------------------------- #
# Criterion reader, ported from the evidence closer (see module docstring).
# --------------------------------------------------------------------------- #

_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(.*)$")
_AC_ITEM_RE = re.compile(
    r"^[ \t]*([*_]*)[ \t]*(AC[-_ ]?\d+)(?!\d)[*_]*(.*?)[ \t]*$", re.IGNORECASE
)
_TRAILING_EMPHASIS_RE = re.compile(r"[*_]+$")
_TRAILING_QUALIFIER_RE = re.compile(r"\s*\([^)]*\)\s*$")
_TASK_MARKER_RE = re.compile(r"^\[[ \t xX]\][ \t]*")
_HEADING_ENUM_RE = re.compile(r"^\d+[.)]\s*")
_AC_HEADING_TEXTS = frozenset(
    {
        "acceptance criteria",
        "acceptance criteria (ac)",
        "acceptance criterion",
        "acceptance",
        "ac",
        "acs",
        "definition of done",
        "definition of done (dod)",
        "dod",
    }
)
_AC_HEADING_PHRASES = frozenset(t for t in _AC_HEADING_TEXTS if " " in t)
_AC_LABEL_RE = re.compile(
    r"^[\s>*_+-]*(?:\*\*)?\s*(AC|DOD)[-_ .]?(\d+)\b", re.IGNORECASE
)
_SUPERSEDED_QUALIFIER_RE = re.compile(
    r"^[ \t]*[(\[][^)\]]*\bsupersed(?:e|es|ed|ing)\b[^)\]]*[)\]]",
    re.IGNORECASE,
)


def _is_markdown_heading(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_ac_heading(line: str) -> bool:
    raw = line.strip()
    if not raw:
        return False
    looks_like_heading = raw.startswith("#") or (
        raw.startswith("**") and raw.endswith("**")
    )
    text = raw.lstrip("#").strip()
    text = text.strip("*_").strip()
    text = _HEADING_ENUM_RE.sub("", text)
    text = text.rstrip(":").strip()
    text = text.strip("*_").strip()
    folded = text.casefold()
    if folded in _AC_HEADING_TEXTS:
        return True
    trimmed = _TRAILING_QUALIFIER_RE.sub("", folded).strip().rstrip(":").strip()
    if trimmed in _AC_HEADING_TEXTS:
        return True
    return looks_like_heading and any(
        trimmed.endswith(f" {known}") for known in _AC_HEADING_PHRASES
    )


def acceptance_criteria_items(description: str) -> list[str]:
    """Items under an acceptance-criteria heading; the whole body if none."""
    items: list[str] = []
    saw_heading = any(_is_ac_heading(line) for line in description.splitlines())
    in_section = not saw_heading
    for line in description.splitlines():
        if _is_ac_heading(line):
            in_section = True
            continue
        if not in_section:
            continue
        if _is_markdown_heading(line) and saw_heading:
            break
        list_match = _LIST_ITEM_RE.match(line)
        if list_match:
            text = _TASK_MARKER_RE.sub("", list_match.group(1)).strip()
            if text:
                items.append(text)
            continue
        ac_match = _AC_ITEM_RE.match(line)
        if ac_match:
            lead, token, rest = ac_match.groups()
            text = f"{token}{rest}".strip()
            if lead:
                text = _TRAILING_EMPHASIS_RE.sub("", text).strip()
            if text:
                items.append(text)
    return items


def canonical_ac_label(text: str) -> str:
    """``AC3`` / ``DOD2`` from a criterion or a ``binds_ac`` entry, or ``""``."""
    match = _AC_LABEL_RE.match(text.strip())
    if not match:
        return ""
    return f"{match.group(1).upper()}{int(match.group(2))}"


def _declares_supersession(item: str) -> bool:
    text = item.strip()
    match = _AC_LABEL_RE.match(text)
    if not match:
        return False
    return _SUPERSEDED_QUALIFIER_RE.match(text[match.end() :]) is not None


def live_acceptance_criteria_items(description: str) -> list[str]:
    """:func:`acceptance_criteria_items` minus declarations a later one replaced."""
    items = acceptance_criteria_items(description)
    superseded_at = {i for i, item in enumerate(items) if _declares_supersession(item)}
    if not superseded_at:
        return items
    replaced_labels = {
        label
        for i, item in enumerate(items)
        if i not in superseded_at
        for label in (canonical_ac_label(item),)
        if label
    }
    return [
        item
        for i, item in enumerate(items)
        if not (i in superseded_at and canonical_ac_label(item) in replaced_labels)
    ]


# --------------------------------------------------------------------------- #
# Contract reading
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvidenceItem:
    """One ``dod_evidence`` entry: its id, the labels it binds, its check types."""

    item_id: str
    binds: frozenset[str]
    check_types: frozenset[str]


def _items(contract: dict[str, Any]) -> list[dict[str, Any]]:
    raw = contract.get("dod_evidence")
    return [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []


def _retired_pairs(contract: dict[str, Any]) -> set[tuple[str, str]]:
    """``(item id, label)`` pairs a well-formed ``supersedes_ac_binding`` retired.

    An entry naming no item, no label, no reason, or a label that item never bound takes no
    effect, so a typo cannot withdraw a real binding. Retirement only ever
    NARROWS what counts as bound.
    """
    claims = {
        str(item.get("id") or ""): {
            canonical_ac_label(str(x)) for x in (item.get("binds_ac") or [])
        }
        for item in _items(contract)
        if isinstance(item.get("binds_ac") or [], list)
    }
    retired: set[tuple[str, str]] = set()
    for item in _items(contract):
        entries = item.get(_RETIREMENT_FIELD)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            target = str(entry.get("item") or "")
            label = canonical_ac_label(str(entry.get("label") or ""))
            reason = str(entry.get("reason") or "").strip()
            if target and label and reason and label in claims.get(target, set()):
                retired.add((target, label))
    return retired


def evidence_items(contract: dict[str, Any]) -> list[EvidenceItem]:
    """Every ``dod_evidence`` item with its live ``binds_ac`` labels."""
    retired = _retired_pairs(contract)
    out: list[EvidenceItem] = []
    for item in _items(contract):
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            continue
        raw_binds = item.get("binds_ac") or []
        binds = (
            {
                label
                for label in (canonical_ac_label(str(x)) for x in raw_binds)
                if label and (item_id, label) not in retired
            }
            if isinstance(raw_binds, list)
            else set()
        )
        checks = item.get("checks") or []
        check_types = {
            str(c.get("check_type"))
            for c in (checks if isinstance(checks, list) else [])
            if isinstance(c, dict) and isinstance(c.get("check_type"), str)
        }
        out.append(EvidenceItem(item_id, frozenset(binds), frozenset(check_types)))
    return out


# --------------------------------------------------------------------------- #
# Repo-owned evidence: product contracts and verified PR heads.
# --------------------------------------------------------------------------- #

REPO_EVIDENCE_CHECK_NAME = "repo-evidence / dod-verify"
REPO_EVIDENCE_APP_SLUG = "github-actions"
CONTRACT_DIR = "contracts"


class RepoEvidenceOutcome(StrEnum):
    NOT_ENGAGED = "not_engaged"
    PASSED = "passed"
    REFUSED = "refused"


@dataclass(frozen=True)
class RepoEvidenceVerdict:
    outcome: RepoEvidenceOutcome
    detail: str

    @property
    def engaged(self) -> bool:
        return self.outcome is not RepoEvidenceOutcome.NOT_ENGAGED


class ContractReadStatus(StrEnum):
    FOUND = "found"
    ABSENT = "absent"
    ERROR = "error"


@dataclass(frozen=True)
class ContractRead:
    status: ContractReadStatus
    text: str = ""
    error: str = ""


# (repo "owner/name", ref sha, ticket_id).
ContractReader = Callable[[str, str, str], ContractRead]
# (repo, sha): named check runs on that sha, or None when unreadable.
CheckRunReader = Callable[[str, str], list[dict[str, Any]] | None]


def gh_read_contract(repo: str, ref: str, ticket_id: str) -> ContractRead:
    """Read the product contract at a fixed commit via GitHub REST."""
    data, error = _gh_api_json(
        f"repos/{repo}/contents/{CONTRACT_DIR}/{ticket_id}.yaml?ref={quote(ref, safe='')}",
        15,
    )
    if error is not None:
        if "HTTP 404" in error or "Not Found" in error:
            return ContractRead(ContractReadStatus.ABSENT)
        return ContractRead(ContractReadStatus.ERROR, error=error)
    if (
        not isinstance(data, dict)
        or data.get("encoding") != "base64"
        or not isinstance(data.get("content"), str)
    ):
        return ContractRead(
            ContractReadStatus.ERROR, error="malformed GitHub contract response"
        )
    try:
        content = "".join(data["content"].split())
        decoded = base64.b64decode(content, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError) as exc:
        return ContractRead(
            ContractReadStatus.ERROR, error=f"cannot decode contract: {exc}"
        )
    return ContractRead(ContractReadStatus.FOUND, text=decoded)


def gh_read_check_runs(repo: str, sha: str) -> list[dict[str, Any]] | None:
    """Read the latest named check runs at the PR head via GitHub REST."""
    data, error = _gh_api_json(
        f"repos/{repo}/commits/{sha}/check-runs?filter=latest&per_page=100"
        f"&check_name={quote(REPO_EVIDENCE_CHECK_NAME, safe='')}",
        15,
    )
    if error is not None or not isinstance(data, dict):
        return None
    runs = data.get("check_runs")
    if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
        return None
    return runs


def _parse_contract(
    read: ContractRead, ticket_id: str, source: str
) -> dict[str, Any] | RepoEvidenceVerdict:
    """Parse a contract, refusing unavailable YAML support or invalid data."""
    if read.status is not ContractReadStatus.FOUND:
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{source}: contracts/{ticket_id}.yaml is {read.status}"
            f" ({read.error or 'contract absent'}); restore readable evidence.",
        )
    try:
        import yaml
    except ImportError:
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{source}: PyYAML is unavailable; install it to read the contract.",
        )
    try:
        contract = yaml.safe_load(read.text)
    except yaml.YAMLError as exc:
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{source}: contracts/{ticket_id}.yaml is invalid YAML ({exc}); fix it.",
        )
    if not isinstance(contract, dict):
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{source}: contracts/{ticket_id}.yaml must be a mapping; fix it.",
        )
    if "ticket_id" in contract and contract["ticket_id"] != ticket_id:
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{source}: contract names ticket_id {contract['ticket_id']!r}, "
            f"not {ticket_id}; correct the ticket binding.",
        )
    return contract


def evaluate_repo_evidence(
    ticket_id: str,
    descriptions: Sequence[str],
    merged_prs: Sequence[PRStatus],
    *,
    read_contract: ContractReader = gh_read_contract,
    read_check_runs: CheckRunReader = gh_read_check_runs,
) -> RepoEvidenceVerdict:
    """Evaluate bindings and verified heads, with all I/O through readers."""
    candidates = {
        (pr.ref.repo, pr.ref.number): pr
        for pr in merged_prs
        if pr.state == "MERGED" and pr.ref.repo and pr.merge_commit_sha and pr.head_sha
    }
    if not candidates:
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.NOT_ENGAGED,
            "no merged product PR to read repo evidence from",
        )

    contracts: list[tuple[PRStatus, dict[str, Any]]] = []
    for (repo, number), pr in candidates.items():
        assert repo is not None
        read = read_contract(repo, pr.merge_commit_sha, ticket_id)
        if read.status is ContractReadStatus.ABSENT:
            continue
        contract = _parse_contract(
            read, ticket_id, f"{repo}#{number} at merge {pr.merge_commit_sha}"
        )
        if isinstance(contract, RepoEvidenceVerdict):
            return contract
        contracts.append((pr, contract))
    if not contracts:
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.NOT_ENGAGED,
            f"no merged product PR carries {CONTRACT_DIR}/{ticket_id}.yaml",
        )
    # The check verifies the whole contract at its PR head, so a later merged PR
    # of the same repository re-verifies everything an earlier one did: only the
    # newest decides there. A PR with no merge time is never proven superseded.
    newest: dict[str, str] = {}
    for pr, _contract in contracts:
        assert pr.ref.repo is not None
        repo = pr.ref.repo
        if pr.merged_at:
            newest[repo] = max(newest.get(repo, ""), pr.merged_at)
    contracts = [
        (pr, contract)
        for pr, contract in contracts
        if not pr.merged_at or pr.merged_at == newest[pr.ref.repo or ""]
    ]

    engaged: list[tuple[PRStatus, dict[str, Any], list[dict[str, Any]]]] = []
    skipped: list[str] = []
    for pr, contract in contracts:
        assert pr.ref.repo is not None
        repo = pr.ref.repo
        source = f"{repo}#{pr.ref.number}"
        runs = read_check_runs(repo, pr.head_sha)
        if runs is None:
            return RepoEvidenceVerdict(
                RepoEvidenceOutcome.REFUSED,
                f"{source} at head {pr.head_sha}: check runs unreadable; "
                "restore GitHub check-run access.",
            )
        kept = [
            r
            for r in runs
            if r.get("name") == REPO_EVIDENCE_CHECK_NAME
            and isinstance(r.get("app"), dict)
            and r["app"].get("slug") == REPO_EVIDENCE_APP_SLUG
        ]
        if not kept:
            skipped.append(
                f"{source} carries {CONTRACT_DIR}/{ticket_id}.yaml but no "
                f"{REPO_EVIDENCE_CHECK_NAME} run on head {pr.head_sha[:12]}"
            )
            continue
        engaged.append((pr, contract, kept))
    if not engaged:
        return RepoEvidenceVerdict(RepoEvidenceOutcome.NOT_ENGAGED, "; ".join(skipped))

    bindings: dict[str, list[str]] = {}
    sources: list[str] = []
    for pr, contract, kept in engaged:
        assert pr.ref.repo is not None
        repo = pr.ref.repo
        source = f"{repo}#{pr.ref.number}"
        context = f"{source} at head {pr.head_sha} and merge {pr.merge_commit_sha}"
        sources.append(context)
        # Check-run ids only grow, so the newest copy is the highest id: a rerun
        # still in progress has no completed_at and must not lose to an old success.
        newest = max(kept, key=lambda r: int(r.get("id") or 0))
        if newest.get("status") != "completed" or newest.get("conclusion") != "success":
            return RepoEvidenceVerdict(
                RepoEvidenceOutcome.REFUSED,
                f"{context}: {REPO_EVIDENCE_CHECK_NAME} run {newest.get('id')} "
                f"has status={newest.get('status')} and "
                f"conclusion={newest.get('conclusion')}; obtain a completed success.",
            )
        head_contract = _parse_contract(
            read_contract(repo, pr.head_sha, ticket_id), ticket_id, context
        )
        if isinstance(head_contract, RepoEvidenceVerdict):
            return head_contract
        if head_contract != contract:
            return RepoEvidenceVerdict(
                RepoEvidenceOutcome.REFUSED,
                f"{context}: contract changed between the verified head and the merge "
                "commit: the check run does not cover what merged; verify the "
                "merged contract in a new PR.",
            )
        for item in evidence_items(contract):
            for label in item.binds:
                bindings.setdefault(label, []).append(f"{item.item_id} ({source})")

    context = ", ".join(sources)
    labels: set[str] = set()
    for desc in dict.fromkeys(d for d in descriptions if d):
        criteria = live_acceptance_criteria_items(desc)
        if not criteria:
            return RepoEvidenceVerdict(
                RepoEvidenceOutcome.REFUSED,
                f"{context}: no acceptance criterion could be read from the ticket "
                "description, so there is nothing for the contract to bind; "
                "list labelled criteria under an `Acceptance criteria` or `DoD` heading.",
            )
        unlabelled = [c for c in criteria if not canonical_ac_label(c)]
        if unlabelled:
            return RepoEvidenceVerdict(
                RepoEvidenceOutcome.REFUSED,
                f"{context}: acceptance criteria carry no label and cannot be "
                f"bound by `binds_ac`: {'; '.join(unlabelled)}; label each criterion.",
            )
        labels.update(canonical_ac_label(c) for c in criteria)
    if not labels:
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{context}: no acceptance criterion could be read from the ticket "
            "description, so there is nothing for the contract to bind; list "
            "labelled acceptance criteria.",
        )
    unbound = sorted(labels - bindings.keys())
    if unbound:
        gaps = " | ".join(
            f"{label}: no dod_evidence item in the contracts of {context} binds it"
            for label in unbound
        )
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED, f"{gaps}; add the missing binds_ac entries."
        )
    return RepoEvidenceVerdict(
        RepoEvidenceOutcome.PASSED,
        "repo-bound: "
        + ", ".join(
            f"{label}<-{sorted(bindings[label])[0]}" for label in sorted(labels)
        ),
    )


__all__ = [
    "CONTRACT_DIR",
    "REPO_EVIDENCE_APP_SLUG",
    "REPO_EVIDENCE_CHECK_NAME",
    "CheckRunReader",
    "ContractRead",
    "ContractReadStatus",
    "ContractReader",
    "EvidenceItem",
    "RepoEvidenceOutcome",
    "RepoEvidenceVerdict",
    "acceptance_criteria_items",
    "canonical_ac_label",
    "evaluate_repo_evidence",
    "evidence_items",
    "gh_read_check_runs",
    "gh_read_contract",
    "live_acceptance_criteria_items",
]
