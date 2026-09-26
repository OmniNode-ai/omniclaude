# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The no-PR Done bar: every acceptance criterion bound to a fresh receipt [OMN-13856].

A ticket that cites no PR has nothing for the merged-PR check to read, so its
Done has to rest on the change-control record instead. Before this module the
guard accepted two things there, and both were weaker than the bar the evidence
closer applies to the same ticket:

* ANY ``status: PASS`` receipt under ``drift/dod_receipts/<TICKET>/`` on
  ``origin/dev``, whatever it proved and however old it was (path B); and
* briefly, on omniclaude#2345's first head, a ``live-state-proven:`` line in the
  ticket description, checked for shape and age but not truth. Anyone wanting
  the close could write it, so it was withdrawn (HOLD on that PR, 2026-09-25).

The bar here is the closer's, read from the same sources:

1. The ticket's OCC contract ``contracts/<TICKET>.yaml`` is on ``origin/dev``.
2. The ticket declares at least one acceptance criterion, read with the
   closer's criterion reader, and every criterion carries a label (``AC1``,
   ``DoD2``). An unlabelled criterion is unbindable: ``binds_ac`` has nothing
   to point at, and the closer holds such a ticket for the same reason.
3. Every criterion label is claimed by the ``binds_ac`` of at least one
   ``dod_evidence`` item, after ``supersedes_ac_binding`` retirements. A
   partially bound contract fails, as it does in OCC's OMN-18333 rule.
4. For every criterion, at least one binding item has a receipt that:

   * is ``status: PASS``;
   * names the SUBJECT: ``ticket_id`` is this ticket, ``evidence_item_id`` is
     the binding item, and ``check_type`` is one the item declares (the
     ``(evidence_item_id, check_type)`` key DurableEvidenceGate's
     CONTRACT_ON_OCC_MAIN check requires the contract to declare);
   * is independently attested and carries the observation: ``runner`` and
     ``verifier`` both set and different, and ``probe_stdout`` non-empty.
     These are the R1 and R2 guardrails of omnimarket
     ``node_dod_verify/services/receipt_bound_evidence.py`` (the PR-less
     receipt-bound class, OMN-15817 shape 5);
   * names the ENVIRONMENT the read was taken in: ``target_identity`` (the
     lane, namespace or host, as RUNTIME_OPS receipts carry it) or
     ``working_dir``, both existing ``ModelDodReceipt`` fields;
   * carries a READ TIME: ``run_timestamp`` is timezone-aware, not in the
     future beyond a small clock skew, and no older than
     :data:`NO_PR_RECEIPT_MAX_AGE`.

WHY A PORT, NOT AN IMPORT. The criterion reader and the label canonicaliser
below are copies of omnibase_infra
``node_evidence_autoclose_sweep_effect/handlers/handler_evidence_autoclose_sweep.py``
(``_is_ac_heading``, ``_acceptance_criteria_items``,
``_live_acceptance_criteria_items``, ``_canonical_ac_label``), which is itself
the reader OCC's ``validation/ac_criteria.py`` ports. Neither package is
importable at hook time: omnibase_infra's node tree is not a hook dependency,
and onex_change_control is a dev-group dependency here pinned to a rev that
predates ``ac_criteria``. The closer made the same call in the other direction
and says so. A change to the reader on either side should be mirrored here.

WHAT IT CANNOT DO. It reads a committed receipt; it does not re-run the probe.
A receipt reaches ``origin/dev`` only through a reviewed OCC PR, which is the
authenticity this bar leans on, and the freshness window bounds how stale that
read may be. The closer re-runs dod_verify; a PreToolUse hook cannot.

