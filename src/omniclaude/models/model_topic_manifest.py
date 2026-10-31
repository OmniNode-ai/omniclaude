# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A ``topics.yaml`` manifest that declares the topics a module addresses (OMN-21623).

A module that publishes to or consumes a topic reads the name from the
``topics.yaml`` beside it instead of spelling the topic in code. The manifest is a
mapping of sections to ``name: topic`` pairs. A section or name the manifest does
not declare fails with :class:`ValueError`, so a rename surfaces at load time and
never leaves a module governing a topic that does not exist.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class ModelTopicManifest(BaseModel):
    """The sections of one ``topics.yaml`` file, keyed by section then topic name.

    Attributes:
        source: Path of the manifest the sections were read from.
        sections: Section name -> topic name -> topic string.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Path
    sections: dict[str, dict[str, str]]

    @classmethod
    def from_path(cls, path: Path) -> ModelTopicManifest:
        """Read a manifest; every section must be a mapping of strings to strings."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: a topics manifest is a mapping of sections")
        sections: dict[str, dict[str, str]] = {}
        for section, entries in raw.items():
            if not isinstance(entries, dict) or not all(
                isinstance(name, str) and isinstance(topic, str)
                for name, topic in entries.items()
            ):
                raise ValueError(
                    f"{path}: section {section!r} must map names to topics"
                )
            sections[str(section)] = dict(entries)
        return cls(source=path, sections=sections)

    @classmethod
    def beside(cls, module_file: str) -> ModelTopicManifest:
        """Read the ``topics.yaml`` that sits next to ``module_file``."""
        return cls.from_path(Path(module_file).resolve().with_name("topics.yaml"))

    def get(self, section: str, name: str) -> str:
        """The topic declared as ``name`` in ``section``; undeclared fails to resolve."""
        try:
            return self.sections[section][name]
        except KeyError:
            raise ValueError(
                f"{self.source}: no topic {name!r} in section {section!r}"
            ) from None

    @staticmethod
    def topic_of(module_file: str, node: str) -> str:
        """The topic ``node``'s contract declares under ``event_bus.subscribe``.

        ``module_file`` is a module of the package whose ``nodes`` directory holds the node.
        """
        contract = (
            Path(module_file).resolve().parents[1] / "nodes" / node / "contract.yaml"
        )
        data = yaml.safe_load(contract.read_text(encoding="utf-8"))
        return str(data["event_bus"]["subscribe"]["topic"])
