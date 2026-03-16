# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""DoD Parser — extract Definition of Done items from ticket descriptions.

Parses markdown-style DoD sections from Linear ticket descriptions and
classifies each bullet into executable check types for the dod_evidence[]
schema on ModelTicketContract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Heading patterns that indicate a DoD section
_DOD_HEADINGS = re.compile(
    r"^#+\s*(?:definition\s+of\s+done|dod|acceptance\s+criteria)\s*$",
    re.IGNORECASE,
)

# Pattern for markdown checklist items: - [ ] or - [x]
_CHECKLIST_ITEM = re.compile(r"^\s*[-*]\s*\[[ xX]?\]\s*(.+)$")

# Classification keyword patterns (case-insensitive)
_TEST_KEYWORDS = re.compile(
    r"\b(?:tests?\s+(?:added|passing|exist|written|created)|unit\s+tests?|"
    r"test\s+coverage|pytest)\b",
    re.IGNORECASE,
)
_ENDPOINT_KEYWORDS = re.compile(
    r"\b(?:api\s+returns|endpoint|responds?\s+with|status\s+(?:code\s+)?\d{3}|"
    r"health\s+check|http)\b",
    re.IGNORECASE,
)
_FILE_KEYWORDS = re.compile(
    r"\b(?:file\s+(?:created|exists|added)|config\s+file|"
    r"(?:created?|added?)\s+(?:a\s+)?file)\b",
    re.IGNORECASE,
)
_COMMAND_KEYWORDS = re.compile(
    r"\b(?:mypy|ruff|lint|format|type[\s-]?check|pre-commit|passes)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DodCheckSpec:
    """A single check specification extracted from DoD text."""

    check_type: str
    check_value: str | dict[str, str]


@dataclass(frozen=True)
class DodItemSpec:
    """A single DoD item extracted from ticket description."""

    id: str
    description: str
    source: str
    linear_dod_text: str
    checks: list[DodCheckSpec] = field(default_factory=list)


def classify_dod_item(text: str) -> DodCheckSpec:
    """Classify a DoD bullet text into a check type and value.

    Applies heuristic keyword matching to determine the most appropriate
    check type. Falls back to a manual command placeholder for unclassifiable
    items.

    Args:
        text: The raw DoD bullet text.

    Returns:
        A DodCheckSpec with the classified check type and value.

    """
    stripped = text.strip()

    if _TEST_KEYWORDS.search(stripped):
        return DodCheckSpec(check_type="test_exists", check_value="tests/")

    if _ENDPOINT_KEYWORDS.search(stripped):
        return DodCheckSpec(check_type="endpoint", check_value=stripped)

    if _FILE_KEYWORDS.search(stripped):
        return DodCheckSpec(check_type="file_exists", check_value="**/*")

    if _COMMAND_KEYWORDS.search(stripped):
        # Try to extract the actual command from the text
        return DodCheckSpec(check_type="command", check_value=stripped)

    # Fallback: manual verification placeholder
    return DodCheckSpec(
        check_type="command",
        check_value=f'echo "MANUAL: {stripped}" && exit 1',
    )


def extract_dod_items(description: str) -> list[DodItemSpec]:
    """Extract DoD items from a ticket description.

    Scans the description for DoD/Acceptance Criteria headings, then
    extracts checklist items under those headings. Each item is classified
    into an executable check type.

    Args:
        description: The full ticket description text (markdown).

    Returns:
        List of DodItemSpec, one per DoD bullet found. Empty if no DoD
        section is present.

    """
    if not description:
        return []

    lines = description.split("\n")
    in_dod_section = False
    items: list[DodItemSpec] = []
    counter = 0

    for line in lines:
        # Check if this line starts a DoD section
        if _DOD_HEADINGS.match(line.strip()):
            in_dod_section = True
            continue

        # If we hit another heading while in DoD section, stop
        if in_dod_section and line.strip().startswith("#"):
            in_dod_section = False
            continue

        if not in_dod_section:
            continue

        # Try to match checklist items
        match = _CHECKLIST_ITEM.match(line)
        if match:
            counter += 1
            text = match.group(1).strip()
            check = classify_dod_item(text)

            items.append(
                DodItemSpec(
                    id=f"dod-{counter:03d}",
                    description=text,
                    source="linear",
                    linear_dod_text=text,
                    checks=[check],
                )
            )

    return items
