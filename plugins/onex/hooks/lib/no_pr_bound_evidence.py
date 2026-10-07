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

import base64
import binascii
import hashlib
import http.client
import json
import os
import re
import signal
import subprocess  # noqa: S404 - fixed-argv git invocations, no shell
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

from linear_done_verify import PRStatus, _gh_api_json

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
# OMN-20368: a receipt behind a MERGED product PR names the code it read by its
# commit, so the commit is that receipt's environment. The no-PR bar keeps the
# narrower pair above: a commit is not where a state readback was taken.
MERGED_PR_ENVIRONMENT_FIELDS = ("target_identity", "working_dir", "commit_sha")

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


def _entry_hash(contract: dict[str, Any], item_id: str) -> str | None:
    """The canonical per-entry hash OCC binds receipts to, or None.

    Imported from omnibase_core (a runtime dependency of this plugin), never
    reimplemented: occ-preflight and the Receipt Gate use the same function, so
    a port here could disagree with them silently. None when it cannot be
    computed, which the caller refuses.
    """
    try:
        from omnibase_core.validation.validator_receipt_gate import (
            compute_contract_entry_sha256,
        )
    except ImportError:
        return None
    try:
        return str(compute_contract_entry_sha256(contract, item_id))
    except (LookupError, TypeError, ValueError):
        # ContractEntryNotFoundError is a LookupError: "cannot recompute",
        # which the caller refuses.
        return None


def _normalised_hash(value: str) -> str:
    text = value.strip().lower()
    return text if text.startswith("sha256:") else f"sha256:{text}"


def staleness_defect(
    receipt: dict[str, Any],
    *,
    item: EvidenceItem,
    contract: dict[str, Any],
    contract_sha256: str,
) -> str | None:
    """Why ``receipt`` was taken against a different contract than today's, or None.

    OMN-20368. A receipt is evidence about the contract it was run against. When
    the contract entry it discharges has changed since, the receipt proves the
    old entry, not the current one, and a Done resting on it is unearned.

    * ``contract_entry_sha256`` present: it must equal the per-entry hash of
      the item in the contract on ``origin/dev`` today.
    * otherwise ``contract_sha256`` (legacy, whole file) must equal the hash of
      today's contract bytes.
    * neither: the receipt names no contract version at all, so nothing ties
      it to today's criteria.
    """
    entry_hash = _str(receipt, "contract_entry_sha256")
    if entry_hash:
        current = _entry_hash(contract, item.item_id)
        if current is None:
            return (
                "per-entry contract hash cannot be recomputed at hook time "
                "(omnibase_core.validation.validator_receipt_gate unavailable)"
            )
        if _normalised_hash(entry_hash) != _normalised_hash(current):
            return (
                f"is stale: contract entry {item.item_id} changed since the "
                "receipt was taken (contract_entry_sha256 does not match the "
                "contract on origin/dev); re-run dod_verify and land a new receipt"
            )
        return None
    whole = _str(receipt, "contract_sha256")
    if whole:
        if not contract_sha256 or _normalised_hash(whole) != _normalised_hash(
            contract_sha256
        ):
            return (
                "is stale: the contract changed since the receipt was taken "
                "(contract_sha256 does not match the contract on origin/dev); "
                "re-run dod_verify and land a new receipt"
            )
        return None
    return "names no contract version (no contract_entry_sha256 or contract_sha256)"


