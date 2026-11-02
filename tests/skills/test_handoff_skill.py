# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the /onex:handoff skill overhaul — OMN-13041.

Verifies:
- SKILL.md is a thin dispatch shim over node_handoff_check_effect (OMN-21910): it calls the
  node through ``onex run-node`` and the skill directory holds no code file and no prompt.md.
- stale_doc_finding.py exposes ModelStaleDocFinding with correct schema validation:
    resolution must be FIXED:<sha> or DEFERRED:<OMN-ticket>, free text is rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from omniclaude.skills.handoff.stale_doc_finding import ModelStaleDocFinding

SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "handoff"
)


# ---------------------------------------------------------------------------
# SKILL.md is a thin shim over node_handoff_check_effect (OMN-21910)
# ---------------------------------------------------------------------------

NODE = "node_handoff_check_effect"


def _skill_text() -> str:
    return (SKILL_DIR / "SKILL.md").read_text()


@pytest.mark.unit
def test_skill_md_frontmatter_parseable() -> None:
    """SKILL.md frontmatter must be valid YAML and not deprecated."""
    text = _skill_text()
    parts = text.split("---", 2)
    assert len(parts) >= 3, "SKILL.md has no valid YAML frontmatter block"
    frontmatter = yaml.safe_load(parts[1])
    assert isinstance(frontmatter, dict)
    assert "DEPRECATED" not in text


@pytest.mark.unit
def test_skill_md_dispatches_the_node_through_run_node() -> None:
    """The skill calls the node through ``onex run-node`` for assemble and resume."""
    text = _skill_text()
    assert f"onex run-node {NODE}" in text
    for command in ('"command": "assemble"', '"command": "resume"'):
        assert command in text


@pytest.mark.unit
def test_skill_directory_holds_no_code_and_no_prompt() -> None:
    """No code file and no prompt.md: the logic lives in the node, not in the skill."""
    names = {
        p.name
        for p in SKILL_DIR.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert "prompt.md" not in names
    assert not {n for n in names if n.endswith((".py", ".sh"))}


@pytest.mark.unit
def test_skill_md_carries_no_terminal_commit_into_the_registry_tree() -> None:
    """The retired terminal commit and docs/handoff target are gone."""
    text = _skill_text()
    assert "git commit" not in text
    assert "docs/handoff" not in text


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
