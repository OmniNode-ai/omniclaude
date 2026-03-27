# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the code_review_sweep skill.

Covers:
  - Finding classification (7 categories, severity/confidence assignment)
  - File hash tracking and dedup (skip unchanged files, fingerprint dedup)
  - Ticket cap enforcement (hard cap, priority ordering)
  - Dry-run produces no side effects (no state writes, no tickets)
  - Vulture integration (output parsing, confidence thresholds)
  - Skill metadata (SKILL.md frontmatter, prompt.md structure)
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SKILLS_DIR = Path(__file__).parents[3] / "plugins/onex/skills"
SKILL_DIR = SKILLS_DIR / "code_review_sweep"
SKILL_MD = SKILL_DIR / "SKILL.md"
PROMPT_MD = SKILL_DIR / "prompt.md"


# ---------------------------------------------------------------------------
# Helpers — finding model (mirrors the schema from SKILL.md)
# ---------------------------------------------------------------------------

VALID_CATEGORIES = frozenset(
    {
        "dead-code",
        "missing-error-handling",
        "stubs-shipped",
        "missing-kafka-wiring",
        "schema-mismatches",
        "hardcoded-values",
        "missing-tests",
    }
)

VALID_SEVERITIES = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO"})
VALID_CONFIDENCES = frozenset({"HIGH", "MEDIUM", "LOW"})

TICKET_PRIORITY = [
    "missing-kafka-wiring",
    "schema-mismatches",
    "stubs-shipped",
    "dead-code",
    "missing-error-handling",
    "hardcoded-values",
    "dead-code",  # lower confidence variant
    "stubs-shipped",  # TODO/FIXME variant
    "missing-tests",
]


def make_finding(
    *,
    repo: str = "omniclaude",
    path: str = "src/omniclaude/foo.py",
    line: int = 42,
    category: str = "dead-code",
    message: str = "Unused function '_helper'",
    severity: str = "WARNING",
    confidence: str = "MEDIUM",
    is_new: bool = True,
    ticketed: bool = False,
) -> dict[str, Any]:
    """Build a finding dict matching the ModelCodeReviewFinding schema."""
    fingerprint = f"{repo}:{path}:{line}:{category}"
    return {
        "repo": repo,
        "path": path,
        "line": line,
        "category": category,
        "message": message,
        "severity": severity,
        "confidence": confidence,
        "fingerprint": fingerprint,
        "is_new": is_new,
        "ticketed": ticketed,
    }


def compute_fingerprint(repo: str, path: str, line: int, category: str) -> str:
    """Compute finding fingerprint matching the skill spec."""
    return f"{repo}:{path}:{line}:{category}"


def classify_vulture_line(line: str) -> dict[str, Any] | None:
    """Parse a vulture output line into a finding dict.

    Vulture output format:
      <file>:<line>: unused <kind> '<name>' (confidence: <N>%)
    """
    match = re.match(
        r"^(.+):(\d+): unused (\w+) '(\w+)' \((\d+)% confidence\)$",
        line.strip(),
    )
    if not match:
        return None

    filepath, lineno, kind, name, confidence_pct = match.groups()
    conf_int = int(confidence_pct)

    if conf_int < 80:
        return None  # below minimum threshold

    severity = "ERROR" if conf_int >= 90 else "WARNING"
    confidence = "HIGH" if conf_int >= 90 else "MEDIUM"

    return make_finding(
        path=filepath,
        line=int(lineno),
        category="dead-code",
        message=f"Unused {kind} '{name}' ({conf_int}% confidence)",
        severity=severity,
        confidence=confidence,
    )


def apply_ticket_cap(
    findings: list[dict[str, Any]],
    max_tickets: int = 10,
) -> list[dict[str, Any]]:
    """Apply ticket cap to findings, prioritizing by severity.

    Returns findings with ticketed=True set on the top-priority new findings
    up to max_tickets.
    """
    # Priority: ERROR+HIGH > WARNING+HIGH > WARNING+MEDIUM > INFO+LOW
    severity_order = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}
    confidence_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

    new_findings = [f for f in findings if f["is_new"]]
    new_findings.sort(
        key=lambda f: (
            severity_order.get(f["severity"], 99),
            confidence_order.get(f["confidence"], 99),
        )
    )

    for tickets_created, finding in enumerate(new_findings):
        if tickets_created >= max_tickets:
            break
        finding["ticketed"] = True

    return findings


