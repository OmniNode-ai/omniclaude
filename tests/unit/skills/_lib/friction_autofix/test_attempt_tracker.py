# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from pathlib import Path

import pytest


@pytest.mark.unit
class TestAttemptTracker:
    def test_record_attempt_new_surface(self, tmp_path: Path) -> None:
        from friction_autofix.attempt_tracker import AttemptTracker

        tracker = AttemptTracker(state_path=tmp_path / "attempts.json")
        tracker.record_attempt("a:config/missing")
        assert tracker.get_attempt_count("a:config/missing") == 1

    def test_record_attempt_increments(self, tmp_path: Path) -> None:
        from friction_autofix.attempt_tracker import AttemptTracker

        tracker = AttemptTracker(state_path=tmp_path / "attempts.json")
        tracker.record_attempt("a:config/missing")
        tracker.record_attempt("a:config/missing")
        assert tracker.get_attempt_count("a:config/missing") == 2

    def test_is_blocked_after_two_strikes(self, tmp_path: Path) -> None:
        from friction_autofix.attempt_tracker import AttemptTracker

        tracker = AttemptTracker(state_path=tmp_path / "attempts.json")
        tracker.record_attempt("a:config/missing")
        assert not tracker.is_blocked("a:config/missing")
        tracker.record_attempt("a:config/missing")
        assert tracker.is_blocked("a:config/missing")

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        from friction_autofix.attempt_tracker import AttemptTracker

        state_file = tmp_path / "attempts.json"
        tracker1 = AttemptTracker(state_path=state_file)
        tracker1.record_attempt("a:config/missing")
        tracker1.save()

        tracker2 = AttemptTracker(state_path=state_file)
        assert tracker2.get_attempt_count("a:config/missing") == 1

    def test_mark_resolved_clears_attempts(self, tmp_path: Path) -> None:
        from friction_autofix.attempt_tracker import AttemptTracker

        tracker = AttemptTracker(state_path=tmp_path / "attempts.json")
        tracker.record_attempt("a:config/missing")
        tracker.record_attempt("a:config/missing")
        tracker.mark_resolved("a:config/missing")
        assert tracker.get_attempt_count("a:config/missing") == 0
        assert not tracker.is_blocked("a:config/missing")

    def test_unknown_surface_returns_zero(self, tmp_path: Path) -> None:
        from friction_autofix.attempt_tracker import AttemptTracker

        tracker = AttemptTracker(state_path=tmp_path / "attempts.json")
        assert tracker.get_attempt_count("unknown:surface") == 0
        assert not tracker.is_blocked("unknown:surface")
