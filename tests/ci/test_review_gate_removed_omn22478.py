# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22478, operator RULING 2026-11-05T20:27:56Z: no automated review holds a merge.

A head with no reviewer row must pass CI Summary's external layers, the reviewer must start no run on a pull request, and the manifest must not call its
context required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.ci import ci_summary_gate as gate

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 5, 21, 0, 0, tzinfo=UTC)
REVIEW_CONTEXTS = (
    "Hostile Reviewer (adversarial gate)",
    "Hostile Review Gate",
    "Hostile Review Thread Gate",
)


def _row(name: str, conclusion: str) -> dict[str, object]:
    return {
        "id": abs(hash(name)) % 10_000_000,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": "2026-11-05T20:00:00Z",
        "completed_at": "2026-11-05T20:05:00Z",
        "head_sha": "a" * 40,
    }


def test_a_head_with_no_reviewer_row_passes_the_external_layers() -> None:
    names = (*gate.EXPECTED_EXTERNAL_CONTEXTS, *gate.ALL_MUST_SUCCEED_EXTERNAL_NAMES)
    rows = [_row(name, "success") for name in names]
    verdict, failures, pending = gate.evaluate_external(rows, now=NOW)
    assert (verdict, failures, pending) == ("SUCCESS", [], [])
    swept_failures, _, _, _ = gate.evaluate_external_sweep(rows, now=NOW)
    assert swept_failures == []


def test_no_review_context_is_asserted() -> None:
    assert not set(REVIEW_CONTEXTS) & set(gate.EXPECTED_EXTERNAL_CONTEXTS)
    assert not set(REVIEW_CONTEXTS) & set(gate.ALL_MUST_SUCCEED_EXTERNAL_NAMES)


def test_the_manifest_does_not_call_a_review_context_required() -> None:
    manifest = yaml.safe_load((REPO / ".github/required-checks.yaml").read_text())
    required = {g["name"] for g in manifest["gates"] if g.get("mode") == "REQUIRED"}
    assert not set(REVIEW_CONTEXTS) & required


def test_the_reviewer_starts_no_run_on_a_pull_request() -> None:
    data: dict[Any, Any] = yaml.safe_load(
        (REPO / ".github/workflows/hostile-reviewer.yml").read_text()
    )
    triggers = data.get("on", data.get(True))
    assert not {"pull_request", "pull_request_target", "merge_group"} & set(triggers)


def test_the_queue_mirrors_no_review_context() -> None:
    data: dict[Any, Any] = yaml.safe_load(
        (REPO / ".github/workflows/merge-group-pr-scoped-contexts.yml").read_text()
    )
    names = {job.get("name") for job in data["jobs"].values()}
    assert not set(REVIEW_CONTEXTS) & names
