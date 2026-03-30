# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Enrich a skeleton contract YAML with dod_evidence from implementation artifacts.

Reads a skeleton contract, discovers test files and CI commands from the
implementation, and populates the dod_evidence[] array with ModelDodEvidenceItem-
compatible entries.
"""

from __future__ import annotations

import yaml


def enrich_contract_with_evidence(
    *,
    contract_yaml: str,
    test_files: list[str],
    test_command: str | None = None,
    include_lint: bool = True,
    repo: str,
) -> str:
    """Add dod_evidence entries to an existing contract YAML.

    Args:
        contract_yaml: Existing contract YAML string
        test_files: List of test file paths added/modified
        test_command: Explicit test command (auto-generated if None)
        include_lint: Whether to add pre-commit lint evidence
        repo: Repository name (for command paths)

    Returns:
        Updated YAML string with populated dod_evidence[]
    """
    contract = yaml.safe_load(contract_yaml)
    existing: list[dict[str, object]] = contract.get("dod_evidence", [])
    existing_ids = {e["id"] for e in existing}

    evidence: list[dict[str, object]] = list(existing)
    counter = len(existing) + 1

    # Build semantic dedup index: set of (check_type, check_value) tuples
    existing_checks: set[tuple[str, str]] = set()
    for item in existing:
        for check in item.get("checks", []):  # type: ignore[union-attr]
            existing_checks.add(
                (check.get("check_type", ""), str(check.get("check_value", "")))
            )

    def _next_id() -> str:
        nonlocal counter
        eid = f"dod-{counter:03d}"
        while eid in existing_ids:
            counter += 1
            eid = f"dod-{counter:03d}"
        counter += 1
        return eid

    # Add test file evidence (skip if already exists for this file)
    for test_file in test_files:
        if ("test_exists", test_file) in existing_checks:
            continue
        evidence.append(
            {
                "id": _next_id(),
                "description": f"Test file exists: {test_file}",
                "source": "generated",
                "linear_dod_text": None,
                "checks": [{"check_type": "test_exists", "check_value": test_file}],
                "status": "pending",
                "evidence_artifact": None,
            }
        )

    # Add test pass evidence (skip if a command check for same command exists)
    if test_files:
        cmd = test_command or f"uv run pytest {' '.join(test_files)} -v"
        if ("command", cmd) not in existing_checks:
            evidence.append(
                {
                    "id": _next_id(),
                    "description": f"All tests pass for {repo}",
                    "source": "generated",
                    "linear_dod_text": None,
                    "checks": [{"check_type": "command", "check_value": cmd}],
                    "status": "pending",
                    "evidence_artifact": None,
                }
            )

    # Add lint evidence (skip if pre-commit check already exists)
    lint_cmd = "pre-commit run --all-files"
    if include_lint and ("command", lint_cmd) not in existing_checks:
        evidence.append(
            {
                "id": _next_id(),
                "description": "Lint and format checks pass",
                "source": "generated",
                "linear_dod_text": None,
                "checks": [{"check_type": "command", "check_value": lint_cmd}],
                "status": "pending",
                "evidence_artifact": None,
            }
        )

    contract["dod_evidence"] = evidence
    return yaml.dump(contract, default_flow_style=False, sort_keys=False)
