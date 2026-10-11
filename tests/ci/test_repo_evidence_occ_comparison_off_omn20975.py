# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20975: end the completed S5 comparison before the S6 cut-over."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

CALLER = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/call-repo-evidence-gate.yml"
)

# Captured from the refreshed dev merge base, 3228efa0de4728392ab16a2b59079989af1857ba.
# A literal snapshot works in the reusable's exported merge-base control too;
# it does not depend on a second clone or on shallow checkout history.
BASE_USES = (
    "OmniNode-ai/omnibase_core/.github/workflows/receipt-gate.yml@"
    "4e4f5e0404d364e296c5d37db6aa3ab9e07f8ffa"
)
BASE_OTHER_INPUTS = {
    "evidence-source": "caller",
    "verifier-version": "0.4.310",
    "shadow": "true",
}
# The base's exact bytes, excluding its S5 comment block and normalizing only
# the comparison input. This covers every other workflow line, comments included.
BASE_REMAINDER_SHA256 = (
    "91015a18ddfc0e173776d62f5dbaa5fc417639c3ad6fc92c4e4f1c22d687c628"
)


def test_dev_caller_stops_comparing_with_occ() -> None:
    job = yaml.safe_load(CALLER.read_text(encoding="utf-8"))["jobs"]["repo-evidence"]
    assert job["with"]["compare-with-occ"] == "false", (
        "the completed S5 comparison must end on dev before S6 removes its producer"
    )


def test_every_other_caller_line_matches_the_merge_base() -> None:
    text = CALLER.read_text(encoding="utf-8")
    job = yaml.safe_load(text)["jobs"]["repo-evidence"]
    other_inputs = {
        key: value for key, value in job["with"].items() if key != "compare-with-occ"
    }
    assert other_inputs == BASE_OTHER_INPUTS
    assert job["uses"] == BASE_USES
    remainder = re.sub(
        r"(?ms)^# S5 shadow count .*?(?=^# The reusable is pinned by full SHA\.)",
        "",
        text,
    ).replace('      compare-with-occ: "true"', '      compare-with-occ: "false"')
    assert hashlib.sha256(remainder.encode()).hexdigest() == BASE_REMAINDER_SHA256
