# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20975: end the completed S5 comparison before the S6 cut-over."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CALLER_PATH = ".github/workflows/call-repo-evidence-gate.yml"
CALLER = ROOT / CALLER_PATH
# Verified with git merge-base at the reviewed PR head. Keep this immutable so
# merging the precursor does not turn its regression's base into the new head.
MERGE_BASE = "3228efa0de4728392ab16a2b59079989af1857ba"
# CI checks the head out at depth 1, so the merge-base commit's tree is not in
# the runner's clone and git show cannot read the base caller there. The test
# carries the base caller byte for byte instead, pinned to the blob git records
# for it: git rev-parse <MERGE_BASE>:<CALLER_PATH>.
MERGE_BASE_BLOB = "b5c491e812bed12f48c912748541e51d217886da"
BASE_TEXT = """\
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Repo Evidence Gate caller (OMN-20073, OCC retirement OR.5) verifies
# omniclaude's own contracts/<OMN-N>.yaml at the PR head through
# omnibase_core's receipt-gate reusable with evidence-source: caller.
# This is the path omnimarket proved as the canary (OMN-20070, OMN-20072).
#
# Why pull_request_target: GitHub reads the workflow definition from the BASE
# branch, so a pull request that edits this file or the reusable's pin does not
# change which definition runs on it. The pull request's own code is only ever
# checked out as data by the reusable, which refuses fork heads.
#
# dev and main are the integration branches. The activity types cover new heads,
# reopened and ready PRs, and edits to the ticket citation or base branch.
# Per-PR concurrency cancels superseded runs so the latest event gets a verdict.
# Read-only contents and pull-requests permissions are all this caller needs;
# checkout and verification belong to the reusable, with no caller secrets.
# The full-SHA pin makes the reusable immutable; verifier-version pins the
# released verifier used to read the caller's contracts.
#
# The job id is the context prefix: repo-evidence / dod-verify carries the
# verdict, so do not add a job name.
#
# S5 shadow count (OMN-20073): shadow and compare-with-occ are both "true", so
# every run records this head's new-path verdict beside OCC's occ-preflight /
# eligibility verdict on the same head, and no job concludes anything but
# success. omniclaude's CI Summary L5 sweep fails any external check-run whose
# conclusion is not success, so a skipped repo-evidence / verify or a refused
# repo-evidence / dod-verify would red every pull request. In shadow mode the
# reusable runs verify as a reported no-op and dod-verify absorbs a refusal,
# then writes one `Shadow verdict:` line (new_path, the first refused step, the
# OCC difference outcome and reason) to the job summary and to a notice
# annotation, the data the S5 count reads. No sweep exclusion is needed or
# allowed for these contexts. repo-evidence / dod-verify is NOT a required
# context here yet. Every OCC context stays required. Making it required, and
# then removing the OCC contexts (S6), are separate rulings that wait for this
# repository's own S5 bar. The S6 change sets shadow and compare-with-occ back
# to "false".
#
# The reusable is pinned by full SHA. It must be a commit that carries the
# shadow input and, for the S5 count, the contract-home marker of
# omnibase_core#1912: with compare-with-occ "true" the head step names the
# repository that holds a ticket's only other contract, and verifier 0.4.305
# (omnimarket#3563) classifies that refusal as contract_in_another_repo instead
# of unclassified (OMN-20074, rulings 2026-10-08T09:57:41Z and 14:59:17Z). The
# pin is the squash commit of omnibase_core#1932 on dev, the one omnimarket's
# caller uses. It descends from #1914 and hands a writer app diff that only
# moves the omnibase_core checkout pin (#1927) or only bumps a .claude-plugin
# manifest version (#1931) to the pinned verifier's classifiers, and refuses a
# verifier-version below 0.4.303. verifier-version 0.4.310 is the first
# omnimarket release that ships both classifiers (omnimarket#3694); it also
# carries omnimarket#3751, so a contract that repeats a mapping key is refused.
# omniclaude does not host receipt-gate.yml.

name: Repo Evidence Gate

on:
  pull_request_target:
    types: [opened, synchronize, reopened, edited, ready_for_review]
    branches: [dev, main]

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number }}
  cancel-in-progress: true

permissions:
  contents: read
  pull-requests: read

jobs:
  repo-evidence:
    uses: OmniNode-ai/omnibase_core/.github/workflows/receipt-gate.yml@4e4f5e0404d364e296c5d37db6aa3ab9e07f8ffa # OMN-20074: the squash commit of omnibase_core#1932 on dev (descends from #1914; writer app workflow-pin and plugin version bump classification, verifier floor)
    with:
      evidence-source: caller
      verifier-version: 0.4.310
      compare-with-occ: "true"
      shadow: "true"
"""


