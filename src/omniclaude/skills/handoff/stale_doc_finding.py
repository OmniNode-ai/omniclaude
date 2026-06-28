# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Typed stale-doc finding model for the /onex:handoff skill — OMN-13041.

A stale-doc finding records a documentation path that was identified as stale
during a handoff and MUST carry an explicit resolution:
- FIXED:<sha>    — the fix was committed; sha is the commit that closed the debt.
- DEFERRED:<ticket> — the fix is tracked in a Linear ticket; ticket is OMN-XXXX.

Free-text resolutions ("fix opportunistically", TODO, notes) are unrepresentable
in this schema by design: prose debt tracking was the failure mode that C-1 closes.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

# Resolution must match FIXED:<sha> or DEFERRED:<ticket>.
# sha: at least 1 hex char.
# ticket: at least one non-whitespace char (e.g. OMN-1234, PROJ-99).
_RESOLUTION_RE = re.compile(r"^(?:FIXED:[0-9a-f]{1,}|DEFERRED:[A-Za-z0-9]+-[0-9]+)$")


class ModelStaleDocFinding(BaseModel):
    """A single stale-doc finding produced during final handoff (behavior d).

    Attributes:
        doc_path:   Relative or absolute path of the stale documentation file.
        resolution: Typed resolution — must be FIXED:<sha> or DEFERRED:<ticket>.
                    Free text is explicitly rejected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_path: str
    resolution: str

    @field_validator("resolution")
    @classmethod
    def _validate_resolution(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "resolution must not be empty; use FIXED:<sha> or DEFERRED:<ticket>"
            )
        if not _RESOLUTION_RE.match(v):
            raise ValueError(
                f"resolution {v!r} is invalid; must be FIXED:<sha> (hex) or "
                "DEFERRED:<PROJECT-NUM> — free text is not representable"
            )
        return v
