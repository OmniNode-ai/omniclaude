# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Diff-scoping + fail-closed escalation for run_aislop_sweep.py (OMN-14086).

Proves the three properties the diff-scope retrofit must hold:
  (a) a normal diff scans ONLY the changed files — a pre-existing violation in
      an unchanged file is not re-flagged;
  (b) the scan escalates to the full src/ tree when narrowing cannot be proven
      safe (no diff supplied, or the diff touches the aislop validator sources);
  (c) a planted violation IN a changed file is still caught (no false-green).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Load the sweep as a module without importing scripts.ci as a package.
_SPEC = importlib.util.spec_from_file_location(
    "run_aislop_sweep_under_test",
    REPO_ROOT / "scripts" / "ci" / "run_aislop_sweep.py",
)
assert _SPEC is not None and _SPEC.loader is not None
sweep = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = sweep
_SPEC.loader.exec_module(sweep)


# A CRITICAL prohibited-pattern line the sweep flags. Split so this test file
# does not itself trip the aislop pattern-scan.
_BAD_ENV = "OLLAMA_BASE" + "_URL"
BAD_LINE = f'CONFIG = "{_BAD_ENV}=http://x"\n'


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A minimal src/ tree with one clean file and one file holding a violation."""
    _write(tmp_path / "src" / "omniclaude" / "clean.py", "X = 1\n")
    _write(tmp_path / "src" / "omniclaude" / "dirty.py", BAD_LINE)
    return tmp_path


@pytest.mark.unit
class TestFailClosedEscalation:
    def test_none_changed_files_escalates(self) -> None:
        escalate, reason = sweep.should_scan_full_tree(None)
        assert escalate is True
        assert reason == "no_diff_available"

    def test_normal_diff_does_not_escalate(self) -> None:
        escalate, reason = sweep.should_scan_full_tree(
            ["src/omniclaude/routing/router.py", "docs/x.md"]
        )
        assert escalate is False
        assert reason is None

    def test_touching_sweep_source_escalates(self) -> None:
        escalate, reason = sweep.should_scan_full_tree(
            ["scripts/ci/run_aislop_sweep.py", "src/omniclaude/foo.py"]
        )
        assert escalate is True
        assert reason == "validator_infra_changed"

    def test_touching_precommit_sibling_escalates(self) -> None:
        escalate, reason = sweep.should_scan_full_tree(
            ["scripts/ci/run_aislop_precommit.py"]
        )
        assert escalate is True
        assert reason == "validator_infra_changed"


@pytest.mark.unit
class TestResolveScanTargets:
    def test_filters_to_existing_src_python(self, fake_repo: Path) -> None:
        changed = [
            "src/omniclaude/clean.py",  # kept
            "src/omniclaude/dirty.py",  # kept
            "src/omniclaude/gone.py",  # dropped: does not exist
            "docs/readme.md",  # dropped: not .py
            "tests/unit/test_x.py",  # dropped: outside src/
            "src/omniclaude/migrations/001.py",  # dropped: excluded dir
        ]
        targets = sweep.resolve_scan_targets(changed, root=fake_repo)
        assert targets == [
            "src/omniclaude/clean.py",
            "src/omniclaude/dirty.py",
        ]


@pytest.mark.unit
class TestDiffScopedDetection:
    def test_scans_only_changed_files_unchanged_violation_not_reflagged(
        self, fake_repo: Path
    ) -> None:
        """(a) Only the changed file is scanned; dirty.py's violation is invisible
        when it is not in the diff."""
        findings = sweep.collect_findings(
            targets=["src/omniclaude/clean.py"], root=fake_repo
        )
        assert findings == []

    def test_planted_violation_in_changed_file_is_caught(self, fake_repo: Path) -> None:
        """(c) A violation inside a changed file is still flagged."""
        findings = sweep.collect_findings(
            targets=["src/omniclaude/dirty.py"], root=fake_repo
        )
        critical = [f for f in findings if f.severity == "CRITICAL"]
        assert len(critical) == 1
        assert critical[0].check == "prohibited-patterns"
        assert critical[0].path == "src/omniclaude/dirty.py"

    def test_empty_target_list_scans_nothing(self, fake_repo: Path) -> None:
        """A diff that touches no in-scope file yields zero findings (never hangs
        on an empty grep target list)."""
        assert sweep.collect_findings(targets=[], root=fake_repo) == []

    def test_full_tree_scan_catches_violation_anywhere(self, fake_repo: Path) -> None:
        """(b) targets=None scans the whole src/ tree and finds dirty.py even
        though it was not named."""
        findings = sweep.collect_findings(targets=None, root=fake_repo)
        critical = [f for f in findings if f.severity == "CRITICAL"]
        assert len(critical) == 1
        assert critical[0].path == "src/omniclaude/dirty.py"


@pytest.mark.unit
class TestHardcodedTopicEnumExclusionPerFile:
    def test_enum_topic_definition_not_flagged_but_bare_literal_is(
        self, tmp_path: Path
    ) -> None:
        """Enum-body topic literals are canonical definitions (skipped); a bare
        literal outside an enum is a violation — both determined per-file, so
        diff-scoping preserves the distinction."""
        enum_file = tmp_path / "src" / "omniclaude" / "topics.py"
        _write(
            enum_file,
            "from enum import StrEnum\n\n\n"
            "class TopicEnum(StrEnum):\n"
            '    FOO = "onex.evt.omniclaude.foo.v1"\n',
        )
        literal_file = tmp_path / "src" / "omniclaude" / "bad_topics.py"
        _write(literal_file, 'TOPIC = "onex.evt.omniclaude.bar.v1"\n')

        enum_findings = sweep.collect_findings(
            targets=["src/omniclaude/topics.py"], root=tmp_path
        )
        assert [f for f in enum_findings if f.check == "hardcoded-topics"] == []

        literal_findings = sweep.collect_findings(
            targets=["src/omniclaude/bad_topics.py"], root=tmp_path
        )
        topic_errors = [f for f in literal_findings if f.check == "hardcoded-topics"]
        assert len(topic_errors) == 1
        assert topic_errors[0].severity == "ERROR"


@pytest.mark.unit
class TestMainCliEntry:
    def test_changed_files_from_diff_scoped_pass(
        self, fake_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: --changed-files-from over a clean file exits 0."""
        monkeypatch.setattr(sweep, "REPO_ROOT", fake_repo)
        changed = tmp_path / "changed.txt"
        changed.write_text("src/omniclaude/clean.py\n")
        rc = sweep.main(["--changed-files-from", str(changed)])
        assert rc == 0

    def test_changed_files_from_catches_planted_violation(
        self, fake_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: --changed-files-from over the dirty file exits 1."""
        monkeypatch.setattr(sweep, "REPO_ROOT", fake_repo)
        changed = tmp_path / "changed.txt"
        changed.write_text("src/omniclaude/dirty.py\n")
        rc = sweep.main(["--changed-files-from", str(changed)])
        assert rc == 1

    def test_full_tree_flag_scans_everything(
        self, fake_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--full-tree scans the whole tree and catches the violation."""
        monkeypatch.setattr(sweep, "REPO_ROOT", fake_repo)
        rc = sweep.main(["--full-tree"])
        assert rc == 1

    def test_validator_infra_change_escalates_and_catches_unnamed_violation(
        self, fake_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A diff that only names the sweep source escalates to full-tree and
        therefore still catches dirty.py, which was not in the diff."""
        monkeypatch.setattr(sweep, "REPO_ROOT", fake_repo)
        changed = tmp_path / "changed.txt"
        changed.write_text("scripts/ci/run_aislop_sweep.py\n")
        rc = sweep.main(["--changed-files-from", str(changed)])
        assert rc == 1
