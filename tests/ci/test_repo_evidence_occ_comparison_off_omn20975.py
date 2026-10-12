# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20975: end the completed S5 comparison before the S6 cut-over."""

from __future__ import annotations

import os
import subprocess
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


@pytest.fixture(scope="module")
def base_text() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{MERGE_BASE}:{CALLER_PATH}"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        timeout=5,
        env={"PATH": os.defpath},
    ).stdout


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