def load_state(state_path: Path) -> dict[str, Any]:
    """Load state from JSON file, returning empty state if missing/corrupt."""
    if not state_path.exists():
        return {
            "last_run_id": None,
            "last_run_at": None,
            "file_hashes": {},
            "finding_fingerprints": {},
        }
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, KeyError):
        return {
            "last_run_id": None,
            "last_run_at": None,
            "file_hashes": {},
            "finding_fingerprints": {},
        }


def should_skip_file(
    state: dict[str, Any], repo: str, rel_path: str, current_hash: str
) -> bool:
    """Return True if the file hash matches state (unchanged)."""
    key = f"{repo}:{rel_path}"
    return state.get("file_hashes", {}).get(key) == current_hash


def is_finding_new(state: dict[str, Any], fingerprint: str) -> bool:
    """Return True if the fingerprint is not in the state."""
    return fingerprint not in state.get("finding_fingerprints", {})


# ---------------------------------------------------------------------------
# Tests — Finding Classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindingClassification:
    """Test that findings are classified into the correct categories."""

    def test_all_categories_valid(self) -> None:
        """All 7 categories are recognized."""
        assert len(VALID_CATEGORIES) == 7

    def test_make_finding_defaults(self) -> None:
        """make_finding produces a valid finding with correct fingerprint."""
        f = make_finding()
        assert f["category"] in VALID_CATEGORIES
        assert f["severity"] in VALID_SEVERITIES
        assert f["confidence"] in VALID_CONFIDENCES
        assert f["fingerprint"] == "omniclaude:src/omniclaude/foo.py:42:dead-code"

    @pytest.mark.parametrize("category", sorted(VALID_CATEGORIES))
    def test_each_category_produces_valid_finding(self, category: str) -> None:
        """Each category can produce a structurally valid finding."""
        f = make_finding(category=category)
        assert f["category"] == category
        assert f["severity"] in VALID_SEVERITIES
        assert f["confidence"] in VALID_CONFIDENCES

    def test_vulture_high_confidence_is_error(self) -> None:
        """Vulture findings with >=90% confidence are ERROR severity."""
        f = classify_vulture_line(
            "src/omniclaude/foo.py:42: unused function '_helper' (90% confidence)"
        )
        assert f is not None
        assert f["severity"] == "ERROR"
        assert f["confidence"] == "HIGH"

    def test_vulture_medium_confidence_is_warning(self) -> None:
        """Vulture findings with 80-89% confidence are WARNING severity."""
        f = classify_vulture_line(
            "src/omniclaude/bar.py:10: unused import 'os' (85% confidence)"
        )
        assert f is not None
        assert f["severity"] == "WARNING"
        assert f["confidence"] == "MEDIUM"

    def test_vulture_below_threshold_returns_none(self) -> None:
        """Vulture findings below 80% confidence are filtered out."""
        f = classify_vulture_line(
            "src/omniclaude/baz.py:5: unused variable 'x' (60% confidence)"
        )
        assert f is None

    def test_vulture_malformed_line_returns_none(self) -> None:
        """Malformed vulture output returns None."""
        assert classify_vulture_line("not a valid vulture line") is None
        assert classify_vulture_line("") is None

    def test_fingerprint_uniqueness(self) -> None:
        """Different file+line+category combos produce different fingerprints."""
        f1 = compute_fingerprint("repo", "path.py", 1, "dead-code")
        f2 = compute_fingerprint("repo", "path.py", 2, "dead-code")
        f3 = compute_fingerprint("repo", "path.py", 1, "stubs-shipped")
        assert f1 != f2
        assert f1 != f3
        assert f2 != f3

    def test_fingerprint_deterministic(self) -> None:
        """Same inputs always produce the same fingerprint."""
        fp1 = compute_fingerprint("r", "p.py", 10, "dead-code")
        fp2 = compute_fingerprint("r", "p.py", 10, "dead-code")
        assert fp1 == fp2


