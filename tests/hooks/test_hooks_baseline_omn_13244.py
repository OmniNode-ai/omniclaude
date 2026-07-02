# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression guard for the OMN-13244 measurement baseline (OMN-13846).

Context: OMN-13835 (PR #1831) auto-merged despite a hold and restored the full
onex hook surface, destroying the deliberate OMN-13244 measurement baseline
(``{"hooks": {}}``). The disabled hooks are context-injection hooks whose
latency/usefulness is being measured -- they must stay disabled until an
explicit operator decision re-registers them.

These tests lock in the baseline so an accidental re-enable is caught by CI:

1. ``plugins/onex/hooks/hooks.json`` carries an EMPTY ``hooks`` object while
   retaining the ``$schema`` / ``description`` / ``version`` metadata keys.
2. The skill-substitution guard machinery (module, config YAML, wrapper
   script, tests) REMAINS on disk -- unregistered, so activating it later is
   a one-line config add and an explicit operator decision, not a code
   restore.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent
_HOOKS_JSON = _REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json"

# Skill-substitution guard machinery that must remain on disk (unregistered).
_GUARD_FILES = (
    "plugins/onex/hooks/scripts/pre_tool_use_skill_substitution_guard.sh",
    "src/omniclaude/hooks/pre_tool_use_skill_substitution_guard.py",
    "src/omniclaude/hooks/raw_command_to_skill.yaml",
    "tests/unit/hooks/test_pre_tool_use_skill_substitution_guard.py",
)


def test_hooks_json_is_empty_measurement_baseline() -> None:
    """hooks.json must carry an empty ``hooks`` object (OMN-13244 baseline).

    Every hook registration is intentionally removed so Claude Code invokes no
    onex hooks. Re-enabling is an explicit operator decision, not an accidental
    revert.
    """
    data = json.loads(_HOOKS_JSON.read_text())
    assert data.get("hooks") == {}, (
        "plugins/onex/hooks/hooks.json must carry an EMPTY 'hooks' object for the "
        "OMN-13244 measurement baseline. A non-empty 'hooks' object means the "
        "disabled context-injection hooks were re-registered without an explicit "
        f"operator decision (see OMN-13846). Found: {data.get('hooks')!r}"
    )


def test_hooks_json_retains_metadata_keys() -> None:
    """The baseline keeps the $schema/description/version metadata keys."""
    data = json.loads(_HOOKS_JSON.read_text())
    for key in ("$schema", "description", "version"):
        assert key in data, f"hooks.json baseline missing metadata key: {key!r}"


@pytest.mark.parametrize("rel_path", _GUARD_FILES)
def test_skill_substitution_guard_machinery_remains_on_disk(rel_path: str) -> None:
    """Guard files must remain on disk (unregistered) for a one-line re-enable.

    Disabling in hooks.json must NOT delete the skill-substitution guard
    machinery -- keeping it on disk means activating the guard later is a
    pure config change (register in hooks.json) and an explicit operator
    decision.
    """
    path = _REPO_ROOT / rel_path
    assert path.is_file(), (
        f"Skill-substitution guard file missing: {rel_path}. The OMN-13244 baseline "
        "unregisters the guard but must retain its machinery on disk so re-enabling "
        "is a one-line config add (see OMN-13846)."
    )