def receipt_defect(
    receipt: dict[str, Any],
    *,
    ticket_id: str,
    item: EvidenceItem,
    now: datetime,
    max_age: timedelta | None = NO_PR_RECEIPT_MAX_AGE,
    environment_fields: tuple[str, ...] = _ENVIRONMENT_FIELDS,
    contract: dict[str, Any] | None = None,
    contract_sha256: str = "",
) -> str | None:
    """Why ``receipt`` does not discharge ``item`` for ``ticket_id``, or None.

    None means the receipt names the subject, the environment and a read time
    (fresh, when ``max_age`` is set), is an independently attested PASS, and,
    when ``contract`` is given, was taken against today's contract entry
    (OMN-20368). Pure function apart from the omnibase_core hash import.
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
    if not any(_str(receipt, key) for key in environment_fields):
        return f"names no environment ({' or '.join(environment_fields)})"
    read_at = _timestamp(receipt.get("run_timestamp"))
    if read_at is None:
        return "has no timezone-aware run_timestamp (no read time)"
    now_utc = now.astimezone(UTC)
    if read_at - now_utc > _MAX_FUTURE_SKEW:
        return f"read time {read_at.isoformat()} is in the future"
    if max_age is not None and now_utc - read_at > max_age:
        return (
            f"read time {read_at.isoformat()} is older than the "
            f"{max_age.days}-day freshness window"
        )
    if contract is not None:
        return staleness_defect(
            receipt, item=item, contract=contract, contract_sha256=contract_sha256
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
    # OMN-20368: ``sha256:<hex>`` of the contract's bytes on the ref, the value
    # a legacy whole-file ``contract_sha256`` receipt binding is compared to.
    contract_sha256: str = ""


def evaluate_bound_evidence(
    ticket_id: str,
    description: str,
    evidence: OccTicketEvidence,
    now: datetime,
    *,
    max_age: timedelta | None = NO_PR_RECEIPT_MAX_AGE,
    environment_fields: tuple[str, ...] = _ENVIRONMENT_FIELDS,
    check_staleness: bool = True,
) -> BoundEvidenceVerdict:
    """Apply the bound-receipt bar (module docstring, steps 1-4). Pure function.

    OMN-20368: this is now the bar for EVERY Done flip, not only the no-PR one.
    ``check_staleness`` refuses a receipt taken against a contract entry that
    has changed since; ``max_age`` (None for no window) and
    ``environment_fields`` let the merged-PR path judge a receipt about merged
    code by its commit rather than by a state-read window.
    """
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
                    receipt,
                    ticket_id=ticket_id,
                    item=item,
                    now=now,
                    max_age=max_age,
                    environment_fields=environment_fields,
                    contract=evidence.contract if check_staleness else None,
                    contract_sha256=evidence.contract_sha256,
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


def bounded_fetch(repo: Path, timeout: float = _GIT_FETCH_TIMEOUT_SECONDS) -> None:
    """``git fetch --quiet origin dev`` in ``repo``, over within ``timeout`` seconds.

    OMN-20368. A fetch run with captured output waits for EOF on its pipes,
    and the ssh or https helper git spawns keeps them open after git itself is
    killed, so ``subprocess.run(..., capture_output=True, timeout=...)`` can
    hang well past its timeout. The hook harness then times the guard out and
    lets the Linear write through, which is how two Done-class writes passed
    unchecked during the live probe on a loaded host. Here nothing is captured,
    the fetch runs in its own process group, and the whole group is killed at
    the deadline. Any failure is ignored: the caller reads the last-known ref.
    """
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(repo), "fetch", "--quiet", "origin", "dev"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait()


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
        bounded_fetch(occ_repo)

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
    contract_sha256 = (
        f"sha256:{hashlib.sha256(shown.stdout.encode('utf-8')).hexdigest()}"
    )

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
    return OccTicketEvidence(contract, receipts, contract_sha256=contract_sha256)


# --------------------------------------------------------------------------- #
# Repo-owned evidence (OMN-20071): the product repository first, OCC second.
# --------------------------------------------------------------------------- #

# Repo-first Done evidence: a product contract and its verified PR head.
#
# The merged product repository's ``contracts/<TICKET>.yaml`` must bind every
# labelled acceptance criterion. A successful GitHub Actions check named
# ``repo-evidence / dod-verify`` attests that those checks passed at the PR head
# and failed at the merge base, using a workflow the PR cannot edit. The contract
# at that verified head must match what merged. Once engaged, this verdict is
# final; only repositories without this evidence fall back to OCC. No database
# is read, and importing this module performs no network I/O.

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


class VerdictReadStatus(StrEnum):
    FOUND = "found"
    ABSENT = "absent"
    ERROR = "error"


@dataclass(frozen=True)
class VerdictRead:
    status: VerdictReadStatus
    row: dict[str, Any] | None = None
    error: str = ""


VerdictReader = Callable[[str], VerdictRead]


# OMN-20071: the projection read the Done gate makes is declared in a hook
# contract (runtime URL as an ${env.VAR} overlay, command, topic, limit), so
# this module carries no endpoint or topic literal.
_VERDICT_READ_CONTRACT = (
    Path(__file__).resolve().parent.parent
    / "contracts"
    / "hook_done_gate_verdict_read.yaml"
)
_ENV_REF = re.compile(r"\$\{env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")


def _verdict_read_declaration() -> dict[str, Any] | str:
    """The declared projection read, or why it cannot be read."""
    try:
        import yaml
    except ImportError:
        return "PyYAML is unavailable to read the verdict-read contract"
    try:
        loaded = yaml.safe_load(_VERDICT_READ_CONTRACT.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return f"verdict-read contract unreadable: {exc}"
    declared = loaded.get("projection_read") if isinstance(loaded, dict) else None
    if not isinstance(declared, dict) or not all(
        isinstance(declared.get(key), str) and declared[key]
        for key in ("runtime_url", "command_name", "topic")
    ):
        return "verdict-read contract declares no complete projection_read mapping"
    return declared


def runtime_read_repo_verdict(ticket_id: str) -> VerdictRead:
    """Read the latest product-repository verdict through the projection node."""
    declared = _verdict_read_declaration()
    if isinstance(declared, str):
        return VerdictRead(VerdictReadStatus.ERROR, error=declared)
    url_ref = str(declared["runtime_url"])
    runtime_url = _ENV_REF.sub(
        lambda ref: os.environ.get(ref.group("name"), ""), url_ref
    ).strip()
    if not runtime_url:
        names = ", ".join(m.group("name") for m in _ENV_REF.finditer(url_ref))
        return VerdictRead(VerdictReadStatus.ERROR, error=f"{names} is unset")
    parts = urlsplit(runtime_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return VerdictRead(
            VerdictReadStatus.ERROR,
            error=f"runtime URL {runtime_url!r} is not an http(s) URL",
        )
    timeout = float(declared.get("timeout_seconds") or 15)
    request_body = {
        "command_name": declared["command_name"],
        "correlation_id": str(uuid4()),
        "timeout_ms": int(timeout * 1000),
        "payload": {
            "topic": declared["topic"],
            "row_ticket_id": ticket_id,
            "order_by": "completed_at",
            "order": "desc",
            "limit": int(declared.get("limit") or 100),
        },
    }
    connection_class = (
        http.client.HTTPSConnection
        if parts.scheme == "https"
        else http.client.HTTPConnection
    )
    try:
        connection = connection_class(parts.hostname, parts.port, timeout=timeout)
        try:
            connection.request(
                "POST",
                f"{parts.path.rstrip('/')}/skill",
                body=json.dumps(request_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            http_status, raw = response.status, response.read()
        finally:
            connection.close()
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return VerdictRead(
            VerdictReadStatus.ERROR, error=f"runtime transport error: {exc}"
        )
    if http_status != 200:
        return VerdictRead(
            VerdictReadStatus.ERROR,
            error=f"runtime answered HTTP {http_status}: {raw[:200]!r}",
        )
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        return VerdictRead(
            VerdictReadStatus.ERROR, error=f"non-JSON runtime response: {exc}"
        )
    if not isinstance(data, dict) or data.get("ok") is not True:
        error = data.get("error", "missing ok=true") if isinstance(data, dict) else data
        return VerdictRead(VerdictReadStatus.ERROR, error=f"runtime refusal: {error}")
    outputs = data.get("output_payloads")
    payload = None
    for output in outputs if isinstance(outputs, list) else []:
        if not isinstance(output, dict):
            continue
        if "ok" in output:
            payload = output
            break
        nested = output.get("payload")
        if isinstance(nested, dict) and "ok" in nested:
            payload = nested
            break
    if payload is None:
        return VerdictRead(
            VerdictReadStatus.ERROR, error="runtime response missing rows payload"
        )
    if payload.get("ok") is not True:
        return VerdictRead(
            VerdictReadStatus.ERROR,
            error=f"projection refusal: {payload.get('error', 'missing ok=true')}",
        )
    rows = payload.get("rows")
    if rows is None and isinstance(payload.get("payload"), dict):
        nested = payload["payload"]
        if nested.get("ok", True) is not True:
            return VerdictRead(
                VerdictReadStatus.ERROR,
                error=f"projection refusal: {nested.get('error', 'missing ok=true')}",
            )
        rows = nested.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return VerdictRead(
            VerdictReadStatus.ERROR,
            error="projection response missing or malformed rows",
        )
    ranked: list[tuple[datetime, int, dict[str, Any]]] = []
    for row in rows:
        if (
            row.get("ticket_id") != ticket_id
            or row.get("contract_source") != "product_repository"
        ):
            continue
        completed = _timestamp(row.get("completed_at"))
        if completed is None:
            return VerdictRead(
                VerdictReadStatus.ERROR, error="repo verdict has invalid completed_at"
            )
        try:
            cursor = int(row.get("projection_cursor") or 0)
        except (TypeError, ValueError) as exc:
            return VerdictRead(
                VerdictReadStatus.ERROR,
                error=f"repo verdict has invalid projection_cursor: {exc}",
            )
        ranked.append((completed, cursor, row))
    if not ranked:
        return VerdictRead(VerdictReadStatus.ABSENT)
    return VerdictRead(
        VerdictReadStatus.FOUND, row=max(ranked, key=lambda item: item[:2])[2]
    )


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
    read_verdict: VerdictReader = runtime_read_repo_verdict,
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
        return _evaluate_repo_verdict(
            ticket_id,
            descriptions,
            contracts,
            "; ".join(skipped),
            read_verdict,
            read_contract,
        )

    for pr, contract, kept in engaged:
        assert pr.ref.repo is not None
        repo = pr.ref.repo
        source = f"{repo}#{pr.ref.number}"
        context = f"{source} at head {pr.head_sha} and merge {pr.merge_commit_sha}"
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
        defect = _verified_head_defect(
            pr, contract, ticket_id, read_contract, verifier="the check run"
        )
        if defect is not None:
            return defect
    return _evaluate_repo_bindings(
        descriptions,
        [(pr, contract) for pr, contract, _kept in engaged],
        "repo-bound: ",
    )


def _verified_head_defect(
    pr: PRStatus,
    contract: dict[str, Any],
    ticket_id: str,
    read_contract: ContractReader,
    *,
    verifier: str,
) -> RepoEvidenceVerdict | None:
    context = f"{pr.ref.repo}#{pr.ref.number} at head {pr.head_sha} and merge {pr.merge_commit_sha}"
    assert pr.ref.repo is not None
    head_contract = _parse_contract(
        read_contract(pr.ref.repo, pr.head_sha, ticket_id), ticket_id, context
    )
    if isinstance(head_contract, RepoEvidenceVerdict):
        return head_contract
    if head_contract != contract:
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{context}: contract changed between the verified head and the merge "
            f"commit: {verifier} does not cover what merged; verify the "
            "merged contract in a new PR.",
        )
    return None


def _evaluate_repo_verdict(
    ticket_id: str,
    descriptions: Sequence[str],
    contracts: list[tuple[PRStatus, dict[str, Any]]],
    skipped_detail: str,
    read_verdict: VerdictReader,
    read_contract: ContractReader,
) -> RepoEvidenceVerdict:
    read = read_verdict(ticket_id)
    if read.status is VerdictReadStatus.ERROR or (
        read.status is VerdictReadStatus.FOUND and read.row is None
    ):
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.NOT_ENGAGED,
            skipped_detail
            + "; repo-owned dod_verify verdict unreadable: "
            + (read.error or "FOUND without a row"),
        )
    if read.status is VerdictReadStatus.ABSENT:
        return RepoEvidenceVerdict(RepoEvidenceOutcome.NOT_ENGAGED, skipped_detail)
    row = read.row
    assert row is not None
    repository, sha, path = (
        value if isinstance(value, str) else ""
        for value in (
            row.get("contract_repository"),
            row.get("contract_commit_sha"),
            row.get("contract_repo_path"),
        )
    )
    bound = next(
        (
            (pr, contract)
            for pr, contract in contracts
            if pr.ref.repo is not None
            and pr.ref.repo.casefold() == repository.casefold()
            and sha in (pr.head_sha, pr.merge_commit_sha)
            and path == f"contracts/{ticket_id}.yaml"
        ),
        None,
    )
    sources = ", ".join(f"{pr.ref.repo}#{pr.ref.number}" for pr, _contract in contracts)
    verdict_context = (
        f"the latest repo-owned dod_verify verdict for {ticket_id} "
        f"(run {row.get('correlation_id')}, completed {row.get('completed_at')})"
    )
    if bound is None:
        heads = ", ".join(pr.head_sha[:12] for pr, _contract in contracts)
        merges = ", ".join(pr.merge_commit_sha[:12] for pr, _contract in contracts)
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{sources}: {verdict_context} was taken at {repository}@{sha[:12]} "
            f"{path}, not at the merged head {heads} or merge commit {merges} "
            f"of {sources}; verify the merged contract.",
        )
    pr, contract = bound
    if row.get("status") != "verified":
        return RepoEvidenceVerdict(
            RepoEvidenceOutcome.REFUSED,
            f"{pr.ref.repo}#{pr.ref.number}: {verdict_context} has "
            f"status={row.get('status')}; obtain a verified verdict for the merged contract.",
        )
    if sha == pr.head_sha:
        defect = _verified_head_defect(
            pr, contract, ticket_id, read_contract, verifier="the verdict"
        )
        if defect is not None:
            return defect
    return _evaluate_repo_bindings(
        descriptions,
        [(pr, contract)],
        f"repo-bound verdict {row.get('correlation_id')} at {sha[:12]}: ",
    )


def _evaluate_repo_bindings(
    descriptions: Sequence[str],
    contracts: list[tuple[PRStatus, dict[str, Any]]],
    pass_prefix: str,
) -> RepoEvidenceVerdict:
    """Apply the identical criterion and binds_ac bar to both repo verdict sources."""
    bindings: dict[str, list[str]] = {}
    sources: list[str] = []
    for pr, contract in contracts:
        source = f"{pr.ref.repo}#{pr.ref.number}"
        sources.append(
            f"{source} at head {pr.head_sha} and merge {pr.merge_commit_sha}"
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
        pass_prefix
        + ", ".join(
            f"{label}<-{sorted(bindings[label])[0]}" for label in sorted(labels)
        ),
    )


__all__ = [
    "CONTRACT_DIR",
    "MERGED_PR_ENVIRONMENT_FIELDS",
    "NO_PR_RECEIPT_MAX_AGE",
    "REPO_EVIDENCE_APP_SLUG",
    "REPO_EVIDENCE_CHECK_NAME",
    "BoundEvidenceVerdict",
    "CheckRunReader",
    "ContractRead",
    "ContractReadStatus",
    "ContractReader",
    "EvidenceItem",
    "OccTicketEvidence",
    "RepoEvidenceOutcome",
    "RepoEvidenceVerdict",
    "VerdictRead",
    "VerdictReadStatus",
    "VerdictReader",
    "acceptance_criteria_items",
    "bounded_fetch",
    "canonical_ac_label",
    "evaluate_bound_evidence",
    "evaluate_repo_evidence",
    "evidence_items",
    "gh_read_check_runs",
    "gh_read_contract",
    "live_acceptance_criteria_items",
    "load_ticket_occ_evidence",
    "receipt_defect",
    "runtime_read_repo_verdict",
    "staleness_defect",
]
