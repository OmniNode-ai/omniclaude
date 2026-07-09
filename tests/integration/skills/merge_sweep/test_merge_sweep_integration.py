# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration-scope contract for the migrated /onex:merge_sweep dispatch shim.

OMN-13097 Phase 4a migrated merge_sweep (like every dispatch shim) to the
single-command pattern: ``uv run onex skill merge_sweep`` printing one typed
``ModelSkillResult``. The pre-migration ``onex run-node`` envelope-construction
contract is gone, and the skill directory carries no executable logic
(``_lib/run.py``/``run.sh`` removed). These assertions are the integration-scope
twin of ``tests/unit/skills/test_dispatch_skill_receipt_contract.py`` for the
merge_sweep skill specifically, keeping the CI merge-sweep-contract gate green.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_SKILL_DIR = (
    Path(__file__).resolve().parents[4] / "plugins" / "onex" / "skills" / "merge_sweep"
)
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_PROMPT_MD = _SKILL_DIR / "prompt.md"


def _frontmatter(text: str) -> dict:
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", "SKILL.md must open with frontmatter"
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    return yaml.safe_load("\n".join(lines[1:end]))


@pytest.mark.unit
class TestMergeSweepSingleCommandShim:
    def test_skill_and_prompt_exist(self) -> None:
        assert _SKILL_MD.is_file()
        assert _PROMPT_MD.is_file()

    def test_skill_md_declares_dispatch_kind(self) -> None:
        fm = _frontmatter(_SKILL_MD.read_text())
        assert fm.get("skill_kind") == "dispatch"

    def test_prompt_has_no_frontmatter(self) -> None:
        first = _PROMPT_MD.read_text().splitlines()[0].strip()
        assert first != "---", "prompt.md procedure body deleted; no frontmatter"

    def test_single_onex_skill_command(self) -> None:
        combined = _SKILL_MD.read_text() + "\n" + _PROMPT_MD.read_text()
        assert re.search(
            r'cd\s+"\$OMNI_HOME/omnibase_infra"\s+&&\s+uv\s+run\s+onex\s+skill\s+merge_sweep\b',
            combined,
        ), "merge_sweep must invoke `uv run onex skill merge_sweep` from omnibase_infra"

    def test_no_bare_runtime_dispatch_in_bash(self) -> None:
        combined = _SKILL_MD.read_text() + "\n" + _PROMPT_MD.read_text()
        bash = "\n".join(re.findall(r"```bash\n(.*?)```", combined, re.DOTALL))
        assert not re.search(r"\bonex\s+(?:run-node|run|node)\b", bash), (
            "bare onex run/node/run-node dispatch forbidden in receipt-mode shim"
        )

    def test_no_inline_gh_or_kafka(self) -> None:
        combined = _SKILL_MD.read_text() + "\n" + _PROMPT_MD.read_text()
        assert "gh pr merge" not in combined
        assert "kcat" not in combined

    def test_directory_has_no_executable_logic(self) -> None:
        offenders = [
            str(p.relative_to(_SKILL_DIR))
            for p in _SKILL_DIR.rglob("*")
            if "__pycache__" not in p.parts
            and (
                (p.is_file() and p.suffix in {".py", ".sh"})
                or (p.is_dir() and p.name == "_lib")
            )
        ]
        assert not offenders, f"merge_sweep must be markdown-only, found {offenders}"
