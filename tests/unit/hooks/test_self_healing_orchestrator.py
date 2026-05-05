# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for self_healing_orchestrator (OMN-7259)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from omniclaude.hooks.self_healing_orchestrator import (
    MAX_REDISPATCHES,
    REGISTRY_REPOS,
    DispatchGroup,
    OrchestratorResult,
    TicketRef,
    build_stall_recovery_prompt,
    build_team_dispatch_prompt,
    exceeds_max_redispatches,
    group_by_repo,
    log_event,
    orchestrate,
    parse_ticket_ids,
    record_stall_recovery,
)


@pytest.mark.unit
class TestTicketRef:
    def test_valid_ticket(self) -> None:
        ref = TicketRef(ticket_id="OMN-1234")
        assert ref.ticket_id == "OMN-1234"
        assert ref.repo == "unassigned"

    def test_valid_ticket_with_repo(self) -> None:
        ref = TicketRef(ticket_id="OMN-9999", repo="omniclaude")
        assert ref.repo == "omniclaude"

    def test_invalid_ticket_id_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid ticket ID"):
            TicketRef(ticket_id="NOTOMN-123")

    def test_unknown_repo_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown repo"):
            TicketRef(ticket_id="OMN-1234", repo="not_a_real_repo")


@pytest.mark.unit
class TestParseTicketIds:
    def test_valid_list(self) -> None:
        refs = parse_ticket_ids(["OMN-1", "OMN-999"])
        assert [r.ticket_id for r in refs] == ["OMN-1", "OMN-999"]

    def test_strips_whitespace(self) -> None:
        refs = parse_ticket_ids(["  OMN-42  "])
        assert refs[0].ticket_id == "OMN-42"

    def test_invalid_id_raises(self) -> None:
        with pytest.raises(ValueError, match="Not a valid ticket ID"):
            parse_ticket_ids(["OMN-1234", "BADID"])

    def test_empty_list_returns_empty(self) -> None:
        assert parse_ticket_ids([]) == []


@pytest.mark.unit
class TestGroupByRepo:
    def test_no_hints_all_unassigned(self) -> None:
        refs = [TicketRef(ticket_id="OMN-1"), TicketRef(ticket_id="OMN-2")]
        groups = group_by_repo(refs)
        assert len(groups) == 1
        assert groups[0].repo == "unassigned"
        assert len(groups[0].tickets) == 2

    def test_hints_assign_repo(self) -> None:
        refs = [TicketRef(ticket_id="OMN-1"), TicketRef(ticket_id="OMN-2")]
        hints = {"OMN-1": "omniclaude", "OMN-2": "omnibase_core"}
        groups = group_by_repo(refs, repo_hints=hints)
        repos = {g.repo for g in groups}
        assert repos == {"omniclaude", "omnibase_core"}

    def test_unknown_hint_falls_back_to_unassigned(self) -> None:
        refs = [TicketRef(ticket_id="OMN-1")]
        hints = {"OMN-1": "not_a_real_repo"}
        groups = group_by_repo(refs, repo_hints=hints)
        assert groups[0].repo == "unassigned"

    def test_tickets_grouped_correctly(self) -> None:
        refs = [
            TicketRef(ticket_id="OMN-1"),
            TicketRef(ticket_id="OMN-2"),
            TicketRef(ticket_id="OMN-3"),
        ]
        hints = {"OMN-1": "omniclaude", "OMN-2": "omniclaude", "OMN-3": "omnibase_core"}
        groups = group_by_repo(refs, repo_hints=hints)
        claude_group = next(g for g in groups if g.repo == "omniclaude")
        core_group = next(g for g in groups if g.repo == "omnibase_core")
        assert len(claude_group.tickets) == 2
        assert len(core_group.tickets) == 1

    def test_result_sorted_by_repo_name(self) -> None:
        refs = [TicketRef(ticket_id=f"OMN-{i}") for i in range(3)]
        hints = {"OMN-0": "omnibase_core", "OMN-1": "omniclaude", "OMN-2": "omnidash"}
        groups = group_by_repo(refs, repo_hints=hints)
        assert [g.repo for g in groups] == sorted(hints.values())


