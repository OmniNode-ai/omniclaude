# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The event_type -> topic mapping of ``hooks/topic_registry.yaml`` (OMN-21623).

``topic_registry.yaml`` is the single home of the omniclaude event type to topic
mapping. A script that audits or exercises those topics names events by event
type and resolves the topic here, so no topic literal sits in code. An event type
the registry does not declare fails with :class:`ValueError`.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "hooks" / "topic_registry.yaml"


class ModelTopicRegistry(BaseModel):
    """The registered event types and their topics.

    Attributes:
        source: Path of the registry the mapping was read from.
        topics_by_event_type: Event type (``session.started``) -> topic string.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Path
    topics_by_event_type: dict[str, str]

    @classmethod
    def from_path(cls, path: Path) -> ModelTopicRegistry:
        """Read a registry file; it must carry a ``topics`` list."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = raw.get("topics") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            raise ValueError(f"{path}: no 'topics' list")
        return cls(
            source=path,
            topics_by_event_type={
                entry["event_type"]: entry["topic"]
                for entry in entries
                if isinstance(entry, dict)
                and isinstance(entry.get("event_type"), str)
                and isinstance(entry.get("topic"), str)
            },
        )

    @classmethod
    def default(cls) -> ModelTopicRegistry:
        """The registry shipped with the omniclaude package."""
        return cls.from_path(_REGISTRY_PATH)

    def topic(self, event_type: str) -> str:
        """The topic of one event type; an undeclared event type fails to resolve."""
        try:
            return self.topics_by_event_type[event_type]
        except KeyError:
            raise ValueError(
                f"{self.source}: event type {event_type!r} is not declared"
            ) from None

    def topics(self, *event_types: str) -> list[str]:
        """The topics of several event types, in the order given."""
        return [self.topic(event_type) for event_type in event_types]