def git_blob_id(text: str) -> str:
    data = text.encode("utf-8")
    header = b"blob %d\0" % len(data)
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


@pytest.fixture(scope="module")
def base_text() -> str:
    assert git_blob_id(BASE_TEXT) == MERGE_BASE_BLOB, (
        f"BASE_TEXT must be {CALLER_PATH} exactly as it is at {MERGE_BASE}"
    )
    return BASE_TEXT


def test_embedded_base_is_the_merge_base_caller() -> None:
    assert git_blob_id(BASE_TEXT) == MERGE_BASE_BLOB
    # A one-line edit to the embedded base is a different blob, so a hand-edited
    # base cannot stand in for the real one.
    edited = BASE_TEXT.replace('compare-with-occ: "true"', 'compare-with-occ: "false"')
    assert edited != BASE_TEXT
    assert git_blob_id(edited) != MERGE_BASE_BLOB


def assert_comparison_off(caller: dict[str, Any]) -> None:
    assert caller["jobs"]["repo-evidence"]["with"]["compare-with-occ"] == "false", (
        "the completed S5 comparison must end on dev before S6 removes its producer"
    )


@pytest.mark.parametrize("source", ["merge-base", "head"])
def test_dev_caller_stops_comparing_with_occ(source: str, base_text: str) -> None:
    if source == "merge-base":
        # The same assertion must reject the actual base caller, not a missing test.
        with pytest.raises(AssertionError, match="completed S5 comparison must end"):
            assert_comparison_off(yaml.safe_load(base_text))
    else:
        assert_comparison_off(yaml.safe_load(CALLER.read_text(encoding="utf-8")))


def s5_comment(text: str) -> tuple[list[str], list[str]]:
    comments = [line for line in text.splitlines() if line.startswith("#")]
    (start,) = (
        index
        for index, line in enumerate(comments)
        if line.startswith("# S5 shadow count ")
    )
    end = comments.index(
        "# The reusable is pinned by full SHA. It must be a commit that carries the"
    )
    assert start < end
    return comments[start:end], comments[:start] + comments[end:]


def test_every_other_caller_line_matches_the_merge_base(base_text: str) -> None:
    text = CALLER.read_text(encoding="utf-8")
    head = yaml.safe_load(text)
    base = yaml.safe_load(base_text)
    base_job = base["jobs"]["repo-evidence"]
    head_job = head["jobs"]["repo-evidence"]
    assert base_job["with"]["compare-with-occ"] == "true"
    assert_comparison_off(head)
    assert head_job["uses"] == base_job["uses"]
    assert [line for line in text.splitlines() if line.strip().startswith("uses:")] == [
        line for line in base_text.splitlines() if line.strip().startswith("uses:")
    ]
    pin = head_job["uses"].rsplit("@", 1)[1]
    assert len(pin) == 40 and all(char in "0123456789abcdef" for char in pin)
    expected_job = deepcopy(base_job)
    expected_job["with"]["compare-with-occ"] = "false"
    assert head_job == expected_job
    expected = deepcopy(base)
    expected["jobs"]["repo-evidence"] = expected_job
    assert head == expected

    head_s5, head_comments = s5_comment(text)
    base_s5, base_comments = s5_comment(base_text)
    assert head_comments == base_comments
    assert 'shadow and compare-with-occ are both "true"' in base_s5[0]
    assert head_s5[:4] == [
        "# S5 shadow count ended before the S6 cut-over (OMN-20975). compare-with-occ",
        '# is "false" on dev so the base-branch caller no longer waits for OCC\'s',
        "# occ-preflight / eligibility verdict after omniclaude#2614 removes its producer.",
        '# shadow stays "true" until that S6 cut-over. No job concludes anything but',
    ]
    assert head_s5[-3:] == [
        '# repository\'s own S5 bar. The S6 change sets shadow to "false"; the comparison',
        "# already ended in this precursor.",
        "#",
    ]
    assert head_s5[4:10] == base_s5[3:9]
    assert head_s5[10:12] == [
        "# annotation. No sweep exclusion is needed or",
        base_s5[10],
    ]
    assert head_s5[12:-3] == base_s5[11:-3]
