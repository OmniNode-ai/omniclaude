# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Request, finding and result of the whole-file hygiene leg (OMN-22273)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_validate_skills_compute.enums.enum_scrub_map_key_kind import (
    EnumScrubMapKeyKind,
)
from omniclaude.nodes.node_validate_skills_compute.enums.enum_whole_file_hygiene_outcome import (
    EnumWholeFileHygieneOutcome,
)


class ModelScrubMapRow(BaseModel):
    """One private value class of the retirement plan's scrub table.

    Attributes:
        row_id: Stable id of the plan table row.
        description: The value class in neutral words (never a private value).
        finding_classes: Hygiene-gate classes whose findings this row explains.
        kind: What the value becomes.
        keys: The overlay keys or environment variables it becomes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_id: str
    description: str
    finding_classes: tuple[str, ...] = ()
    kind: EnumScrubMapKeyKind
    keys: tuple[str, ...] = ()


class ModelScrubMap(BaseModel):
    """The scrub map data file, parsed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows: tuple[ModelScrubMapRow, ...]

    def keys_for_class(self, class_name: str) -> tuple[str, ...]:
        """Every key a finding of ``class_name`` becomes, in row order."""
        keys: list[str] = []
        for row in self.rows:
            if class_name in row.finding_classes:
                keys.extend(k for k in row.keys if k not in keys)
        return tuple(keys)


class ModelWholeFileHygieneRequest(BaseModel):
    """One run of the leg over a scope directory.

    Attributes:
        repo_root: The checkout the leg scans and whose gate it uses.
        scope_dir: Directory under ``repo_root`` scanned whole-file.
        vocabulary: The private denylist vocabulary. ``None`` reads
            ``OMNI_HYGIENE_VOCAB_PATH``; with neither the leg is a config error.
        lab_vocabulary: The private lab vocabulary. ``None`` reads the file of
            the gate's name beside ``vocabulary``.
        model_vocabulary: The private model vocabulary for the deployment-config
            run. ``None`` reads the file of the gate's name beside ``vocabulary``.
        scrub_map: The scrub map data file. ``None`` reads the repo's own.
        gate_script: The hygiene gate. ``None`` reads the repo's own.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_root: Path
    scope_dir: str = "plugins/omni"
    vocabulary: Path | None = None
    lab_vocabulary: Path | None = None
    model_vocabulary: Path | None = None
    scrub_map: Path | None = None
    gate_script: Path | None = None


class ModelWholeFileFinding(BaseModel):
    """One finding. The line's text is never carried: a public log must not repeat it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    line_no: int
    class_name: str
    becomes: tuple[str, ...] = ()


class ModelWholeFileHygieneResult(BaseModel):
    """The leg's verdict. ``error`` is set exactly when the outcome is CONFIG_ERROR."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: EnumWholeFileHygieneOutcome
    files_scanned: int = 0
    findings: tuple[ModelWholeFileFinding, ...] = Field(default_factory=tuple)
    error: str | None = None

    @property
    def exit_code(self) -> int:
        return self.outcome.exit_code