@pytest.mark.unit
class TestBuildPrompts:
    def _make_group(self, repo: str, *ticket_ids: str) -> DispatchGroup:
        return DispatchGroup(
            repo=repo,
            tickets=[TicketRef(ticket_id=tid, repo=repo) for tid in ticket_ids],
        )

    def test_team_dispatch_prompt_contains_repo(self) -> None:
        group = self._make_group("omniclaude", "OMN-1", "OMN-2")
        prompt = build_team_dispatch_prompt(group, epic_id=None)
        assert "omniclaude" in prompt
        assert "OMN-1" in prompt
        assert "OMN-2" in prompt

    def test_team_dispatch_prompt_includes_epic(self) -> None:
        group = self._make_group("omniclaude", "OMN-1")
        prompt = build_team_dispatch_prompt(group, epic_id="OMN-7253")
        assert "OMN-7253" in prompt

    def test_team_dispatch_prompt_no_epic(self) -> None:
        group = self._make_group("omniclaude", "OMN-1")
        prompt = build_team_dispatch_prompt(group, epic_id=None)
        assert "epic" not in prompt.lower()

    def test_stall_recovery_prompt_excludes_completed(self) -> None:
        group = self._make_group("omniclaude", "OMN-1", "OMN-2", "OMN-3")
        prompt = build_stall_recovery_prompt(
            group, "OMN-2", attempt=1, completed_tickets=["OMN-1"]
        )
        assert "OMN-1" not in prompt  # completed — excluded
        assert "OMN-2" in prompt or "OMN-3" in prompt  # remaining

    def test_stall_recovery_prompt_includes_attempt_number(self) -> None:
        group = self._make_group("omniclaude", "OMN-1")
        prompt = build_stall_recovery_prompt(
            group, "OMN-1", attempt=2, completed_tickets=[]
        )
        assert "#2" in prompt


@pytest.mark.unit
class TestRedispatchAccounting:
    def _make_group(self) -> DispatchGroup:
        return DispatchGroup(
            repo="omniclaude",
            tickets=[TicketRef(ticket_id="OMN-1", repo="omniclaude")],
        )

    def test_initial_count_is_zero(self) -> None:
        group = self._make_group()
        assert not exceeds_max_redispatches(group, "OMN-1")

    def test_increment_once_below_max(self) -> None:
        group = self._make_group()
        group.increment_redispatch("OMN-1")
        assert not exceeds_max_redispatches(group, "OMN-1")

    def test_increment_to_max_is_not_exceeded(self) -> None:
        group = self._make_group()
        for _ in range(MAX_REDISPATCHES):
            group.increment_redispatch("OMN-1")
        # exactly at max — still dispatches (exceeded = strictly greater)
        assert not exceeds_max_redispatches(group, "OMN-1")

    def test_increment_beyond_max_exceeds(self) -> None:
        group = self._make_group()
        for _ in range(MAX_REDISPATCHES + 1):
            group.increment_redispatch("OMN-1")
        assert exceeds_max_redispatches(group, "OMN-1")

    def test_record_stall_below_max_returns_redispatch_true(self) -> None:
        group = self._make_group()
        should_redispatch, attempt = record_stall_recovery(group, "OMN-1", "run-1", [])
        assert should_redispatch is True
        assert attempt == 1

    def test_record_stall_at_max_returns_redispatch_false(self) -> None:
        group = self._make_group()
        # First two stalls are within limit
        for _ in range(MAX_REDISPATCHES):
            record_stall_recovery(group, "OMN-1", "run-1", [])
        # Third stall exceeds limit
        should_redispatch, attempt = record_stall_recovery(group, "OMN-1", "run-1", [])
        assert should_redispatch is False
        assert attempt == MAX_REDISPATCHES + 1


