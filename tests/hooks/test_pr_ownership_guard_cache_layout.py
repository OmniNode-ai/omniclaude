# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""End-to-end cache-layout tests for pre_tool_use_pr_ownership_guard.sh (OMN-16983).

The OMN-16485 guard shipped importing ``plugins.onex.hooks.lib.*`` by absolute
package path, and its shell wrapper ran Python with ``cd $PLUGIN_ROOT/../..``
plus ``PYTHONPATH=$PLUGIN_ROOT/../..``.  Both silently assume the SOURCE layout
``<omniclaude>/plugins/onex``, where ``../..`` is the repo root and ``plugins``
is an importable package.

Claude Code does not load hooks from that tree.  It loads them from the plugin
CACHE, ``~/.claude/plugins/cache/<marketplace>/onex/<version>/hooks/...``, which
has NO ``plugins/`` ancestor.  There ``../..`` is the marketplace directory,
``import plugins`` raises ``ModuleNotFoundError``, the decision core exits 1,
and the wrapper's fail-closed branch refuses the command.  On 2026-08-29 that
refused every ``gh api`` call on this host — read-only GETs included — for
every concurrent lane.

These tests stage the plugin into a temp CACHE-layout tree and drive the real
``.sh`` over stdin exactly as Claude Code does.  They are the falsifier for
OMN-16983 AC1-AC3:

* AC1 — a read-only ``gh api ... --jq`` GET passes through (RED before the fix).
* AC2 — an evaluation error on a genuine mutation verb still BLOCKS (fail-closed
  preserved); proven by breaking the registry module the mutation path needs.
* AC3 — the gate still DISCRIMINATES under the cache layout: a cross-lane
  ``gh api -X PATCH .../pulls/N -f state=closed`` blocks while the same command
  against a PR this lane actively claims is allowed.  A guard that blocks
  everything (the pre-fix behaviour) fails the allow half.

Falsifier discipline: every pass-through assertion is paired with a block
assertion driven through the same wrapper, so deleting the ownership check turns
these RED rather than leaving a vacuous green.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_HOOKS = _REPO_ROOT / "plugins" / "onex" / "hooks"
_SCRIPT_RELPATH = Path("hooks") / "scripts" / "pre_tool_use_pr_ownership_guard.sh"

#: Synthetic version segment. Deliberately NOT the real plugin version: what
#: this test fixes is the tree SHAPE (``onex/<ver>/hooks/...`` with no
#: ``plugins/`` ancestor), and coupling it to plugin.json would make a routine
#: version bump look like a semantic change here.
_CACHE_VERSION = "0.0.0-test"

LANE_SELF = "lane-alpha"
LANE_PEER = "lane-beta"

_READ_ONLY_GET = "gh api repos/OmniNode-ai/omni_home --jq .name"
_QUOTED_LITERAL = "printf '%s\\n' 'gh api repos/OmniNode-ai/omni_home --jq .name'"


def _cross_lane_patch(number: int = 2019) -> str:
    return (
        f"gh api -X PATCH repos/OmniNode-ai/omniclaude/pulls/{number} -f state=closed"
    )


def _pr_key(number: int = 2019) -> str:
    return f"omninode-ai/omniclaude#{number}"


