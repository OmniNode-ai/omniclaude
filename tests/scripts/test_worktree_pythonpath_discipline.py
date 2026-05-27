# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-11422: Verify that worktree Python invocation rules carry the env -u PYTHONPATH guard.

Background
----------
omniclaude hook scripts export PYTHONPATH into the Claude Code session environment so that
Python modules in plugins/onex/hooks/lib/ are importable. That value propagates to every
subprocess spawned by the Claude Code agent, including `uv run pytest`, `uv run python`, and
bare `python3` calls made inside git worktrees.

In a worktree the local src/ layout differs from the canonical clone (and from the hooks/lib
path that was injected into PYTHONPATH). Without clearing PYTHONPATH first, Python resolves
imports from the hook-export path instead of the worktree's own src/, causing silent import
shadowing and hard-to-diagnose test failures.

The canonical fix is: prefix every Python invocation inside a worktree with env -u PYTHONPATH.

These tests assert that the key surfaces (dispatch_worker operating rules and the shared
skill_orchestrator_template) document this requirement, and that common.sh carries the
explanatory comment pointing agents at the correct pattern.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent

DISPATCH_WORKER_PROMPT = "plugins/onex/skills/dispatch_worker/prompt.md"
DISPATCH_WORKER_SKILL = "plugins/onex/skills/dispatch_worker/SKILL.md"
SKILL_ORCHESTRATOR_TEMPLATE = (
    "plugins/onex/skills/_shared/skill_orchestrator_template.md"
)
COMMON_SH = "plugins/onex/hooks/scripts/common.sh"

# The canonical worktree pytest command that both skill files must contain.
_WORKTREE_PYTEST_PATTERN = re.compile(
    r"env\s+-u\s+PYTHONPATH\s+uv\s+run\s+pytest",
    re.MULTILINE,
)

# The note in common.sh that explains the propagation risk to agents.
_COMMON_SH_OMN_ANNOTATION = "OMN-11422"


@pytest.mark.unit
def test_dispatch_worker_prompt_uses_env_u_pythonpath_for_pytest() -> None:
    """dispatch_worker/prompt.md operating rules must prescribe env -u PYTHONPATH uv run pytest."""
    text = (REPO_ROOT / DISPATCH_WORKER_PROMPT).read_text()
    assert _WORKTREE_PYTEST_PATTERN.search(text), (
        f"{DISPATCH_WORKER_PROMPT}: operating rule 4 must use "
        "`env -u PYTHONPATH uv run pytest` (not bare `uv run pytest`). "
        "Hook scripts export PYTHONPATH which shadows worktree src/ — "
        "see OMN-11422."
    )


@pytest.mark.unit
def test_dispatch_worker_skill_uses_env_u_pythonpath_for_pytest() -> None:
    """dispatch_worker/SKILL.md operating rules must prescribe env -u PYTHONPATH uv run pytest."""
    text = (REPO_ROOT / DISPATCH_WORKER_SKILL).read_text()
    assert _WORKTREE_PYTEST_PATTERN.search(text), (
        f"{DISPATCH_WORKER_SKILL}: operating rule 4 must use "
        "`env -u PYTHONPATH uv run pytest` (not bare `uv run pytest`). "
        "SKILL.md and prompt.md must stay in sync — see OMN-11422."
    )


@pytest.mark.unit
def test_skill_orchestrator_template_uses_env_u_pythonpath_for_pytest() -> None:
    """skill_orchestrator_template.md worker checklist must include env -u PYTHONPATH for pytest."""
    text = (REPO_ROOT / SKILL_ORCHESTRATOR_TEMPLATE).read_text()
    assert _WORKTREE_PYTEST_PATTERN.search(text), (
        f"{SKILL_ORCHESTRATOR_TEMPLATE}: worker self-verification checklist must use "
        "`env -u PYTHONPATH uv run pytest` — see OMN-11422."
    )


@pytest.mark.unit
def test_common_sh_documents_worktree_pythonpath_rule() -> None:
    """common.sh must carry the OMN-11422 annotation explaining the worktree PYTHONPATH hazard."""
    text = (REPO_ROOT / COMMON_SH).read_text()
    assert _COMMON_SH_OMN_ANNOTATION in text, (
        f"{COMMON_SH}: must contain a comment referencing OMN-11422 that explains why "
        "env -u PYTHONPATH is required for Python invocations inside worktrees."
    )


@pytest.mark.unit
def test_dispatch_worker_prompt_and_skill_operating_rules_agree() -> None:
    """prompt.md and SKILL.md must both carry the same env -u PYTHONPATH pytest instruction.

    These two files are kept in sync manually. If one is updated without the other, worker
    prompts compiled by node_dispatch_worker will carry different rules than documented.
    """
    prompt_text = (REPO_ROOT / DISPATCH_WORKER_PROMPT).read_text()
    skill_text = (REPO_ROOT / DISPATCH_WORKER_SKILL).read_text()
    prompt_has_guard = bool(_WORKTREE_PYTEST_PATTERN.search(prompt_text))
    skill_has_guard = bool(_WORKTREE_PYTEST_PATTERN.search(skill_text))
    assert prompt_has_guard == skill_has_guard, (
        "dispatch_worker/prompt.md and dispatch_worker/SKILL.md are out of sync: "
        f"prompt.md env -u PYTHONPATH guard present={prompt_has_guard}, "
        f"SKILL.md env -u PYTHONPATH guard present={skill_has_guard}. "
        "Both files must carry the same operating rule 4 text."
    )
