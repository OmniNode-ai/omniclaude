# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20074: required-checks manifest rows after the OCC S6 cut-over."""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / ".github" / "required-checks.yaml"


def test_manifest_drops_the_occ_contexts_for_the_s6_cutover() -> None:
    gates = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))["gates"]
    retired_contexts = {
        "occ-preflight / eligibility",
        "verify / verify",
        "call-reject-skip-token / occ-preflight / eligibility",
    }
    assert not retired_contexts.intersection(row["name"] for row in gates), (
        "the S6 cut-over must remove the retired OCC contexts from the manifest"
    )


def test_manifest_keeps_the_skip_token_scan_required() -> None:
    gates = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))["gates"]
    row = next(
        row
        for row in gates
        if row["name"] == "call-reject-skip-token / scan / reject-skip-gate-token"
    )
    assert row["mode"] == "REQUIRED", "the skip-token scan must remain REQUIRED"


def test_manifest_has_no_repo_evidence_row() -> None:
    gates = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))["gates"]
    assert not any(row["name"].startswith("repo-evidence") for row in gates), (
        "repo-evidence is ruleset-required, not a branch-protection manifest row"
    )