def _stage_cache_layout(tmp: Path) -> Path:
    """Stage plugins/onex into ``<tmp>/onex/<ver>/`` — the plugin-cache shape.

    Returns the staged plugin root.  Critically, no ancestor of the staged tree
    is named ``plugins``, so ``import plugins.onex.hooks.lib.X`` cannot resolve
    — which is exactly the production condition this guard has to survive.
    """
    plugin_root = tmp / "cache" / "omninode-tools-dev" / "onex" / _CACHE_VERSION
    plugin_root.mkdir(parents=True)
    shutil.copytree(
        _SOURCE_HOOKS,
        plugin_root / "hooks",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    assert "plugins" not in set(plugin_root.parts), (
        "staged tree must NOT have a `plugins` ancestor — that is the whole point"
    )
    return plugin_root


def _make_project_dir(tmp: Path) -> Path:
    """A directory ``is_omninode_repo()`` accepts, so the guard does not bail early."""
    project = tmp / "omni_home"
    project.mkdir(parents=True)
    (project / "CLAUDE.md").write_text("OmniNode omniclaude registry\n")
    (project / ".onex_state").mkdir()
    return project


def _write_claim(state_dir: Path, pr_key: str, *, lane_id: str) -> Path:
    claims_dir = state_dir / "pr-queue" / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = claims_dir / f"{pr_key.replace('/', '--').replace('#', '--')}.json"
    path.write_text(
        json.dumps(
            {
                "pr_key": pr_key,
                "claimed_by_run": "run-1",
                "claimed_by_host": "host-1",
                "claimed_by_instance_id": "inst-1",
                "claimed_at": stamp,
                "last_heartbeat_at": stamp,
                "action": "close",
                "lane_id": lane_id,
            }
        )
    )
    return path


def _run(
    command: str,
    plugin_root: Path,
    project_dir: Path,
    state_dir: Path,
    home: Path,
    *,
    lane_id: str = LANE_SELF,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # All hooks on: neutralize any ambient mask that disables BASH_GUARD.
    env.pop("ONEX_HOOKS_MASK", None)
    env.pop("PROJECT_ROOT", None)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["ONEX_REGISTRY_ROOT"] = str(project_dir)
    env["ONEX_STATE_DIR"] = str(state_dir)
    env["HOME"] = str(home)
    env["ONEX_LANE_ID"] = lane_id
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run(
        ["bash", str(plugin_root / _SCRIPT_RELPATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=str(project_dir),
        env=env,
    )


class _Bed:
    """One staged cache-layout bed: plugin root, project dir, state dir, HOME."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.plugin_root = _stage_cache_layout(tmp)
        self.project_dir = _make_project_dir(tmp)
        self.state_dir = tmp / "state"
        self.state_dir.mkdir(parents=True)
        self.home = tmp / "home"
        self.home.mkdir(parents=True)

    def run(self, command: str, *, lane_id: str = LANE_SELF):
        return _run(
            command,
            self.plugin_root,
            self.project_dir,
            self.state_dir,
            self.home,
            lane_id=lane_id,
        )

    def break_registry(self) -> None:
        """Make the claims registry unimportable — forces an evaluation error."""
        (self.plugin_root / "hooks" / "lib" / "pr_claim_registry.py").write_text(
            'raise RuntimeError("OMN-16983 test: registry deliberately broken")\n'
        )


def _assert_passthrough(result: subprocess.CompletedProcess[str], command: str) -> None:
    assert result.returncode == 0, (
        f"expected pass-through for {command!r} under the cache layout; "
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert '"decision"' not in result.stdout, (
        f"pass-through must echo the tool payload, not a decision: {result.stdout}"
    )
    assert json.loads(result.stdout)["tool_input"]["command"] == command


def _assert_blocked(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 2, (
        f"expected a hard block (exit 2); rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    return str(decision["reason"])


# ---------------------------------------------------------------------------
# AC1 — read-only gh api passes through under the cache layout
# ---------------------------------------------------------------------------


def test_read_only_gh_api_get_passes_under_cache_layout() -> None:
    """`gh api <path> --jq` carries no mutating method — it must never be refused.

    RED before OMN-16983: the decision core dies on `import plugins` and the
    wrapper's fail-closed branch turns a GET into a block.
    """
    with tempfile.TemporaryDirectory() as td:
        bed = _Bed(Path(td))
        _assert_passthrough(bed.run(_READ_ONLY_GET), _READ_ONLY_GET)


def test_read_only_gh_api_get_never_touches_the_claims_registry() -> None:
    """A non-mutating `gh api` must be decided without ownership evaluation.

    Proven structurally: with the registry module deliberately unimportable, a
    GET still passes.  If the GET path imported the registry it would error and
    fail closed.
    """
    with tempfile.TemporaryDirectory() as td:
        bed = _Bed(Path(td))
        bed.break_registry()
        _assert_passthrough(bed.run(_READ_ONLY_GET), _READ_ONLY_GET)


def test_quoted_gh_api_literal_passes_under_cache_layout() -> None:
    """Quoted text naming `gh api` is not a command and must pass through."""
    with tempfile.TemporaryDirectory() as td:
        bed = _Bed(Path(td))
        _assert_passthrough(bed.run(_QUOTED_LITERAL), _QUOTED_LITERAL)


# ---------------------------------------------------------------------------
# AC3 — the gate still discriminates under the cache layout
# ---------------------------------------------------------------------------


def test_cross_lane_api_pr_close_blocks_under_cache_layout() -> None:
    """A peer lane's active claim refuses this lane's `gh api -X PATCH` close."""
    with tempfile.TemporaryDirectory() as td:
        bed = _Bed(Path(td))
        _write_claim(bed.state_dir, _pr_key(), lane_id=LANE_PEER)
        reason = _assert_blocked(bed.run(_cross_lane_patch(), lane_id=LANE_SELF))
        assert "REFUSED" in reason and LANE_PEER in reason, (
            f"refusal must name the owning peer lane: {reason}"
        )
        assert "could not evaluate" not in reason, (
            "must block on OWNERSHIP, not on an evaluation error — a guard that "
            f"cannot evaluate is not a guard that discriminates: {reason}"
        )


def test_unclaimed_api_pr_close_blocks_under_cache_layout() -> None:
    """Absent claim is never read as 'free to take' (OMN-16485 fail-closed)."""
    with tempfile.TemporaryDirectory() as td:
        bed = _Bed(Path(td))
        reason = _assert_blocked(bed.run(_cross_lane_patch(4242), lane_id=LANE_SELF))
        assert "REFUSED" in reason, reason
        assert "could not evaluate" not in reason, (
            f"must refuse on ownership, not on an evaluation error: {reason}"
        )


def test_own_lane_api_pr_close_is_allowed_under_cache_layout() -> None:
    """The allow half of the discrimination pair: this lane's own claim passes.

    Without this, a guard that blocks EVERYTHING would satisfy the block tests.
    """
    with tempfile.TemporaryDirectory() as td:
        bed = _Bed(Path(td))
        _write_claim(bed.state_dir, _pr_key(), lane_id=LANE_SELF)
        command = _cross_lane_patch()
        _assert_passthrough(bed.run(command, lane_id=LANE_SELF), command)


# ---------------------------------------------------------------------------
# AC2 — evaluation errors on a genuine mutation verb stay fail-closed
# ---------------------------------------------------------------------------


def test_evaluation_error_on_mutation_verb_still_fails_closed() -> None:
    """A broken registry must refuse a real mutation, not wave it through."""
    with tempfile.TemporaryDirectory() as td:
        bed = _Bed(Path(td))
        _write_claim(bed.state_dir, _pr_key(), lane_id=LANE_SELF)
        bed.break_registry()
        reason = _assert_blocked(bed.run(_cross_lane_patch(), lane_id=LANE_SELF))
        assert "could not evaluate" in reason, (
            f"expected the fail-closed evaluation-error refusal: {reason}"
        )


def test_gh_pr_close_still_fails_closed_when_registry_is_broken() -> None:
    """The same fail-closed contract holds for the `gh pr close` verb."""
    with tempfile.TemporaryDirectory() as td:
        bed = _Bed(Path(td))
        bed.break_registry()
        reason = _assert_blocked(
            bed.run("gh pr close 2019 --repo OmniNode-ai/omniclaude")
        )
        assert "could not evaluate" in reason