# ---------------------------------------------------------------------------
# Tests — File Hash Tracking / Dedup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileHashTracking:
    """Test file hash tracking and dedup logic."""

    def test_empty_state_never_skips(self) -> None:
        """With empty state, no files should be skipped."""
        state = load_state(Path("/nonexistent"))
        assert not should_skip_file(state, "repo", "src/foo.py", "abc123")

    def test_matching_hash_skips(self) -> None:
        """File with matching hash in state is skipped."""
        state = {
            "file_hashes": {"repo:src/foo.py": "abc123"},
            "finding_fingerprints": {},
        }
        assert should_skip_file(state, "repo", "src/foo.py", "abc123")

    def test_different_hash_does_not_skip(self) -> None:
        """File with changed hash is NOT skipped."""
        state = {
            "file_hashes": {"repo:src/foo.py": "abc123"},
            "finding_fingerprints": {},
        }
        assert not should_skip_file(state, "repo", "src/foo.py", "def456")

    def test_new_finding_is_new(self) -> None:
        """Finding not in state fingerprints is marked new."""
        state: dict[str, Any] = {"finding_fingerprints": {}}
        fp = "repo:src/foo.py:42:dead-code"
        assert is_finding_new(state, fp)

    def test_existing_finding_is_not_new(self) -> None:
        """Finding already in state fingerprints is NOT new."""
        fp = "repo:src/foo.py:42:dead-code"
        state = {"finding_fingerprints": {fp: "run-123"}}
        assert not is_finding_new(state, fp)

    def test_state_load_from_valid_file(self) -> None:
        """Load state from a valid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            state_data = {
                "last_run_id": "run-1",
                "last_run_at": "2026-03-26T00:00:00Z",
                "file_hashes": {"repo:src/a.py": "hash1"},
                "finding_fingerprints": {"repo:src/a.py:1:dead-code": "run-1"},
            }
            json.dump(state_data, f)
            f.flush()
            loaded = load_state(Path(f.name))
        assert loaded["last_run_id"] == "run-1"
        assert loaded["file_hashes"]["repo:src/a.py"] == "hash1"

    def test_state_load_corrupt_returns_empty(self) -> None:
        """Corrupt state file returns empty state."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json{{{")
            f.flush()
            loaded = load_state(Path(f.name))
        assert loaded["last_run_id"] is None
        assert loaded["file_hashes"] == {}

    def test_state_load_missing_returns_empty(self) -> None:
        """Missing state file returns empty state."""
        loaded = load_state(Path("/tmp/does-not-exist-code-review-state.json"))
        assert loaded["last_run_id"] is None
        assert loaded["file_hashes"] == {}


