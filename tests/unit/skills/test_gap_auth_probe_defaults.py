# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Static tests for gap auth probe default documentation (OMN-9068).

These tests do not run auth probes or touch credentials. They only validate
the skill shim contract that is passed through to node_gap_compute.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GAP_DIR = _REPO_ROOT / "plugins" / "onex" / "skills" / "gap"
_GAP_SKILL = _GAP_DIR / "SKILL.md"
_GAP_PROMPT = _GAP_DIR / "prompt.md"


def _frontmatter(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---")
    parts = content.split("---", 2)
    assert len(parts) >= 3, "Frontmatter not properly delimited"
    return yaml.safe_load(parts[1])


@pytest.mark.unit
def test_skill_frontmatter_exposes_auth_probe_opt_out() -> None:
    fm = _frontmatter(_GAP_SKILL)
    arg_names = [arg["name"] for arg in fm["args"]]

    assert "--include-auth-probes" in arg_names
    assert "--no-include-auth-probes" in arg_names

    descriptions = {arg["name"]: arg.get("description", "") for arg in fm["args"]}
    assert "default: true" in descriptions["--include-auth-probes"]
    assert "Disable auth_config probes" in descriptions["--no-include-auth-probes"]


@pytest.mark.unit
def test_prompt_documents_auth_probe_default_and_opt_out() -> None:
    prompt = _GAP_PROMPT.read_text(encoding="utf-8")

    assert (
        "`--include-auth-probes` | Include auth_config probes (default: true" in prompt
    )
    assert "`--no-include-auth-probes` | Disable auth_config probes" in prompt
    assert "Auth probes are included by default" in prompt


@pytest.mark.unit
def test_gap_docs_do_not_regress_to_auth_probes_disabled_by_default() -> None:
    combined = "\n".join(
        [
            _GAP_SKILL.read_text(encoding="utf-8"),
            _GAP_PROMPT.read_text(encoding="utf-8"),
        ]
    )

    assert not re.search(r"\|\s*`--include-auth-probes`\s*\|\s*false\b", combined)
    assert "disabled by default" not in combined.lower()