@pytest.mark.unit
class TestOrchestrate:
    def test_returns_orchestrator_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("ONEX_STATE_DIR", tmpdir)
            result = orchestrate(["OMN-1234", "OMN-5678"], run_id="test-run-1")
        assert isinstance(result, OrchestratorResult)
        assert result.run_id == "test-run-1"
        assert result.total_tickets == 2
        assert result.stalls_recovered == 0
        assert result.escalated == []

    def test_emits_ndjson_log_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("ONEX_STATE_DIR", tmpdir)
            orchestrate(["OMN-1234"], run_id="test-run-log")
            log_files = list(Path(tmpdir, "dispatch-log").glob("*.ndjson"))
            assert log_files, "Expected at least one NDJSON log file"
            entries = [
                json.loads(line)
                for line in log_files[0].read_text().splitlines()
                if line
            ]
            events = [e["event"] for e in entries]
            assert "orchestration_planned" in events

    def test_with_repo_hints(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("ONEX_STATE_DIR", tmpdir)
            result = orchestrate(
                ["OMN-1", "OMN-2"],
                repo_hints={"OMN-1": "omniclaude", "OMN-2": "omnibase_core"},
            )
        repos = {g.repo for g in result.groups}
        assert repos == {"omniclaude", "omnibase_core"}

    def test_with_epic_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("ONEX_STATE_DIR", tmpdir)
            result = orchestrate(["OMN-99"], epic_id="OMN-7253")
        assert result.epic_id == "OMN-7253"

    def test_invalid_ticket_raises(self) -> None:
        with pytest.raises(ValueError):
            orchestrate(["NOT-A-TICKET"])

    def test_empty_ticket_list_raises_and_logs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("ONEX_STATE_DIR", tmpdir)
            with pytest.raises(ValueError, match="No ticket IDs provided"):
                orchestrate([], run_id="test-run-empty")

            log_files = list(Path(tmpdir, "dispatch-log").glob("*.ndjson"))
            assert log_files, "Expected rejected orchestration to be logged"
            entries = [
                json.loads(line)
                for line in log_files[0].read_text().splitlines()
                if line
            ]
        assert entries[0]["event"] == "orchestration_rejected"
        assert entries[0]["run_id"] == "test-run-empty"
        assert entries[0]["reason"] == "no_ticket_ids"


@pytest.mark.unit
class TestLogEvent:
    def test_log_event_writes_ndjson(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("ONEX_STATE_DIR", tmpdir)
            log_event("test_event", run_id="run-x", ticket_id="OMN-1")
            log_files = list(Path(tmpdir, "dispatch-log").glob("*.ndjson"))
            assert log_files
            entries = [
                json.loads(line)
                for line in log_files[0].read_text().splitlines()
                if line
            ]
            assert entries[0]["event"] == "test_event"
            assert entries[0]["run_id"] == "run-x"

    def test_log_event_never_raises_on_bad_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", "/nonexistent/cannot/write/here")
        # Should not raise
        log_event("safe_event", run_id="x")

    def test_log_event_never_raises_on_unserializable_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("ONEX_STATE_DIR", tmpdir)
            log_event("bad_field", callback=lambda: None)

    def test_multiple_events_append(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("ONEX_STATE_DIR", tmpdir)
            log_event("event_a", run_id="r1")
            log_event("event_b", run_id="r1")
            log_files = list(Path(tmpdir, "dispatch-log").glob("*.ndjson"))
            lines = [ln for ln in log_files[0].read_text().splitlines() if ln]
            assert len(lines) == 2
            events = [json.loads(ln)["event"] for ln in lines]
            assert events == ["event_a", "event_b"]


@pytest.mark.unit
class TestRegistryRepos:
    def test_registry_contains_expected_repos(self) -> None:
        assert "omniclaude" in REGISTRY_REPOS
        assert "omnibase_core" in REGISTRY_REPOS
        assert "omnibase_infra" in REGISTRY_REPOS

    def test_max_redispatches_is_two(self) -> None:
        assert MAX_REDISPATCHES == 2
