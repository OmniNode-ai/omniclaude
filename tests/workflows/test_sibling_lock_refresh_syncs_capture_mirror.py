# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The sibling-lock refresh re-derives the capture-contract mirror at the pin it writes (OMN-17427).

``sibling-lock-refresh.yml`` advances the clone-governed omnimarket git rev
(OMN-18752). That rev is also the rev the Registry Consistency job reads
omnimarket at (OMN-20001: ``steps.om_pin`` greps it out of ``uv.lock``), and at
that rev the job compares ``src/omniclaude/hooks/contracts/capture_redaction.yaml``
against omnimarket's owning copy (OMN-18357). The refresh moved the pin and left
the mirror behind, so any bump past an omnimarket commit that changed the owning
contract opened a bot PR that was red on Registry Consistency by construction:
omniclaude#2770 moved ``cc90cce4`` -> ``0143496c`` across omnimarket's OMN-18946
change and failed on exactly ``capture_redaction.yaml has drifted ... ['topics']``.

The repair already exists (``generate_event_registry.py --sync-capture-contract``);
the refresh never ran it. These tests pin that it does, at the rev the lock pins
rather than at the clone head, and that the re-derived mirror rides in the same
commit as the lock it belongs to.
"""

from __future__ import annotations

import re
import runpy
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sibling-lock-refresh.yml"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DAEMON_REGISTRY = (
    ".clones/omnimarket/src/omnimarket/nodes/node_emit_daemon/registries/topics.yaml"
)


def _mirror_relpath() -> str:
    generator = runpy.run_path(
        str(REPO_ROOT / "scripts" / "validation" / "generate_event_registry.py")
    )
    mirror: Path = generator["VENDORED_CAPTURE_CONTRACT"]
    return str(mirror.relative_to(REPO_ROOT))


def _steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = doc["jobs"]["refresh"]["steps"]
    return steps


def _index(steps: list[dict[str, Any]], needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in str(s.get("run", ""))]
    assert len(hits) == 1, f"expected exactly one step running {needle!r}, got {hits}"
    return hits[0]


def _sync_step(steps: list[dict[str, Any]]) -> tuple[int, str]:
    i = _index(steps, "--sync-capture-contract")
    return i, str(steps[i]["run"])


def test_refresh_runs_the_mirror_sync_against_the_omnimarket_clone() -> None:
    _, run = _sync_step(_steps())
    assert "scripts/validation/generate_event_registry.py" in run
    assert f"--daemon-registry {DAEMON_REGISTRY}" in run or (
        f'--daemon-registry "{DAEMON_REGISTRY}"' in run
    )


def test_sync_runs_after_the_lock_is_written_and_before_the_delta() -> None:
    steps = _steps()
    sync, _ = _sync_step(steps)
    # OMN-19998: the dev-tag train step also runs relock_git_sources.py; the
    # clone-governed relock is the one naming omnimarket.
    relock = _index(steps, "--package omnimarket")
    uv_lock = _index(steps, 'uv lock "${ARGS[@]}"')
    delta = _index(steps, "git diff --quiet")
    assert relock < uv_lock < sync < delta, (relock, uv_lock, sync, delta)


def test_sync_reads_omnimarket_at_the_rev_the_lock_pins() -> None:
    """The mirror must match the rev Registry Consistency reads, not the clone head.

    relock_git_sources.py refuses a non-descendant candidate and then leaves the
    pin where it was; a sync from the clone head in that case would write a
    mirror for a rev the lock does not pin, and the bot PR would be red the other
    way round.
    """
    _, run = _sync_step(_steps())
    ci_text = CI.read_text(encoding="utf-8")
    pin_grep = "grep -oE 'omnimarket\\.git\\?rev=[0-9a-f]{40}' uv.lock"
    assert pin_grep in ci_text, "ci.yml's om_pin resolution moved; re-point this test"
    assert pin_grep in run
    assert re.search(
        r"git -C \.clones/omnimarket (-c [^ ]+ )*checkout[^\n]*\$\{?rev", run
    )


def test_the_mirror_is_part_of_the_delta_and_the_commit() -> None:
    steps = _steps()
    mirror = _mirror_relpath()
    delta = str(steps[_index(steps, "git diff --quiet")]["run"])
    commit = str(steps[_index(steps, "git commit")]["run"])
    assert mirror in delta, "a mirror-only re-derivation would be reported as no change"
    assert re.search(rf"git add [^\n]*{re.escape(mirror)}", commit)


def test_pr_step_is_gated_on_the_delta_step() -> None:
    steps = _steps()
    delta = steps[_index(steps, "git diff --quiet")]
    pr = steps[_index(steps, "gh pr create")]
    assert delta.get("id"), "the delta step needs an id the PR step can read"
    # OMN-19998: a train dry run also holds the PR step back.
    assert str(pr.get("if")).startswith(
        f"steps.{delta['id']}.outputs.changed == 'true'"
    )
