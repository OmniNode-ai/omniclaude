# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The repository's prose documentation lives in the knowledge base (OMN-17427 AC46).

The removed documentation files stay removed, the root README.md links the
knowledge base, and the convention files that ``conventions/routes.yaml``
routes to stay, because ``file_path_router`` loads them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_REMOVED_DOCS = (
    "CHANGELOG.md",
    ".github/CONTRIBUTING.md",
    ".github/CODE_OF_CONDUCT.md",
    "plugins/onex/README.md",
    "plugins/onex/GETTING_STARTED.md",
    "plugins/onex/skills/gap/docs/POST_MERGE_STABILIZATION.md",
)

_ROUTED_CONVENTIONS = ("omniclaude-hooks", "omnidash-server", "onex-contracts")


@pytest.mark.unit
@pytest.mark.parametrize("relpath", _REMOVED_DOCS)
def test_removed_doc_is_absent(relpath: str) -> None:
    assert not (_REPO_ROOT / relpath).exists(), relpath


@pytest.mark.unit
def test_gap_skill_does_not_name_removed_doc() -> None:
    text = (_REPO_ROOT / "plugins/onex/skills/gap/SKILL.md").read_text(encoding="utf-8")
    assert "POST_MERGE_STABILIZATION" not in text


@pytest.mark.unit
@pytest.mark.parametrize("name", _ROUTED_CONVENTIONS)
def test_routed_convention_file_is_kept(name: str) -> None:
    conventions = _REPO_ROOT / "plugins/onex/hooks/conventions"
    assert f'"{name}"' in (conventions / "routes.yaml").read_text(encoding="utf-8")
    assert (conventions / f"{name}.md").is_file(), name


@pytest.mark.unit
def test_root_readme_links_knowledge_base() -> None:
    text = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/OmniNode-ai/knowledge-base" in text
