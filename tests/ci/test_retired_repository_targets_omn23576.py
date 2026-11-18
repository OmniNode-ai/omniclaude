# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""No live list in omniclaude names a retired repository (OMN-23576).

The host reconcile unit refuses to run while a registry list, sync script or
source constant in a checkout names a retired repository. The check reads
non-comment lines from paths that previously held live entries.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RETIRED_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(onex[_-]change[_-]control|omnibase[_-]compat|ycbench[_-]onex)"
    r"(?![A-Za-z0-9_.-])"
)
RETIRED_PACKAGE_RE = re.compile(r"omnibase[_-]compat")

LIVE_LIST_FILES = (
    "scripts/apply_branch_protection.sh",
    "scripts/verify_branch_protection.sh",
    "scripts/check_infra_coupling.py",
    "scripts/cron-merge-sweep.sh",
    "scripts/cron-quick-merge.sh",
    "scripts/lib/run-unstick-queue.py",
    "src/omniclaude/coverage/scanner.py",
    "src/omniclaude/handlers/handler_internal_sibling_pins.py",
    "src/omniclaude/hooks/pre_tool_use_workflow_guard.py",
    "src/omniclaude/hooks/self_healing_orchestrator.py",
)

PACKAGE_LIST_FILES = (
    "architecture-handshakes/validator-requirements.yaml",
    "plugins/onex/skills/_bin/_lib/armed_not_enqueued.py",
    "plugins/onex/skills/_bin/lab-onboarding.sh",
    "scripts/check_dep_provenance.py",
    "src/omniclaude/hooks/pre_tool_use_dispatch_mode_guardrail.py",
)


def _live_lines(text: str) -> list[int]:
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if not line.lstrip().startswith("#") and RETIRED_RE.search(line)
    ]


def test_positive_control_the_matcher_sees_a_live_entry_and_skips_a_comment() -> None:
    assert _live_lines('REPOS = ["omnibase_compat"]\n') == [1]
    assert _live_lines('  "omnibase-compat": "omnibase_compat",\n') == [1]
    assert _live_lines("# onex_change_control narrates the retirement\n") == []
    assert _live_lines('REPOS = ["omnibase_core"]\n') == []


@pytest.mark.parametrize("relative", LIVE_LIST_FILES)
def test_live_list_names_no_retired_repository(relative: str) -> None:
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert _live_lines(text) == [], f"{relative} names a retired repository"


@pytest.mark.parametrize("relative", LIVE_LIST_FILES)
def test_live_list_keeps_its_active_repositories(relative: str) -> None:
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert "omnibase_core" in text or "omnibase-core" in text


@pytest.mark.parametrize("relative", PACKAGE_LIST_FILES)
def test_live_list_excludes_the_retired_package(relative: str) -> None:
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert RETIRED_PACKAGE_RE.search(text) is None, (
        f"{relative} names the retired package"
    )