Pure logic apart from :func:`load_ticket_occ_evidence`, which reads git.
"""

from __future__ import annotations

import re
import subprocess  # noqa: S404 - fixed-argv git invocations, no shell
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# The freshness window for a no-PR receipt's read time. A no-PR ticket's
# evidence is an observation of state (worktrees gone, a record present), and
# state drifts; a readback older than this says what WAS true.
NO_PR_RECEIPT_MAX_AGE = timedelta(days=7)
# Tolerated clock skew for a receipt stamped slightly ahead of this host.
_MAX_FUTURE_SKEW = timedelta(minutes=5)

_CONTRACT_DIR = "contracts"
_RECEIPT_DIR_PREFIX = "drift/dod_receipts"
_RETIREMENT_FIELD = "supersedes_ac_binding"
_ENVIRONMENT_FIELDS = ("target_identity", "working_dir")

_GIT_FETCH_TIMEOUT_SECONDS = 20
_GIT_READ_TIMEOUT_SECONDS = 15
# How many failing criteria a refusal names before summarising.
_MAX_LISTED = 8


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

    Mirrors OCC ``ac_binding_acceptance._retired_pairs``: an entry naming no
    item, no label, no reason, or a label that item never bound takes no
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
# Receipt qualification
# --------------------------------------------------------------------------- #


def _str(receipt: dict[str, Any], key: str) -> str:
    value = receipt.get(key)
    return value.strip() if isinstance(value, str) else ""


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def receipt_defect(
    receipt: dict[str, Any],
    *,
    ticket_id: str,
    item: EvidenceItem,
    now: datetime,
    max_age: timedelta = NO_PR_RECEIPT_MAX_AGE,
) -> str | None:
    """Why ``receipt`` does not discharge ``item`` for ``ticket_id``, or None.

    None means the receipt names the subject, the environment and a fresh read
    time, and is an independently attested PASS. Pure function.
    """
    if _str(receipt, "status").upper() != "PASS":
        return "not a PASS"
    if _str(receipt, "ticket_id") != ticket_id:
        return (
            f"names subject {_str(receipt, 'ticket_id') or '(none)'}, not {ticket_id}"
        )
    if _str(receipt, "evidence_item_id") != item.item_id:
        return f"is for item {_str(receipt, 'evidence_item_id') or '(none)'}"
    check_type = _str(receipt, "check_type")
    if not check_type or check_type not in item.check_types:
        return (
            f"check_type {check_type or '(none)'} is not declared by item "
            f"{item.item_id} in the contract"
        )
    runner, verifier = _str(receipt, "runner"), _str(receipt, "verifier")
    if not runner or not verifier or runner == verifier:
        return "is self-attested or names no runner/verifier"
    if not _str(receipt, "probe_stdout"):
        return "carries no probe_stdout (no observation)"
    if not any(_str(receipt, key) for key in _ENVIRONMENT_FIELDS):
        return "names no environment (target_identity or working_dir)"
    read_at = _timestamp(receipt.get("run_timestamp"))
    if read_at is None:
        return "has no timezone-aware run_timestamp (no read time)"
    now_utc = now.astimezone(UTC)
    if read_at - now_utc > _MAX_FUTURE_SKEW:
        return f"read time {read_at.isoformat()} is in the future"
    if now_utc - read_at > max_age:
        return (
            f"read time {read_at.isoformat()} is older than the "
            f"{max_age.days}-day freshness window"
        )
    return None


@dataclass(frozen=True)
class BoundEvidenceVerdict:
    """The no-PR bar's answer: passed, and a human-readable account either way."""

    passed: bool
    detail: str


@dataclass(frozen=True)
class OccTicketEvidence:
    """What ``origin/dev`` of the OCC clone holds for one ticket."""

    contract: dict[str, Any] | None
    receipts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


def evaluate_bound_evidence(
    ticket_id: str,
    description: str,
    evidence: OccTicketEvidence,
    now: datetime,
    *,
    max_age: timedelta = NO_PR_RECEIPT_MAX_AGE,
) -> BoundEvidenceVerdict:
    """Apply the no-PR bar (module docstring, steps 1-4). Pure function."""
    contract_path = f"{_CONTRACT_DIR}/{ticket_id}.yaml"
    if evidence.contract is None:
        why = f" ({evidence.error})" if evidence.error else ""
        return BoundEvidenceVerdict(
            False, f"no OCC contract {contract_path} on origin/dev{why}"
        )

    criteria = live_acceptance_criteria_items(description)
    if not criteria:
        return BoundEvidenceVerdict(
            False,
            "no acceptance criterion could be read from the ticket description, "
            "so there is nothing for the contract to bind; list the criteria "
            "under an `Acceptance criteria` or `DoD` heading, labelled AC1, AC2, ...",
        )
    unlabelled = [c for c in criteria if not canonical_ac_label(c)]
    if unlabelled:
        return BoundEvidenceVerdict(
            False,
            f"{len(unlabelled)} acceptance criterion/criteria carry no label and "
            "cannot be bound by `binds_ac`: "
            + "; ".join(c[:80] for c in unlabelled[:_MAX_LISTED])
            + ". Label each (AC1, AC2, ... or DoD1, ...)",
        )

    items = evidence_items(evidence.contract)
    gaps: list[str] = []
    proven: list[str] = []
    seen: set[str] = set()
    for criterion in criteria:
        label = canonical_ac_label(criterion)
        if label in seen:
            continue
        seen.add(label)
        binders = [item for item in items if label in item.binds]
        if not binders:
            gaps.append(f"{label}: no dod_evidence item in {contract_path} binds it")
            continue
        defects: list[str] = []
        discharged_by = ""
        for item in binders:
            candidates = [
                r
                for r in evidence.receipts
                if _str(r, "evidence_item_id") == item.item_id
            ]
            if not candidates:
                defects.append(f"{item.item_id} has no receipt on origin/dev")
                continue
            for receipt in candidates:
                defect = receipt_defect(
                    receipt, ticket_id=ticket_id, item=item, now=now, max_age=max_age
                )
                if defect is None:
                    discharged_by = item.item_id
                    break
                defects.append(f"{item.item_id} receipt {defect}")
            if discharged_by:
                break
        if discharged_by:
            proven.append(f"{label}<-{discharged_by}")
        else:
            gaps.append(f"{label}: " + "; ".join(defects[:3]))

    if gaps:
        more = f" (+{len(gaps) - _MAX_LISTED} more)" if len(gaps) > _MAX_LISTED else ""
        return BoundEvidenceVerdict(
            False,
            "acceptance criteria without a bound, fresh, attested receipt: "
            + " | ".join(gaps[:_MAX_LISTED])
            + more,
        )
    return BoundEvidenceVerdict(True, "bound: " + ", ".join(proven))