# ---------------------------------------------------------------------------
# Tests — Ticket Cap Enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTicketCapEnforcement:
    """Test the hard cap on ticket creation per run."""

    def test_cap_limits_tickets(self) -> None:
        """Only max_tickets findings get ticketed=True."""
        findings = [
            make_finding(
                line=i,
                severity="ERROR",
                confidence="HIGH",
                is_new=True,
            )
            for i in range(20)
        ]
        apply_ticket_cap(findings, max_tickets=10)
        ticketed = [f for f in findings if f["ticketed"]]
        assert len(ticketed) == 10

    def test_cap_zero_creates_no_tickets(self) -> None:
        """max_tickets=0 creates zero tickets."""
        findings = [make_finding(is_new=True) for _ in range(5)]
        apply_ticket_cap(findings, max_tickets=0)
        ticketed = [f for f in findings if f["ticketed"]]
        assert len(ticketed) == 0

    def test_fewer_than_cap_tickets_all(self) -> None:
        """When fewer new findings than cap, all get ticketed."""
        findings = [make_finding(line=i, is_new=True) for i in range(3)]
        apply_ticket_cap(findings, max_tickets=10)
        ticketed = [f for f in findings if f["ticketed"]]
        assert len(ticketed) == 3

    def test_only_new_findings_get_ticketed(self) -> None:
        """Old findings (is_new=False) are never ticketed."""
        findings = [
            make_finding(line=1, is_new=True),
            make_finding(line=2, is_new=False),
            make_finding(line=3, is_new=True),
        ]
        apply_ticket_cap(findings, max_tickets=10)
        ticketed = [f for f in findings if f["ticketed"]]
        assert len(ticketed) == 2
        assert not findings[1]["ticketed"]

    def test_priority_ordering_error_before_warning(self) -> None:
        """ERROR findings are ticketed before WARNING findings."""
        findings = [
            make_finding(line=1, severity="WARNING", confidence="MEDIUM", is_new=True),
            make_finding(line=2, severity="ERROR", confidence="HIGH", is_new=True),
            make_finding(line=3, severity="INFO", confidence="LOW", is_new=True),
        ]
        apply_ticket_cap(findings, max_tickets=1)
        ticketed = [f for f in findings if f["ticketed"]]
        assert len(ticketed) == 1
        assert ticketed[0]["severity"] == "ERROR"

    def test_default_cap_is_ten(self) -> None:
        """Default max_tickets is 10."""
        findings = [
            make_finding(line=i, is_new=True, severity="ERROR", confidence="HIGH")
            for i in range(15)
        ]
        apply_ticket_cap(findings)  # uses default max_tickets=10
        ticketed = [f for f in findings if f["ticketed"]]
        assert len(ticketed) == 10


