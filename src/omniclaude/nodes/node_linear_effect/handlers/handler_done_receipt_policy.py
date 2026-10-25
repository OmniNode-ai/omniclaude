# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Receipt revision and fail-closed hook policy owned by node_linear_effect.

The plugin's baselined entrypoints call this handler. This module uses only
standard-library imports until a contract actually needs YAML parsing, so a
missing runtime package can never turn a no-receipt refusal into an allow.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaude.nodes.node_linear_effect.models.model_done_guard_readers import (
        ModelDoneGuardReaders,
    )
    from omniclaude.nodes.node_linear_effect.protocols.protocol_done_receipt_policy import (
        ProtocolContractRead,
        ProtocolDoneDecider,
        ProtocolReceiptEvidence,
        ProtocolReceiptItem,
        ProtocolReceiptVerdict,
    )


def parse_contract(
    read: ProtocolContractRead,
    ticket_id: str,
    source: str,
    evidence: ProtocolReceiptEvidence,
) -> Mapping[str, object] | ProtocolReceiptVerdict:
    """Parse a contract, refusing unavailable YAML support or invalid data."""
    ContractReadStatus = evidence.ContractReadStatus
    RepoEvidenceVerdict = evidence.RepoEvidenceVerdict
    RepoEvidenceOutcome = evidence.RepoEvidenceOutcome
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


def check_contract_revision(
    head: str, merged: str, current: str, context: str, ref: str
) -> tuple[str, str]:
    verified_hash = hashlib.sha256(head.encode("utf-8")).hexdigest()
    merged_hash = hashlib.sha256(merged.encode("utf-8")).hexdigest()
    current_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if verified_hash != merged_hash or verified_hash != current_hash:
        return "", (
            f"{context}: stale_contract: verified hash {verified_hash}, "
            f"merge hash {merged_hash}, {ref} hash {current_hash}; "
            "obtain a PASS receipt for the current contract."
        )
    return current_hash, ""


def run_hook(decide: ProtocolDoneDecider, readers: ModelDoneGuardReaders) -> int:
    """Read one hook payload and emit a refusal for every decision error."""
    try:
        call = json.loads(sys.stdin.read())
        if not isinstance(call, dict) or not isinstance(call.get("tool_name"), str):
            raise ValueError("hook payload must be a JSON object with tool_name")
        decision = decide(call, **readers)
        if decision.allowed:
            return 0
        reason = decision.reason
    except (
        ArithmeticError,
        AssertionError,
        AttributeError,
        ImportError,
        LookupError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        reason = (
            "guard_error: the done-flip guard could not decide "
            f"({type(exc).__name__}: {exc}). Refusing the Linear write "
            "without a bound receipt (OMN-20368)."
        )
    sys.stderr.write(
        json.dumps(
            {
                "decision": "block",
                "reason": f"[OMN-20368 done-flip repo-evidence gate] {reason}",
            }
        )
        + "\n"
    )
    return 2


def evidence_items(
    contract: Mapping[str, object], evidence: ProtocolReceiptEvidence
) -> list[ProtocolReceiptItem]:
    """Every ``dod_evidence`` item with its live ``binds_ac`` labels."""
    _retired_pairs = evidence._retired_pairs
    _items = evidence._items
    canonical_ac_label = evidence.canonical_ac_label
    EvidenceItem = evidence.EvidenceItem
    retired = _retired_pairs(contract)
    out: list[ProtocolReceiptItem] = []
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
