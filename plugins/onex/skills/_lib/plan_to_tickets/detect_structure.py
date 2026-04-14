# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""detect_structure() — parse a plan markdown file into structured entries.

Used by the plan-to-tickets skill (SKILL.md Step 2).  Returns a ModelPlanDocument
when omnibase_core >= 0.40 (which adds EnumPlanStructureType.SECTION_HEADINGS).
For omnibase_core == 0.39 the returned object is a _PlanDocumentCompat shim that
exposes the same attribute surface so callers need not branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["detect_structure", "parse_dependencies", "parse_dependency_string"]

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_TASK_RE = re.compile(
    r"^## Task\s+(\d+(?:\.\d+)?):\s*(.+?)$", re.MULTILINE | re.IGNORECASE
)
_PHASE_RE = re.compile(
    r"^## Phase\s+(\d+(?:\.\d+)?):\s*(.+?)$", re.MULTILINE | re.IGNORECASE
)
_SECTION_RE = re.compile(r"^§(\d+(?:\.\d+)*)\s+(.*)", re.MULTILINE)
_H2_RE = re.compile(r"^## ", re.MULTILINE)
_TITLE_RE = re.compile(r"^# (.+?)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Compat shim — matches ModelPlanDocument / ModelPlanEntry surface used in tests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PlanEntryCompat:
    id: str
    title: str
    content: str
    dependencies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _StructureTypeCompat:
    value: str


@dataclass
class _PlanDocumentCompat:
    structure_type: _StructureTypeCompat
    entries: list[_PlanEntryCompat]
    title: str
    source_path: str | None = None

    def entry_by_id(self, entry_id: str) -> _PlanEntryCompat | None:
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None


# ---------------------------------------------------------------------------
# Try to use omnibase_core types; fall back to compat shim if enum is missing
# ---------------------------------------------------------------------------


def _make_doc(
    structure_type_str: str,
    entries_raw: list[dict[str, Any]],
    title: str,
    source_path: str | None,
) -> Any:
    """Build a ModelPlanDocument or a _PlanDocumentCompat."""
    try:
        from omnibase_core.enums.enum_plan_structure_type import EnumPlanStructureType
        from omnibase_core.models.plan.model_plan_document import ModelPlanDocument
        from omnibase_core.models.plan.model_plan_entry import ModelPlanEntry

        structure_enum = EnumPlanStructureType(structure_type_str)
        entries = [
            ModelPlanEntry(
                id=e["id"],
                title=e["title"],
                content=e["content"],
                dependencies=e.get("dependencies", []),
            )
            for e in entries_raw
        ]
        return ModelPlanDocument(
            title=title,
            structure_type=structure_enum,
            entries=entries,
            source_path=source_path,
        )
    except (ImportError, ValueError):
        # omnibase_core does not yet carry the new enum value — use shim
        entries = [
            _PlanEntryCompat(
                id=e["id"],
                title=e["title"],
                content=e["content"],
                dependencies=e.get("dependencies", []),
            )
            for e in entries_raw
        ]
        return _PlanDocumentCompat(
            structure_type=_StructureTypeCompat(value=structure_type_str),
            entries=entries,
            title=title,
            source_path=source_path,
        )


# ---------------------------------------------------------------------------
# Core parsing helpers
# ---------------------------------------------------------------------------


def _extract_title(content: str) -> str:
    m = _TITLE_RE.search(content)
    return m.group(1).strip() if m else "Untitled Plan"


def _extract_numbered_entries(
    matches: list[re.Match[str]],
    keyword: str,
    content: str,
) -> list[dict[str, Any]]:
    """Shared extraction for ## Task N: and ## Phase N: patterns."""
    entries: list[dict[str, Any]] = []
    for i, match in enumerate(matches):
        num = match.group(1)
        entry_id = "P" + num.replace(".", "_")
        title = f"{keyword} {num}: {match.group(2).strip()}"

        start = match.end()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            nxt = _H2_RE.search(content[start:])
            end = start + nxt.start() if nxt else len(content)

        entry_content = content[start:end].strip()
        entries.append(
            {
                "id": entry_id,
                "title": title,
                "content": entry_content,
                "dependencies": parse_dependencies(entry_content),
            }
        )

    # Duplicate ID check
    seen: dict[str, str] = {}
    for entry in entries:
        if entry["id"] in seen:
            raise ValueError(
                f"Duplicate {keyword.lower()} ID '{entry['id']}': "
                f"'{seen[entry['id']]}' and '{entry['title']}'. "
                "Fix plan file to use unique numbers."
            )
        seen[entry["id"]] = entry["title"]

    return entries


def _extract_section_entries(
    matches: list[re.Match[str]],
    content: str,
) -> list[dict[str, Any]]:
    """Extract entries for §N and §N.x headings."""
    entries: list[dict[str, Any]] = []
    for i, match in enumerate(matches):
        num = match.group(1)
        entry_id = "P" + num.replace(".", "_")
        title = f"§{num} {match.group(2).strip()}"

        start = match.end()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(content)

        entry_content = content[start:end].strip()
        entries.append(
            {
                "id": entry_id,
                "title": title,
                "content": entry_content,
                "dependencies": parse_dependencies(entry_content),
            }
        )

    # Duplicate ID check
    seen: dict[str, str] = {}
    for entry in entries:
        if entry["id"] in seen:
            raise ValueError(
                f"Duplicate section ID '{entry['id']}': "
                f"'{seen[entry['id']]}' and '{entry['title']}'. "
                "Fix plan file to use unique numbers."
            )
        seen[entry["id"]] = entry["title"]

    return entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_structure(content: str, source_path: str | None = None) -> Any:
    """Detect plan structure and return a plan document.

    Detection cascade (first match wins):
    1. ## Task N:     → task_sections (canonical)
    2. ## Phase N:    → phase_sections (legacy alias)
    3. §N / §N.x     → section_headings (OMN-8491)
    4. (future arms …)

    Raises ValueError if no valid structure is detected or content is empty/whitespace.
    """
    if not content or not content.strip():
        raise ValueError(
            "no valid structure detected: content is empty. "
            "Plans must use ## Task N: headings (or § headings). Use design-to-plan."
        )

    title = _extract_title(content)

    # 1. ## Task N:
    task_matches = list(_TASK_RE.finditer(content))
    if task_matches:
        entries = _extract_numbered_entries(task_matches, "Task", content)
        return _make_doc("task_sections", entries, title, source_path)

    # 2. ## Phase N:
    phase_matches = list(_PHASE_RE.finditer(content))
    if phase_matches:
        entries = _extract_numbered_entries(phase_matches, "Phase", content)
        return _make_doc("phase_sections", entries, title, source_path)

    # 3. § headings (OMN-8491)
    section_matches = list(_SECTION_RE.finditer(content))
    if section_matches:
        entries = _extract_section_entries(section_matches, content)
        return _make_doc("section_headings", entries, title, source_path)

    raise ValueError(
        "no valid structure detected. "
        "Plans must use ## Task N: headings (or ## Phase N:, or §N headings). "
        "Use design-to-plan to generate a conforming plan."
    )


def parse_dependencies(content: str) -> list[str]:
    """Extract P# or OMN-#### dependencies from a content block."""
    dep_patterns = [
        r"(?:Dependencies|Depends on|Blocked by|Requires):\s*(.+?)(?:\n|$)",
        r"\*\*Dependencies?\*\*:\s*(.+?)(?:\n|$)",
    ]
    for pattern in dep_patterns:
        m = re.search(pattern, content, re.IGNORECASE)
        if m:
            return parse_dependency_string(m.group(1))
    return []


def parse_dependency_string(deps_str: str) -> list[str]:
    """Parse a dependency string into a normalized list of IDs."""
    if not deps_str or deps_str.strip().lower() in ("none", "n/a", "-", ""):
        return []

    deps: list[str] = []
    parts = re.split(r"[,;&]|\band\b", deps_str)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        omn = re.match(r"(OMN-\d+)", part, re.IGNORECASE)
        if omn:
            deps.append(omn.group(1).upper())
            continue

        phase = re.match(r"Phase\s+(\d+(?:\.\d+)?)", part, re.IGNORECASE)
        if phase:
            deps.append("P" + phase.group(1).replace(".", "_"))
            continue

        milestone = re.match(r"(?:Milestone\s+|M)(\d+)", part, re.IGNORECASE)
        if milestone:
            deps.append(f"P{milestone.group(1)}")
            continue

        p = re.match(r"P(\d+(?:[._]\d+)?)", part, re.IGNORECASE)
        if p:
            deps.append("P" + p.group(1).replace(".", "_"))
            continue

    return deps