# --------------------------------------------------------------------------- #
# Git-backed loader (origin/dev of the local OCC clone)
# --------------------------------------------------------------------------- #


def _git(
    args: list[str], cwd: Path, timeout: int
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def load_ticket_occ_evidence(
    occ_repo: Path, ticket_id: str, *, ref: str = "origin/dev", fetch: bool = True
) -> OccTicketEvidence:
    """Read the ticket's contract and receipts off ``ref``; never the work tree.

    Fail-closed: any failure yields ``contract=None`` with the reason, or an
    empty receipt list, both of which the bar refuses.
    """
    try:
        import yaml
    except ImportError:
        return OccTicketEvidence(None, error="PyYAML is not importable at hook time")
    if not occ_repo.is_dir():
        return OccTicketEvidence(None, error=f"no OCC clone at {occ_repo}")
    if fetch:
        # Best effort: a failed fetch still reads the last-known ref.
        _git(
            ["fetch", "--quiet", "origin", "dev"], occ_repo, _GIT_FETCH_TIMEOUT_SECONDS
        )

    shown = _git(
        ["show", f"{ref}:{_CONTRACT_DIR}/{ticket_id}.yaml"],
        occ_repo,
        _GIT_READ_TIMEOUT_SECONDS,
    )
    if shown is None or shown.returncode != 0:
        return OccTicketEvidence(None, error="contract not found")
    try:
        contract = yaml.safe_load(shown.stdout)
    except yaml.YAMLError as exc:
        return OccTicketEvidence(None, error=f"contract YAML unreadable: {exc}")
    if not isinstance(contract, dict):
        return OccTicketEvidence(None, error="contract is not a mapping")

    receipts: list[dict[str, Any]] = []
    listing = _git(
        [
            "ls-tree",
            "-r",
            "--name-only",
            ref,
            "--",
            f"{_RECEIPT_DIR_PREFIX}/{ticket_id}",
        ],
        occ_repo,
        _GIT_READ_TIMEOUT_SECONDS,
    )
    if listing is not None and listing.returncode == 0:
        for rel_path in listing.stdout.splitlines():
            rel_path = rel_path.strip()
            if not rel_path.endswith(".yaml"):
                continue
            body = _git(
                ["show", f"{ref}:{rel_path}"], occ_repo, _GIT_READ_TIMEOUT_SECONDS
            )
            if body is None or body.returncode != 0:
                continue
            try:
                parsed = yaml.safe_load(body.stdout)
            except yaml.YAMLError:
                continue
            if isinstance(parsed, dict):
                receipts.append(parsed)
    return OccTicketEvidence(contract, receipts)


__all__ = [
    "NO_PR_RECEIPT_MAX_AGE",
    "BoundEvidenceVerdict",
    "EvidenceItem",
    "OccTicketEvidence",
    "acceptance_criteria_items",
    "canonical_ac_label",
    "evaluate_bound_evidence",
    "evidence_items",
    "live_acceptance_criteria_items",
    "load_ticket_occ_evidence",
    "receipt_defect",
]
