# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one definition of an internal sibling's dev merge tag (OMN-19972).

Every dev merge of a sibling gets this tag from its own dev-merge-tag.yml
(RULINGs 2026-10-16T07:34:18Z and 2026-10-16T09:35:49Z). Imported by
scripts/check_dep_provenance.py, scripts/relock_git_sources.py (the nightly
dev-tag train) and handler_internal_sibling_pins; stdlib only because the
dep-provenance gate and the sibling-lock-refresh workflow run a bare python3
with PYTHONPATH=src.
tests/unit/handlers/test_handler_dev_merge_tag_omn19972.py holds it equal to
omnibase_core's contracts/internal_sibling_pins.yaml dev_tag_pattern.
"""

import re
from typing import Final

DEV_MERGE_TAG_PATTERN: Final = r"^dev-(?P<stamp>[0-9]{14})-[0-9a-f]{12}$"
_DEV_MERGE_TAG: Final = re.compile(DEV_MERGE_TAG_PATTERN)


def dev_merge_tag_stamp(tag: str) -> str | None:
    """Return the 14-digit stamp when tag is a dev merge tag, else None."""
    match = _DEV_MERGE_TAG.fullmatch(tag)
    return match.group("stamp") if match else None


def is_dev_merge_tag(tag: str) -> bool:
    """Return whether tag is a dev merge tag."""
    return dev_merge_tag_stamp(tag) is not None


__all__ = ["DEV_MERGE_TAG_PATTERN", "dev_merge_tag_stamp", "is_dev_merge_tag"]
