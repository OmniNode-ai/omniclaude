# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The retro prose skill reviews one session and plugs into the friction machinery (OMN-26381).

The tests read the skill file and the distribution manifest and assert what the
ticket's acceptance criteria name. They define no behaviour of their own: the
friction row shape, the friction thresholds and the ticket rules stay in the
skills that own them, so one test asserts that the retro skill restates none.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_PATH = Path("plugins/onex/skills/retro/SKILL.md")
MANIFEST = Path("plugins/distribution_manifest.yaml")

SOURCE_URL = "github.com/mattpocock/skills"

# The permission paragraphs of the MIT licence of the source repository, as given.
PERMISSION_NOTICE = """\
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

CATEGORIES: tuple[str, ...] = ("navigation", "missing automated check", "standard")


def _text() -> str:
    assert SKILL_PATH.is_file(), f"{SKILL_PATH} does not exist"
    return SKILL_PATH.read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _worked_example(text: str) -> str:
    start = text.find("## Worked example")
    assert start != -1, "no '## Worked example' section"
    rest = text[start + 1 :]
    nxt = re.search(r"^## ", rest, re.MULTILINE)
    return text[start : start + 1 + (nxt.start() if nxt else len(rest))]


def _kind(finding: str) -> str:
    match = re.search(r"^\*\*Kind\*\*:\s*(.+)$", finding, re.MULTILINE)
    assert match, "no Kind line"
    return match.group(1).strip().lower().rstrip(".")


def _findings(example: str) -> list[str]:
    return [c for c in re.split(r"^### ", example, flags=re.MULTILINE)[1:] if c.strip()]


@pytest.mark.unit
def test_retro_notice_credits_the_source_and_carries_the_licence() -> None:
    text = _text()
    assert "MIT License" in text
    assert re.search(r"Copyright \(c\) 2026 \S+ \S+", text), "no copyright line"
    assert SOURCE_URL in text
    assert _squash(PERMISSION_NOTICE) in _squash(text)


@pytest.mark.unit
def test_retro_notice_positive_control() -> None:
    """A text with the paragraph cut short is reported as missing the notice."""
    cut = _squash(_text()).replace("OR OTHER DEALINGS IN THE SOFTWARE.", "")
    assert _squash(PERMISSION_NOTICE) not in cut


@pytest.mark.unit
def test_retro_categories_and_write_routes() -> None:
    text = _text()
    lowered = text.lower()
    for category in CATEGORIES:
        assert category in lowered, f"category missing: {category}"
    # A mechanical error gets a deterministic check before a written rule.
    assert "deterministic check" in lowered
    assert re.search(r"mechanical", lowered)
    assert re.search(
        r"prefer[^.]*over\s+writing\s+a\s+(written\s+)?(rule|standard)", lowered
    )
    # The repository's own check command is read first.
    assert "check command" in lowered
    # Both write routes.
    assert "friction-record" in text
    assert "onex ticket create" in text
    assert "create-ticket" in text


@pytest.mark.unit
def test_retro_plugs_into_friction_skills_and_restates_no_format() -> None:
    text = _text()
    assert "friction_triage" in text
    assert "friction-record" in text
    assert "record_friction" in text
    # No row grammar, no count threshold, no severity weights of its own.
    assert not re.search(r"\|\s*FRICTION\s*\|", text)
    assert not re.search(r"\bcost=", text)
    assert not re.search(r"(count|score)\s*(>=|≥|>)\s*\d", text)
    assert not re.search(r"severity_score", text)
    assert not re.search(
        r"\b(threshold|crosses)\b[^.\n]*\b\d+\s*(times|occurrences)", text
    )


@pytest.mark.unit
def test_retro_plugs_in_positive_control() -> None:
    """The absence checks would fire on a text that did restate a row grammar."""
    bad = "2026-01-01T00:00:00Z | FRICTION | lane=x | cost=~5 lane-minutes | text"
    assert re.search(r"\|\s*FRICTION\s*\|", bad)
    assert re.search(r"\bcost=", bad)
    assert re.search(r"(count|score)\s*(>=|≥|>)\s*\d", "file a ticket when count >= 3")


@pytest.mark.unit
def test_retro_worked_example_holds_three_findings_each_with_a_kind_and_reason() -> (
    None
):
    example = _worked_example(_text())
    findings = _findings(example)
    assert len(findings) == 3, [f.splitlines()[0] for f in findings]
    topics = (
        ("parked", "bottom-layer"),
        ("swap",),
        ("pool",),
    )
    for finding, words in zip(findings, topics, strict=True):
        head = finding.splitlines()[0].lower()
        for word in words:
            assert word in head, f"{word!r} not in heading {head!r}"
        kind = re.search(r"^\*\*Kind\*\*:\s*(.+)$", finding, re.MULTILINE)
        assert kind, f"no Kind line under {head!r}"
        assert kind.group(1).strip().lower().rstrip(".") in CATEGORIES
        assert re.search(r"^\*\*Why this kind\*\*:", finding, re.MULTILINE)
        assert re.search(r"^\*\*What happened\*\*:", finding, re.MULTILINE)
        assert re.search(r"^\*\*Would be written\*\*:", finding, re.MULTILINE)
    # The two hypotheses of the brief that the rows confirmed or changed are stated.
    kinds = [_kind(f) for f in findings]
    assert "missing automated check" in kinds
    assert "navigation" in kinds


@pytest.mark.unit
def test_retro_worked_example_missing_finding_is_detected() -> None:
    """Positive control: a worked example with two findings fails the count."""
    example = _worked_example(_text())
    two = example.rsplit("### ", 1)[0]
    assert len(_findings(two)) == 2


@pytest.mark.unit
def test_retro_skill_names_no_private_host_path_or_repository() -> None:
    text = _text()
    for pattern in (
        r"\bh\d{3}\b",
        r"\b[A-Z][A-Z_]{8,}\.md\b",
        r"/Users/",
        r"/home/",
        r"-internal\b",
        r"\b192\.168\.",
    ):
        assert not re.search(pattern, text), pattern


@pytest.mark.unit
def test_retro_manifest_row_classifies_the_skill() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    entries = [c for c in manifest["components"] if c["id"] == "retro"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "skill"
    assert entry["surface_class"] == "pure_skill"
    assert entry["path"] == "plugins/onex/skills/retro/SKILL.md"
    assert entry["backing_nodes"] == []
    assert "OMN-26381" in entry["rationale"]
