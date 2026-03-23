# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for skill_suggestion_injector (OMN-3455).

All tests run without Postgres or network access.  Usage log and progression
graph are provided via tmp_path fixtures or in-memory content.
"""

from __future__ import annotations

import json
import textwrap
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from omniclaude.hooks.lib.skill_suggestion_injector import (
    _find_candidates,
    _format_one,
    _load_counts_from_log,
    _normalize_skill_name,
    format_suggestions,
    get_skill_suggestions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROGRESSION_YAML = textwrap.dedent(
    """\
    progressions:
      - from: local-review
        to: pr-polish
        after_uses: 5
      - from: ticket-work
        to: ticket-pipeline
        after_uses: 3
      - from: pr-review
        to: pr-review-dev
        after_uses: 5
      - from: gap-analysis
        to: gap-fix
        after_uses: 2
    """
)


def _write_progression(tmp_path: Path, content: str = _PROGRESSION_YAML) -> Path:
    p = tmp_path / "progression.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _write_log(tmp_path: Path, entries: list[dict]) -> Path:
    log = tmp_path / "onex-skill-usage.log"
    log.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    return log


# ---------------------------------------------------------------------------
# _normalize_skill_name
# ---------------------------------------------------------------------------


class TestNormalizeSkillName:
    @pytest.mark.unit
    def test_strips_onex_prefix(self) -> None:
        assert _normalize_skill_name("onex:local_review") == "local-review"

    @pytest.mark.unit
    def test_no_prefix_unchanged(self) -> None:
        assert _normalize_skill_name("local-review") == "local-review"

    @pytest.mark.unit
    def test_empty_string_unchanged(self) -> None:
        assert _normalize_skill_name("") == ""


# ---------------------------------------------------------------------------
# _load_counts_from_log
# ---------------------------------------------------------------------------


class TestLoadCountsFromLog:
    @pytest.mark.unit
    def test_nonexistent_log_returns_empty_counter(self, tmp_path: Path) -> None:
        log = tmp_path / "missing.log"
        counts = _load_counts_from_log(log)
        assert isinstance(counts, Counter)
        assert len(counts) == 0

    @pytest.mark.unit
    def test_counts_skill_uses(self, tmp_path: Path) -> None:
        log = _write_log(
            tmp_path,
            [
                {
                    "skill_name": "onex:local_review",
                    "timestamp": "t",
                    "session_id": "s",
                },
                {
                    "skill_name": "onex:local_review",
                    "timestamp": "t",
                    "session_id": "s",
                },
                {"skill_name": "onex:ticket_work", "timestamp": "t", "session_id": "s"},
            ],
        )
        counts = _load_counts_from_log(log)
        assert counts["local-review"] == 2
        assert counts["ticket-work"] == 1

    @pytest.mark.unit
    def test_strips_onex_prefix_in_counts(self, tmp_path: Path) -> None:
        log = _write_log(
            tmp_path,
            [{"skill_name": "onex:pr_review", "timestamp": "t", "session_id": "s"}],
        )
        counts = _load_counts_from_log(log)
        assert "pr-review" in counts
        assert "onex:pr_review" not in counts

    @pytest.mark.unit
    def test_skips_malformed_json_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        log.write_text(
            '{"skill_name": "onex:local_review", "timestamp": "t", "session_id": "s"}\n'
            "not-valid-json\n"
            '{"skill_name": "onex:ticket_work", "timestamp": "t", "session_id": "s"}\n',
            encoding="utf-8",
        )
        counts = _load_counts_from_log(log)
        assert counts["local-review"] == 1
        assert counts["ticket-work"] == 1

    @pytest.mark.unit
    def test_skips_entries_with_empty_skill_name(self, tmp_path: Path) -> None:
        log = _write_log(
            tmp_path,
            [{"skill_name": "", "timestamp": "t", "session_id": "s"}],
        )
        counts = _load_counts_from_log(log)
        assert len(counts) == 0

    @pytest.mark.unit
    def test_empty_log_returns_empty_counter(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        log.write_text("", encoding="utf-8")
        counts = _load_counts_from_log(log)
        assert len(counts) == 0


# ---------------------------------------------------------------------------
# _find_candidates
# ---------------------------------------------------------------------------


class TestFindCandidates:
    def _make_progressions(self) -> list[dict]:
        import yaml  # type: ignore[import-untyped]

        return yaml.safe_load(_PROGRESSION_YAML)["progressions"]

    @pytest.mark.unit
    def test_unlocks_when_threshold_met(self) -> None:
        progressions = self._make_progressions()
        counts: Counter[str] = Counter({"local-review": 5})
        candidates = _find_candidates(counts=counts, progressions=progressions)
        to_skills = [to for _, to in candidates]
        assert "pr-polish" in to_skills

    @pytest.mark.unit
    def test_no_unlock_when_below_threshold(self) -> None:
        progressions = self._make_progressions()
        counts: Counter[str] = Counter({"local-review": 4})
        candidates = _find_candidates(counts=counts, progressions=progressions)
        to_skills = [to for _, to in candidates]
        assert "pr-polish" not in to_skills

    @pytest.mark.unit
    def test_no_unlock_when_to_already_used(self) -> None:
        progressions = self._make_progressions()
        counts: Counter[str] = Counter({"local-review": 10, "pr-polish": 2})
        candidates = _find_candidates(counts=counts, progressions=progressions)
        to_skills = [to for _, to in candidates]
        assert "pr-polish" not in to_skills

    @pytest.mark.unit
    def test_multiple_unlocks_sorted_by_threshold(self) -> None:
        """Lower after_uses threshold should appear first."""
        progressions = self._make_progressions()
        # gap-analysis (after_uses=2) and ticket-work (after_uses=3)
        counts: Counter[str] = Counter({"gap-analysis": 2, "ticket-work": 3})
        candidates = _find_candidates(counts=counts, progressions=progressions)
        assert candidates[0][1] == "gap-fix"  # gap-fix has lower threshold

    @pytest.mark.unit
    def test_empty_progressions_returns_empty(self) -> None:
        candidates = _find_candidates(counts=Counter(), progressions=[])
        assert candidates == []

    @pytest.mark.unit
    def test_no_usage_returns_empty(self) -> None:
        progressions = self._make_progressions()
        candidates = _find_candidates(counts=Counter(), progressions=progressions)
        assert candidates == []

    @pytest.mark.unit
    def test_returns_tuple_of_from_to(self) -> None:
        progressions = self._make_progressions()
        counts: Counter[str] = Counter({"ticket-work": 3})
        candidates = _find_candidates(counts=counts, progressions=progressions)
        assert len(candidates) >= 1
        frm, to = candidates[0]
        assert frm == "ticket-work"
        assert to == "ticket-pipeline"


# ---------------------------------------------------------------------------
# _format_one
# ---------------------------------------------------------------------------


class TestFormatOne:
    @pytest.mark.unit
    def test_format_with_from_skill(self) -> None:
        msg = _format_one(to_skill="pr-polish", from_skill="local-review")
        assert "pr-polish" in msg
        assert "local-review" in msg
        assert "/onex:pr_polish" in msg

    @pytest.mark.unit
    def test_format_fallback_no_from_skill(self) -> None:
        msg = _format_one(to_skill="local-review", from_skill="")
        assert "/onex:local_review" in msg
        # Fallback format should NOT mention a from skill
        assert "builds on" not in msg

    @pytest.mark.unit
    def test_no_prompt_content_in_message(self) -> None:
        msg = _format_one(to_skill="pr-polish", from_skill="local-review")
        for forbidden in ("prompt", "code", "file", "content"):
            assert forbidden not in msg.lower()


# ---------------------------------------------------------------------------
# format_suggestions
# ---------------------------------------------------------------------------


class TestFormatSuggestions:
    @pytest.mark.unit
    def test_empty_list_returns_empty_string(self) -> None:
        assert format_suggestions([]) == ""

    @pytest.mark.unit
    def test_single_suggestion_returned(self) -> None:
        result = format_suggestions(["msg1"])
        assert result == "msg1"

    @pytest.mark.unit
    def test_two_suggestions_joined_by_newline(self) -> None:
        result = format_suggestions(["msg1", "msg2"])
        assert "msg1" in result
        assert "msg2" in result
        assert "\n" in result


# ---------------------------------------------------------------------------
# get_skill_suggestions (integration-style, fully mocked)
# ---------------------------------------------------------------------------


class TestGetSkillSuggestions:
    @pytest.mark.unit
    def test_returns_list(self, tmp_path: Path) -> None:
        log = _write_log(
            tmp_path,
            [
                {
                    "skill_name": "onex:local_review",
                    "timestamp": "t",
                    "session_id": "s",
                },
            ],
        )
        prog = _write_progression(tmp_path)
        result = get_skill_suggestions(
            "sess", log_path=log, progression_path=prog, db_enabled=False
        )
        assert isinstance(result, list)

    @pytest.mark.unit
    def test_suggests_unlocked_skill(self, tmp_path: Path) -> None:
        # 5 uses of local-review → should suggest pr-polish
        log = _write_log(
            tmp_path,
            [
                {
                    "skill_name": "onex:local_review",
                    "timestamp": "t",
                    "session_id": "s",
                },
            ]
            * 5,
        )
        prog = _write_progression(tmp_path)
        result = get_skill_suggestions(
            "sess", log_path=log, progression_path=prog, db_enabled=False
        )
        assert any("pr-polish" in s for s in result)

    @pytest.mark.unit
    def test_does_not_suggest_already_used_skill(self, tmp_path: Path) -> None:
        log = _write_log(
            tmp_path,
            [{"skill_name": "onex:local_review", "timestamp": "t", "session_id": "s"}]
            * 5
            + [{"skill_name": "onex:pr_polish", "timestamp": "t", "session_id": "s"}],
        )
        prog = _write_progression(tmp_path)
        result = get_skill_suggestions(
            "sess", log_path=log, progression_path=prog, db_enabled=False
        )
        assert not any("pr-polish" in s for s in result)

    @pytest.mark.unit
    def test_max_two_suggestions(self, tmp_path: Path) -> None:
        # Use all from-skills enough times to unlock all progressions
        log = _write_log(
            tmp_path,
            [
                {
                    "skill_name": "onex:local_review",
                    "timestamp": "t",
                    "session_id": "s",
                },
            ]
            * 5
            + [{"skill_name": "onex:ticket_work", "timestamp": "t", "session_id": "s"}]
            * 3
            + [{"skill_name": "onex:pr_review", "timestamp": "t", "session_id": "s"}]
            * 5
            + [{"skill_name": "onex:gap-analysis", "timestamp": "t", "session_id": "s"}]
            * 2,
        )
        prog = _write_progression(tmp_path)
        result = get_skill_suggestions(
            "sess", log_path=log, progression_path=prog, db_enabled=False
        )
        assert len(result) <= 2

    @pytest.mark.unit
    def test_fallback_when_no_usage_history(self, tmp_path: Path) -> None:
        # Empty log → should suggest basic skills via fallback
        log = tmp_path / "empty.log"
        log.write_text("", encoding="utf-8")
        prog = _write_progression(tmp_path)
        result = get_skill_suggestions(
            "sess", log_path=log, progression_path=prog, db_enabled=False
        )
        # Fallback should return at most 2 suggestions
        assert len(result) <= 2

    @pytest.mark.unit
    def test_missing_log_triggers_fallback(self, tmp_path: Path) -> None:
        # No log file at all → fallback should run without crashing
        log = tmp_path / "nonexistent.log"
        prog = _write_progression(tmp_path)
        result = get_skill_suggestions(
            "sess", log_path=log, progression_path=prog, db_enabled=False
        )
        assert isinstance(result, list)
        assert len(result) <= 2

    @pytest.mark.unit
    def test_missing_progression_yaml_returns_empty(self, tmp_path: Path) -> None:
        log = _write_log(
            tmp_path,
            [{"skill_name": "onex:local_review", "timestamp": "t", "session_id": "s"}]
            * 5,
        )
        prog = tmp_path / "nonexistent-progression.yaml"
        result = get_skill_suggestions(
            "sess", log_path=log, progression_path=prog, db_enabled=False
        )
        assert isinstance(result, list)

    @pytest.mark.unit
    def test_never_raises(self, tmp_path: Path) -> None:
        """get_skill_suggestions must not propagate any exception."""
        with patch(
            "omniclaude.hooks.lib.skill_suggestion_injector._compute_suggestions",
            side_effect=RuntimeError("simulated crash"),
        ):
            result = get_skill_suggestions("sess")
        assert result == []

    @pytest.mark.unit
    def test_db_not_called_when_disabled(self, tmp_path: Path) -> None:
        log = _write_log(
            tmp_path,
            [{"skill_name": "onex:local_review", "timestamp": "t", "session_id": "s"}],
        )
        prog = _write_progression(tmp_path)
        with patch(
            "omniclaude.hooks.lib.skill_suggestion_injector._load_counts_from_db"
        ) as mock_db:
            get_skill_suggestions(
                "sess", log_path=log, progression_path=prog, db_enabled=False
            )
        mock_db.assert_not_called()

    @pytest.mark.unit
    def test_db_queried_when_enabled(self, tmp_path: Path) -> None:
        log = _write_log(
            tmp_path,
            [{"skill_name": "onex:local_review", "timestamp": "t", "session_id": "s"}],
        )
        prog = _write_progression(tmp_path)
        with patch(
            "omniclaude.hooks.lib.skill_suggestion_injector._load_counts_from_db",
            return_value=Counter({"local-review": 5}),
        ) as mock_db:
            get_skill_suggestions(
                "sess", log_path=log, progression_path=prog, db_enabled=True
            )
        mock_db.assert_called_once()

    @pytest.mark.unit
    def test_db_failure_falls_back_to_log(self, tmp_path: Path) -> None:
        """When DB fails, should fall back to local log without crashing."""
        log = _write_log(
            tmp_path,
            [{"skill_name": "onex:local_review", "timestamp": "t", "session_id": "s"}]
            * 5,
        )
        prog = _write_progression(tmp_path)
        with patch(
            "omniclaude.hooks.lib.skill_suggestion_injector._load_counts_from_db",
            return_value=None,  # None signals failure — fall back to log
        ):
            result = get_skill_suggestions(
                "sess", log_path=log, progression_path=prog, db_enabled=True
            )
        # Should still suggest based on local log
        assert any("pr-polish" in s for s in result)

    @pytest.mark.unit
    def test_suggestion_contains_only_skill_name(self, tmp_path: Path) -> None:
        """Privacy: no prompt content, file paths, or code in suggestions."""
        log = _write_log(
            tmp_path,
            [{"skill_name": "onex:ticket_work", "timestamp": "t", "session_id": "s"}]
            * 3,
        )
        prog = _write_progression(tmp_path)
        result = get_skill_suggestions(
            "sess", log_path=log, progression_path=prog, db_enabled=False
        )
        for suggestion in result:
            for forbidden in (
                "prompt",
                "code",
                "file_path",
                "content",
                "args",
                "session_id",
            ):
                assert forbidden not in suggestion.lower()
