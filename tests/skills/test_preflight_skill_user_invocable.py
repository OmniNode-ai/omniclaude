# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The preflight skill is reachable and is a shim over the runner [OMN-18368].

The skill declared ``user_invocable: false``, said in its body that it was
callable from the session orchestrator only, and named a replacement skill that
performs no preflight. The check bodies lived there and nowhere else, so nobody
could run them.

This module pins the three properties that make it an interface again:

1. it is user-invocable and takes an ``--intent`` argument;
2. it is a **shim** — it names the runner and carries no inline check recipe, so
   the check bodies have exactly one home;
3. it carries no organization-specific check content, which now lives in the
   overlay the runner loads.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "plugins" / "onex" / "skills" / "preflight" / "SKILL.md"
_RUNNER_REL = "plugins/onex/scripts/session_preflight.py"


def _frontmatter() -> dict[str, object]:
    text = _SKILL.read_text()
    assert text.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    _, block, _ = text.split("---\n", 2)
    loaded = yaml.safe_load(block)
    assert isinstance(loaded, dict)
    return loaded


def test_skill_is_user_invocable() -> None:
    fm = _frontmatter()
    assert fm.get("user_invocable") is True, (
        "The preflight skill is the only path from a person to the check bodies. "
        "Declaring it non-invocable is what made them unreachable."
    )


def test_skill_no_longer_names_a_replacement() -> None:
    fm = _frontmatter()
    assert "replacement_skill" not in fm, (
        "A skill that is the interface has no replacement; the previous value "
        "pointed at a skill that performs no preflight."
    )


def test_skill_declares_the_intent_argument() -> None:
    fm = _frontmatter()
    names = {a.get("name") for a in fm.get("args", []) if isinstance(a, dict)}
    assert "--intent" in names, f"declared args: {sorted(n for n in names if n)}"


def test_skill_documents_all_three_intents() -> None:
    body = _SKILL.read_text()
    for intent in ("quiet", "normal", "tick"):
        assert intent in body, f"the {intent} intent is undocumented"


def test_skill_names_the_runner() -> None:
    assert _RUNNER_REL in _SKILL.read_text(), (
        "A prose skill is a thin wrapper over one command; it must name it."
    )


def test_skill_carries_no_inline_check_recipe() -> None:
    """The check bodies have one home, and it is not this file.

    The previous body carried a repository list, a shell loop per check and its
    own verdict banner. Re-homing them into the runner is the change; a copy
    left behind here is a second source of truth that drifts.
    """
    body = _SKILL.read_text()
    for leak in (
        "KNOWLEDGE_BASE_INTERNAL_PATH",
        "OVERNIGHT_DRIVE_PATH",
        "LINEAR_API_KEY",
        "OmniNode-ai/",
        "gh pr list",
    ):
        assert leak not in body, (
            f"The skill body still carries {leak!r}. Check content belongs in "
            f"the overlay the runner loads, not in the public skill body."
        )


def test_skill_names_the_overlay_variable() -> None:
    assert "SESSION_PREFLIGHT_OVERLAY_PATH" in _SKILL.read_text(), (
        "A reader whose run refuses for want of an overlay must learn the "
        "variable name from the skill, not from a traceback."
    )
