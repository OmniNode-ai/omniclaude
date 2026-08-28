# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for worktree_auto_prune.py's fact collection [OMN-16901].

The pure predicate itself is covered by
``tests/unit/hooks/lib/test_worktree_prune_policy.py``. These tests cover the
fact-collection half — the parts that decide *what the predicate is told*, where
a bug is just as capable of deleting live work:

* ledger claim-awareness (the claim-awareness hazard: a lane that re-claimed a closed
  ticket must block the prune),
* stash attribution to a branch (stashes are repo-wide, worktrees are not),
* tracker state mapping (only ``completed``/``canceled`` are terminal).

No network calls, no subprocesses.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.hooks.lib.worktree_prune_policy import EnumTicketLifecycle

pytestmark = pytest.mark.unit

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "worktree_auto_prune.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("worktree_auto_prune", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


# =============================================================================
# Ledger claim-awareness
# =============================================================================


class TestParseLedgerClaims:
    def test_terminal_row_without_later_claim_is_closed(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "| 2026-08-01T10:00:00Z | lane-a | OMN-1234 | CLAIM | started |\n"
            "| 2026-08-02T10:00:00Z | lane-a | OMN-1234 | TERMINAL | landed |\n",
            encoding="utf-8",
        )
        has_terminal, open_claim = mod.parse_ledger_claims(ledger)["OMN-1234"]
        assert has_terminal is True
        assert open_claim is None

    def test_claim_after_terminal_reopens_the_ticket(self, tmp_path: Path) -> None:
        """A live lane resumed work on a closed ticket."""
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "| 2026-08-02T10:00:00Z | lane-a | OMN-1234 | TERMINAL | landed |\n"
            "| 2026-08-03T10:00:00Z | lane-b | OMN-1234 | CLAIM | repair lane |\n",
            encoding="utf-8",
        )
        has_terminal, open_claim = mod.parse_ledger_claims(ledger)["OMN-1234"]
        assert has_terminal is True
        assert open_claim is not None
        assert "repair lane" in open_claim

    def test_claim_plus_terminal_on_one_line_resolves_to_terminal(
        self, tmp_path: Path
    ) -> None:
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "### OMN-1234 — a lane\n\n- **Status:** CLAIM+TERMINAL\n",
            encoding="utf-8",
        )
        has_terminal, open_claim = mod.parse_ledger_claims(ledger)["OMN-1234"]
        assert has_terminal is True
        assert open_claim is None

    def test_section_body_inherits_the_ticket_from_its_heading(
        self, tmp_path: Path
    ) -> None:
        """`- **Status:** IN PROGRESS.` carries no ticket id of its own."""
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "### OMN-1234 — a lane (CLAIM)\n\n"
            "- **Scope:** something\n"
            "- **Status:** IN PROGRESS.\n",
            encoding="utf-8",
        )
        has_terminal, open_claim = mod.parse_ledger_claims(ledger)["OMN-1234"]
        assert has_terminal is False
        assert open_claim is not None

    def test_prose_mentioning_a_ticket_is_not_a_claim(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "Some prose about the claim gate and OMN-1234 being terminal-ish.\n",
            encoding="utf-8",
        )
        assert mod.parse_ledger_claims(ledger) == {}

    def test_missing_ledger_returns_empty_map(self, tmp_path: Path) -> None:
        assert mod.parse_ledger_claims(tmp_path / "absent.md") == {}

    def test_tickets_are_tracked_independently(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.md"
        ledger.write_text(
            "| t1 | lane | OMN-1 | TERMINAL | done |\n"
            "| t2 | lane | OMN-2 | CLAIM | live |\n",
            encoding="utf-8",
        )
        parsed = mod.parse_ledger_claims(ledger)
        assert parsed["OMN-1"] == (True, None)
        assert parsed["OMN-2"][0] is False
        assert parsed["OMN-2"][1] is not None


# =============================================================================
# Stash attribution — stashes are repo-wide, worktrees are not
# =============================================================================


class TestCountAttributedStashes:
    def test_counts_only_stashes_naming_this_branch(self) -> None:
        subjects = [
            "WIP on jonah/omn-1-a: 1234567 msg",
            "On jonah/omn-1-a: manual stash",
            "WIP on jonah/omn-2-b: 89abcde msg",
        ]
        assert mod.count_attributed_stashes(subjects, "jonah/omn-1-a") == 2
        assert mod.count_attributed_stashes(subjects, "jonah/omn-2-b") == 1

    def test_unrelated_branch_has_no_attributed_stash(self) -> None:
        subjects = ["WIP on other/branch: 1234567 msg"]
        assert mod.count_attributed_stashes(subjects, "jonah/omn-1-a") == 0

    def test_detached_head_attributes_nothing(self) -> None:
        assert mod.count_attributed_stashes(["WIP on x: y"], None) == 0

    def test_prefix_collision_does_not_over_attribute(self) -> None:
        """`WIP on feat/a-extended:` must not be attributed to `feat/a`."""
        subjects = ["WIP on feat/a-extended: 1234567 msg"]
        assert mod.count_attributed_stashes(subjects, "feat/a") == 0


# =============================================================================
# Tracker state mapping — only terminal states are terminal
# =============================================================================


class TestStateTypeToLifecycle:
    @pytest.mark.parametrize(
        ("state_type", "expected"),
        [
            ("completed", EnumTicketLifecycle.DONE),
            ("canceled", EnumTicketLifecycle.CANCELED),
            ("started", EnumTicketLifecycle.OPEN),
            ("unstarted", EnumTicketLifecycle.OPEN),
            ("backlog", EnumTicketLifecycle.OPEN),
            ("triage", EnumTicketLifecycle.OPEN),
            ("", EnumTicketLifecycle.OPEN),
        ],
    )
    def test_mapping(self, state_type: str, expected: EnumTicketLifecycle) -> None:
        assert mod._state_type_to_lifecycle(state_type) is expected


# =============================================================================
# Worktree discovery — a linked worktree's .git is a file, a clone's is a dir
# =============================================================================


class TestDiscoverWorktrees:
    def test_finds_linked_worktrees_and_ignores_full_clones(
        self, tmp_path: Path
    ) -> None:
        linked = tmp_path / "OMN-1" / "repo"
        linked.mkdir(parents=True)
        (linked / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")

        nested = tmp_path / "OMN-2" / "sub" / "repo"
        nested.mkdir(parents=True)
        (nested / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")

        clone = tmp_path / "OMN-3" / "repo"
        (clone / ".git").mkdir(parents=True)

        found = mod.discover_worktrees(tmp_path)
        assert linked in found
        assert nested in found
        assert clone not in found
