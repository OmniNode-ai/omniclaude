# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the /onex:handoff skill overhaul — OMN-13041.

Verifies:
- SKILL.md exists and is NOT marked deprecated; description covers the 6 enforcement
  behaviors (claim-certification, supersession, terminal-commit, stale-doc schema,
  scorecard, deep-dive reconcile).
- prompt.md exists and contains the required execution sections.
- stale_doc_finding.py exposes ModelStaleDocFinding with correct schema validation:
    resolution must be FIXED:<sha> or DEFERRED:<OMN-ticket>, free text is rejected.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from omniclaude.skills.handoff.stale_doc_finding import ModelStaleDocFinding

SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "handoff"
)


# ---------------------------------------------------------------------------
# SKILL.md structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_skill_md_exists() -> None:
    """SKILL.md must be present."""
    assert (SKILL_DIR / "SKILL.md").exists(), "handoff/SKILL.md is missing"


@pytest.mark.unit
def test_skill_md_not_deprecated() -> None:
    """SKILL.md must not contain a DEPRECATED notice — the skill is now active."""
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert "DEPRECATED" not in content, (
        "SKILL.md still carries a DEPRECATED notice; the overhaul should remove it"
    )


@pytest.mark.unit
def test_skill_md_frontmatter_parseable() -> None:
    """SKILL.md frontmatter must be valid YAML."""
    text = (SKILL_DIR / "SKILL.md").read_text()
    parts = text.split("---", 2)
    assert len(parts) >= 3, "SKILL.md has no valid YAML frontmatter block"
    fm = yaml.safe_load(parts[1])
    assert isinstance(fm, dict), "Frontmatter must be a YAML mapping"
    assert "description" in fm, "Frontmatter must have a description field"


@pytest.mark.unit
def test_skill_md_covers_claim_certification() -> None:
    """SKILL.md must document claim-certification lint (behavior a)."""
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert re.search(r"claim[- ]certif", content, re.IGNORECASE), (
        "SKILL.md missing claim-certification section"
    )


@pytest.mark.unit
def test_skill_md_covers_supersession() -> None:
    """SKILL.md must document supersession handling (behavior b)."""
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert re.search(r"supersess", content, re.IGNORECASE), (
        "SKILL.md missing supersession section"
    )


@pytest.mark.unit
def test_skill_md_covers_terminal_commit() -> None:
    """SKILL.md must document terminal commit+push requirement (behavior c)."""
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert re.search(r"terminal.{0,30}commit", content, re.IGNORECASE) or re.search(
        r"commit.{0,30}push", content, re.IGNORECASE
    ), "SKILL.md missing terminal commit+push section"


@pytest.mark.unit
def test_skill_md_covers_stale_doc_schema() -> None:
    """SKILL.md must document typed stale-doc findings (behavior d)."""
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert re.search(r"stale.doc", content, re.IGNORECASE) or re.search(
        r"FIXED:", content
    ), "SKILL.md missing typed stale-doc findings section"


@pytest.mark.unit
def test_skill_md_covers_scorecard() -> None:
    """SKILL.md must document live-gh-query scorecard (behavior e)."""
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert re.search(r"scorecard", content, re.IGNORECASE), (
        "SKILL.md missing scorecard section"
    )


@pytest.mark.unit
def test_skill_md_covers_deep_dive_reconcile() -> None:
    """SKILL.md must document deep-dive reconcile (behavior f)."""
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert re.search(r"deep.div", content, re.IGNORECASE), (
        "SKILL.md missing deep-dive reconcile section"
    )


# ---------------------------------------------------------------------------
# prompt.md structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prompt_md_exists() -> None:
    """prompt.md must be present."""
    assert (SKILL_DIR / "prompt.md").exists(), "handoff/prompt.md is missing"


@pytest.mark.unit
def test_prompt_md_has_scorecard_command() -> None:
    """prompt.md must contain a gh CLI call to generate the scorecard."""
    content = (SKILL_DIR / "prompt.md").read_text()
    assert "gh " in content, "prompt.md must reference a gh CLI command for scorecard"


@pytest.mark.unit
def test_prompt_md_has_commit_push_step() -> None:
    """prompt.md must mention git commit and push for terminal commit+push."""
    content = (SKILL_DIR / "prompt.md").read_text()
    assert "git commit" in content or "git push" in content, (
        "prompt.md must include terminal commit+push step"
    )


@pytest.mark.unit
def test_prompt_md_references_stale_doc_schema() -> None:
    """prompt.md must reference FIXED:<sha> or DEFERRED:<ticket> pattern."""
    content = (SKILL_DIR / "prompt.md").read_text()
    assert "FIXED:" in content or "DEFERRED:" in content, (
        "prompt.md must document the FIXED:<sha>|DEFERRED:<ticket> schema"
    )


# ---------------------------------------------------------------------------
# ModelStaleDocFinding Pydantic model
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_model_stale_doc_finding_importable() -> None:
    """stale_doc_finding.py must be importable and expose ModelStaleDocFinding."""
    assert ModelStaleDocFinding.__name__ == "ModelStaleDocFinding"


@pytest.mark.unit
def test_model_valid_fixed_resolution() -> None:
    """FIXED:<sha> resolution must be accepted."""
    finding = ModelStaleDocFinding(
        doc_path="docs/architecture/CLAUDE.md",
        resolution="FIXED:a1b2c3d",
    )
    assert finding.resolution == "FIXED:a1b2c3d"


@pytest.mark.unit
def test_model_valid_deferred_resolution() -> None:
    """DEFERRED:<ticket> resolution must be accepted."""
    finding = ModelStaleDocFinding(
        doc_path="docs/architecture/CLAUDE.md",
        resolution="DEFERRED:OMN-9999",
    )
    assert finding.resolution == "DEFERRED:OMN-9999"


@pytest.mark.unit
def test_model_rejects_free_text_resolution() -> None:
    """Free-text resolution like 'fix opportunistically' must be rejected."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelStaleDocFinding(
            doc_path="docs/architecture/CLAUDE.md",
            resolution="fix opportunistically",
        )


@pytest.mark.unit
def test_model_rejects_empty_resolution() -> None:
    """Empty resolution must be rejected."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelStaleDocFinding(
            doc_path="docs/architecture/CLAUDE.md",
            resolution="",
        )


@pytest.mark.unit
def test_model_rejects_bare_fixed() -> None:
    """FIXED: without a sha must be rejected."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelStaleDocFinding(
            doc_path="docs/architecture/CLAUDE.md",
            resolution="FIXED:",
        )


@pytest.mark.unit
def test_model_rejects_bare_deferred() -> None:
    """DEFERRED: without a ticket must be rejected."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelStaleDocFinding(
            doc_path="docs/architecture/CLAUDE.md",
            resolution="DEFERRED:",
        )


@pytest.mark.unit
def test_model_is_frozen() -> None:
    """ModelStaleDocFinding must be immutable (frozen=True)."""
    finding = ModelStaleDocFinding(
        doc_path="docs/foo.md",
        resolution="FIXED:abc1234",
    )
    with pytest.raises(Exception):
        finding.doc_path = "docs/bar.md"  # type: ignore[misc]
