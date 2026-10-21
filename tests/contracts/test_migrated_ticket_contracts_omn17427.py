# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The migrated ticket contracts remain readable in the product repository."""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
# Evidence identities from the 24 contracts migrated in this pull request.
# Additional evidence may be appended without changing these historical items.
MIGRATED_EVIDENCE = {
    "OMN-14856": (
        "dod-OmniNode-ai-omniclaude-pr-1984",
        "dod-occ-evidence-admissibility-validator",
        "occ-self-bind-pr-6385",
    ),
    "OMN-14882": (
        "dod-OmniNode-ai-omniclaude-pr-2079",
        "dod-occ-diff-derived-behavior-proof",
        "occ-self-bind-pr-7681",
    ),
    "OMN-16371": (
        "dod-OmniNode-ai-omniclaude-pr-2011",
        "dod-occ-evidence-admissibility-validator",
        "occ-self-bind-pr-6852",
    ),
    "OMN-16726": (
        "dod-OmniNode-ai-omniclaude-pr-2366",
        "dod-occ-diff-derived-behavior-proof",
        "occ-self-bind-pr-11445",
    ),
    "OMN-16742": (
        "occ-self-bind-pr-11780",
        "dod-OmniNode-ai-omniclaude-pr-2409",
        "dod-OmniNode-ai-omniclaude-pr-2409-ci",
        "dod-occ-diff-derived-behavior-proof-pr-2409",
    ),
    "OMN-16826": (
        "dod-OmniNode-ai-omniclaude-pr-2056",
        "dod-OmniNode-ai-omniclaude-pr-2056-ci",
        "dod-occ-evidence-admissibility-validator",
        "occ-self-bind-pr-7386",
        "dod-OmniNode-ai-omnimarket-pr-2185",
        "dod-OmniNode-ai-omnimarket-pr-2185-ci",
        "occ-self-bind-pr-7408",
        "dod-occ-diff-derived-behavior-proof",
    ),
    "OMN-16913": (
        "occ-self-bind-pr-11926",
        "dod-OmniNode-ai-omniclaude-pr-2435",
        "dod-OmniNode-ai-omniclaude-pr-2435-ci",
        "dod-occ-diff-derived-behavior-proof-pr-2435",
    ),
    "OMN-16986": (
        "dod-OmniNode-ai-omniclaude-pr-2365",
        "dod-OmniNode-ai-omniclaude-pr-2365-ci",
        "dod-occ-diff-derived-behavior-proof-pr-2365",
        "occ-self-bind-pr-11412",
    ),
    "OMN-17047": (
        "dod-OmniNode-ai-omniclaude-pr-2572",
        "dod-OmniNode-ai-omniclaude-pr-2572-ci",
        "occ-self-bind-pr-13106",
        "dod-occ-diff-derived-behavior-proof-pr-2572",
    ),
    "OMN-17102": (
        "occ-self-bind-pr-12506",
        "dod-OmniNode-ai-omniclaude-pr-2518",
        "dod-OmniNode-ai-omniclaude-pr-2518-ci",
        "dod-occ-diff-derived-behavior-proof-pr-2518",
    ),
    "OMN-17207": (
        "dod-OmniNode-ai-omniclaude-pr-2085",
        "dod-occ-diff-derived-behavior-proof",
        "occ-self-bind-pr-7738",
    ),
    "OMN-17284": (
        "dod-OmniNode-ai-omniclaude-pr-2148",
        "dod-occ-diff-derived-behavior-proof",
        "occ-self-bind-pr-9376",
        "dod-OmniNode-ai-omniclaude-pr-2174",
        "dod-OmniNode-ai-omniclaude-pr-2174-ci",
        "occ-self-bind-pr-9642",
        "dod-OmniNode-ai-omniclaude-pr-2175",
        "dod-OmniNode-ai-omniclaude-pr-2175-ci",
        "occ-self-bind-pr-9653",
    ),
    "OMN-17354": (
        "dod-OmniNode-ai-omniclaude-pr-2097",
        "dod-OmniNode-ai-omniclaude-pr-2097-ci",
        "dod-occ-diff-derived-behavior-proof",
        "occ-self-bind-pr-7991",
        "dod-omn17354-customer-entrypoint-install-proof",
    ),
    "OMN-17827": (
        "dod-OmniNode-ai-omniclaude-pr-2103",
        "dod-occ-diff-derived-behavior-proof",
        "occ-self-bind-pr-8141",
    ),
    "OMN-18183": (
        "dod-OmniNode-ai-omniclaude-pr-2135",
        "dod-occ-diff-derived-behavior-proof",
        "occ-self-bind-pr-9112",
    ),
    "OMN-18358": (
        "dod-OmniNode-ai-omnibase_infra-pr-3523",
        "dod-OmniNode-ai-omniclaude-pr-2160",
        "dod-OmniNode-ai-omniclaude-pr-2160-ci",
        "dod-occ-diff-derived-behavior-proof",
        "dod-occ-diff-derived-behavior-proof-pr-2160",
        "occ-self-bind-pr-9486",
        "occ-self-bind-pr-9486-merged",
        "occ-self-bind-pr-9487",
    ),
    "OMN-18983": (
        "dod-OmniNode-ai-omniclaude-pr-2591",
        "dod-OmniNode-ai-omniclaude-pr-2591-ci",
    ),
    "OMN-19055": ("dod-OmniNode-ai-omniclaude-pr-2636",),
    "OMN-20220": (
        "dod-OmniNode-ai-omniclaude-pr-2553",
        "dod-OmniNode-ai-omniclaude-pr-2553-ci",
        "dod-OmniNode-ai-omniclaude-pr-2569",
    ),
    "OMN-20356": (
        "dod-OmniNode-ai-omniclaude-pr-2496-ci",
        "dod-OmniNode-ai-omniclaude-pr-2496",
    ),
    "OMN-20389": (
        "dod-OmniNode-ai-omniclaude-pr-2508-ci",
        "dod-OmniNode-ai-omniclaude-pr-2508",
    ),
    "OMN-20398": (
        "dod-omn20398-pr2559-report-contract-tests",
        "dod-omn20398-pr2559-guard-inbox-pattern",
    ),
    "OMN-20664": (
        "dod-OmniNode-ai-omniclaude-pr-2576",
        "dod-OmniNode-ai-omniclaude-pr-2576-ci",
        "dod-occ-diff-derived-behavior-proof",
    ),
    "OMN-6227": ("dod-001", "dod-002", "dod-003", "dod-004"),
}


@pytest.mark.parametrize("ticket", MIGRATED_EVIDENCE)
def test_migrated_contract_identifies_its_ticket(ticket: str) -> None:
    contract = yaml.safe_load((CONTRACTS / f"{ticket}.yaml").read_text())

    assert contract["schema_version"] == "1.0.0"
    assert contract["ticket_id"] == ticket
    assert contract["title"].strip()


@pytest.mark.parametrize("ticket", MIGRATED_EVIDENCE)
def test_migrated_contract_retains_its_evidence(ticket: str) -> None:
    contract = yaml.safe_load((CONTRACTS / f"{ticket}.yaml").read_text())
    items = contract["dod_evidence"]
    by_id = {item["id"]: item for item in items}

    assert len(by_id) == len(items), "Evidence IDs must remain unique"
    for evidence_id in MIGRATED_EVIDENCE[ticket]:
        checks = by_id[evidence_id]["checks"]
        assert checks, evidence_id
        for check in checks:
            assert check["check_type"].strip(), evidence_id
            assert check["check_value"].strip(), evidence_id