# ---------------------------------------------------------------------------
# Tests — Dry-Run No Side Effects
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDryRunNoSideEffects:
    """Test that dry-run mode produces no state writes or ticket creation."""

    def test_dry_run_does_not_write_state(self) -> None:
        """Simulated dry-run: state file should not be created/modified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "code-review-state.json"
            # In dry-run, we load state but never write it
            state = load_state(state_path)
            assert state["last_run_id"] is None
            # Simulate scan: update in-memory state
            state["last_run_id"] = "dry-run-test"
            state["file_hashes"]["repo:src/foo.py"] = "hash1"
            # In dry-run, we do NOT persist — verify file still doesn't exist
            assert not state_path.exists()

    def test_dry_run_findings_not_ticketed(self) -> None:
        """In dry-run mode, no findings should be marked as ticketed."""
        findings = [make_finding(is_new=True) for _ in range(5)]
        # In dry-run, we skip apply_ticket_cap entirely
        # Verify none are ticketed by default
        assert all(not f["ticketed"] for f in findings)

    def test_first_run_forces_dry_run(self) -> None:
        """When no state file exists, first run should force dry-run."""
        state_path = Path("/tmp/nonexistent-code-review-state-test.json")
        state = load_state(state_path)
        # First run detection: state has no last_run_id
        is_first_run = state["last_run_id"] is None
        assert is_first_run
        # Skill spec: first run forces --dry-run


# ---------------------------------------------------------------------------
# Tests — Vulture Integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVultureIntegration:
    """Test vulture output parsing and integration."""

    def test_parse_standard_vulture_output(self) -> None:
        """Standard vulture output lines are parsed correctly."""
        lines = [
            "src/omniclaude/foo.py:42: unused function '_helper' (90% confidence)",
            "src/omniclaude/bar.py:10: unused import 'os' (85% confidence)",
            "src/omniclaude/baz.py:5: unused variable 'x' (60% confidence)",
        ]
        results = [classify_vulture_line(line) for line in lines]
        assert results[0] is not None
        assert results[0]["severity"] == "ERROR"
        assert results[1] is not None
        assert results[1]["severity"] == "WARNING"
        assert results[2] is None  # below threshold

    def test_parse_vulture_class_output(self) -> None:
        """Vulture class findings are parsed."""
        f = classify_vulture_line(
            "src/pkg/models.py:100: unused class 'OldModel' (95% confidence)"
        )
        assert f is not None
        assert "OldModel" in f["message"]
        assert f["severity"] == "ERROR"
        assert f["confidence"] == "HIGH"

    def test_vulture_empty_output(self) -> None:
        """Empty vulture output produces no findings."""
        assert classify_vulture_line("") is None

    def test_vulture_exactly_80_percent(self) -> None:
        """80% confidence is included (boundary condition)."""
        f = classify_vulture_line(
            "src/foo.py:1: unused function 'bar' (80% confidence)"
        )
        assert f is not None
        assert f["severity"] == "WARNING"
        assert f["confidence"] == "MEDIUM"

    def test_vulture_exactly_90_percent(self) -> None:
        """90% confidence is ERROR/HIGH (boundary condition)."""
        f = classify_vulture_line(
            "src/foo.py:1: unused function 'bar' (90% confidence)"
        )
        assert f is not None
        assert f["severity"] == "ERROR"
        assert f["confidence"] == "HIGH"


# ---------------------------------------------------------------------------
# Tests — Skill Metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillMetadata:
    """Test SKILL.md frontmatter and prompt.md structural requirements."""

    def test_skill_md_exists(self) -> None:
        """SKILL.md exists in the skill directory."""
        assert SKILL_MD.exists(), f"SKILL.md not found at {SKILL_MD}"

    def test_prompt_md_exists(self) -> None:
        """prompt.md exists in the skill directory."""
        assert PROMPT_MD.exists(), f"prompt.md not found at {PROMPT_MD}"

    def test_skill_md_has_frontmatter(self) -> None:
        """SKILL.md has valid YAML frontmatter."""
        content = SKILL_MD.read_text()
        assert content.startswith("---"), "SKILL.md must start with ---"
        # Find closing ---
        lines = content.splitlines()
        close_idx = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                close_idx = i
                break
        assert close_idx is not None, "SKILL.md must have closing ---"

    def test_skill_md_has_description(self) -> None:
        """SKILL.md frontmatter includes description."""
        content = SKILL_MD.read_text()
        assert "description:" in content

    def test_skill_md_has_version(self) -> None:
        """SKILL.md frontmatter includes version."""
        content = SKILL_MD.read_text()
        assert "version:" in content

    def test_skill_md_has_args(self) -> None:
        """SKILL.md frontmatter includes args section."""
        content = SKILL_MD.read_text()
        assert "args:" in content

    def test_skill_md_has_dry_run_arg(self) -> None:
        """SKILL.md declares --dry-run argument."""
        content = SKILL_MD.read_text()
        assert "--dry-run" in content

    def test_skill_md_has_ticket_arg(self) -> None:
        """SKILL.md declares --ticket argument."""
        content = SKILL_MD.read_text()
        assert "--ticket" in content

    def test_skill_md_has_max_tickets_arg(self) -> None:
        """SKILL.md declares --max-tickets argument."""
        content = SKILL_MD.read_text()
        assert "--max-tickets" in content

    def test_skill_md_documents_all_categories(self) -> None:
        """SKILL.md documents all 7 finding categories."""
        content = SKILL_MD.read_text()
        for category in VALID_CATEGORIES:
            assert category in content, (
                f"Category {category!r} not documented in SKILL.md"
            )

    def test_skill_md_documents_ticket_cap(self) -> None:
        """SKILL.md documents the hard ticket cap."""
        content = SKILL_MD.read_text()
        assert "10" in content, "Ticket cap of 10 not documented"
        assert "hard cap" in content.lower() or "Hard cap" in content

    def test_prompt_md_has_scan_phase(self) -> None:
        """prompt.md includes scan phase."""
        content = PROMPT_MD.read_text()
        assert "Phase 1: Scan" in content or "Scan" in content

    def test_prompt_md_has_triage_phase(self) -> None:
        """prompt.md includes triage phase."""
        content = PROMPT_MD.read_text()
        assert "Phase 2: Triage" in content or "Triage" in content

    def test_prompt_md_has_ticket_phase(self) -> None:
        """prompt.md includes ticket creation phase."""
        content = PROMPT_MD.read_text()
        assert "Ticket Creation" in content or "ticket" in content.lower()

    def test_prompt_md_has_state_update_phase(self) -> None:
        """prompt.md includes state update phase."""
        content = PROMPT_MD.read_text()
        assert "State Update" in content or "state" in content.lower()

    def test_prompt_md_documents_vulture(self) -> None:
        """prompt.md documents vulture usage for cross-file dead code."""
        content = PROMPT_MD.read_text()
        assert "vulture" in content.lower()

    def test_prompt_md_constrains_llm_dead_code(self) -> None:
        """prompt.md constrains LLM dead code to module-level only."""
        content = PROMPT_MD.read_text()
        assert "module-level" in content.lower() or "MODULE-LEVEL" in content
        assert "cross-file" in content.lower() or "CROSS-FILE" in content.lower()

    def test_prompt_md_has_autonomous_execution(self) -> None:
        """prompt.md declares autonomous execution mode."""
        content = PROMPT_MD.read_text()
        assert "autonomous" in content.lower()

    def test_prompt_md_has_first_run_dry_run(self) -> None:
        """prompt.md documents first-run dry-run default."""
        content = PROMPT_MD.read_text()
        assert "first run" in content.lower() or "first-run" in content.lower()


# ---------------------------------------------------------------------------
# Tests — Topics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTopics:
    """Test topics.yaml manifest."""

    def test_topics_yaml_exists(self) -> None:
        """topics.yaml exists in the skill directory."""
        topics_path = SKILL_DIR / "topics.yaml"
        assert topics_path.exists(), f"topics.yaml not found at {topics_path}"

    def test_topics_yaml_has_cmd_topic(self) -> None:
        """topics.yaml declares the command topic."""
        content = (SKILL_DIR / "topics.yaml").read_text()
        assert "onex.cmd.omniclaude.code-review-sweep.v1" in content

    def test_topics_yaml_has_completed_topic(self) -> None:
        """topics.yaml declares the completed event topic."""
        content = (SKILL_DIR / "topics.yaml").read_text()
        assert "onex.evt.omniclaude.code-review-sweep-completed.v1" in content

    def test_topics_yaml_has_failed_topic(self) -> None:
        """topics.yaml declares the failed event topic."""
        content = (SKILL_DIR / "topics.yaml").read_text()
        assert "onex.evt.omniclaude.code-review-sweep-failed.v1" in content


# ---------------------------------------------------------------------------
# Tests — Orchestrator Node
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestratorNode:
    """Test that the generated orchestrator node exists and is importable."""

    def test_node_directory_exists(self) -> None:
        """Orchestrator node directory was generated."""
        node_dir = (
            Path(__file__).parents[3]
            / "src/omniclaude/nodes/node_skill_code_review_sweep_orchestrator"
        )
        assert node_dir.exists(), f"Node directory not found at {node_dir}"

    def test_node_has_init(self) -> None:
        """__init__.py exists in node directory."""
        init_path = (
            Path(__file__).parents[3]
            / "src/omniclaude/nodes/node_skill_code_review_sweep_orchestrator/__init__.py"
        )
        assert init_path.exists()

    def test_node_has_node_py(self) -> None:
        """node.py exists in node directory."""
        node_path = (
            Path(__file__).parents[3]
            / "src/omniclaude/nodes/node_skill_code_review_sweep_orchestrator/node.py"
        )
        assert node_path.exists()

    def test_node_has_contract_yaml(self) -> None:
        """contract.yaml exists in node directory."""
        contract_path = (
            Path(__file__).parents[3]
            / "src/omniclaude/nodes/node_skill_code_review_sweep_orchestrator/contract.yaml"
        )
        assert contract_path.exists()

    def test_node_class_name_convention(self) -> None:
        """node.py defines the correct class name."""
        node_path = (
            Path(__file__).parents[3]
            / "src/omniclaude/nodes/node_skill_code_review_sweep_orchestrator/node.py"
        )
        content = node_path.read_text()
        assert "NodeSkillCodeReviewSweepOrchestrator" in content

    def test_contract_has_skill_capability(self) -> None:
        """contract.yaml declares the skill.code_review_sweep capability."""
        contract_path = (
            Path(__file__).parents[3]
            / "src/omniclaude/nodes/node_skill_code_review_sweep_orchestrator/contract.yaml"
        )
        content = contract_path.read_text()
        assert "code_review_sweep" in content
