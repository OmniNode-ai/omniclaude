# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Request and result of the internal-sibling-pins check (OMN-21282)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_sibling_pin_kind import EnumSiblingPinKind
from omniclaude.enums.enum_sibling_pin_verdict import EnumSiblingPinVerdict


class ModelInternalSiblingPinsRequest(BaseModel):
    """Two lock files and the dev merge tags each sibling repository carries.

    Attributes:
        head_lock_text: ``uv.lock`` as the change leaves it.
        base_lock_text: ``uv.lock`` before the change; ``None`` judges every pin.
        dev_tags: Sibling repository name to its tag names, as read from the
            repository. A repository missing here was not read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    head_lock_text: str
    base_lock_text: str | None = None
    dev_tags: dict[str, list[str]] = Field(default_factory=dict)


class ModelInternalSiblingPinFinding(BaseModel):
    """One internal sibling pin in the head lock and the verdict on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    distribution: str
    repo: str
    version: str
    kind: EnumSiblingPinKind
    moved: bool
    released_at: str | None = None
    newest_dev_tag: str | None = None
    verdict: EnumSiblingPinVerdict
    reason: str


class ModelInternalSiblingPinsResult(BaseModel):
    """Every internal sibling pin judged, and the repositories still unread."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: list[ModelInternalSiblingPinFinding]
    repos_needing_tags: list[str]

    @property
    def refused(self) -> list[ModelInternalSiblingPinFinding]:
        return [f for f in self.findings if f.verdict is EnumSiblingPinVerdict.REFUSED]

    @property
    def passed(self) -> bool:
        return not self.refused


__all__ = [
    "ModelInternalSiblingPinFinding",
    "ModelInternalSiblingPinsRequest",
    "ModelInternalSiblingPinsResult",
]
