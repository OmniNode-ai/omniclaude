# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the closeout phase compliance checker.

Verifies that:
1. The contract YAML is valid and covers all phases in cron-closeout.sh
2. The compliance checker catches known-bad patterns (read-only, localhost)
3. The current cron-closeout.sh passes compliance

[OMN-7383]
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# Import the compliance checker
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
import importlib.util

spec = importlib.util.spec_from_file_location(
    "check_closeout_phase_compliance",
    SCRIPTS_DIR / "check_closeout_phase_compliance.py",
)
assert spec is not None
assert spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


CONTRACT_PATH = SCRIPTS_DIR / "closeout-phase-contract.yaml"
CLOSEOUT_PATH = SCRIPTS_DIR / "cron-closeout.sh"


class TestContractYaml:
    """Verify the contract YAML itself is well-formed."""

    def test_contract_exists(self) -> None:
        assert CONTRACT_PATH.exists(), "closeout-phase-contract.yaml missing"

    def test_contract_parses(self) -> None:
        with open(CONTRACT_PATH) as f:
            contract = yaml.safe_load(f)
        assert contract is not None
        assert "phases" in contract
        assert len(contract["phases"]) > 0

    def test_all_phases_have_required_fields(self) -> None:
        with open(CONTRACT_PATH) as f:
            contract = yaml.safe_load(f)
        for phase in contract["phases"]:
            assert "id" in phase, f"Phase missing 'id': {phase}"
            assert "name" in phase, f"Phase {phase['id']} missing 'name'"
            assert "category" in phase, f"Phase {phase['id']} missing 'category'"
            assert "blocking" in phase, f"Phase {phase['id']} missing 'blocking'"
            assert "expected_action" in phase, (
                f"Phase {phase['id']} missing 'expected_action'"
            )

    def test_phase_ids_are_unique(self) -> None:
        with open(CONTRACT_PATH) as f:
            contract = yaml.safe_load(f)
        ids = [p["id"] for p in contract["phases"]]
        assert len(ids) == len(set(ids)), f"Duplicate phase IDs: {ids}"

    def test_contract_covers_all_script_phases(self) -> None:
        """Every run_phase call in cron-closeout.sh should have a contract."""
        if not CLOSEOUT_PATH.exists():
            pytest.skip("cron-closeout.sh not found")

        prompts = checker.extract_phase_prompts(CLOSEOUT_PATH)
        with open(CONTRACT_PATH) as f:
            contract = yaml.safe_load(f)
        contract_ids = {p["id"] for p in contract["phases"]}

        missing = set(prompts.keys()) - contract_ids
        assert not missing, f"Phases in script but missing from contract: {missing}"


class TestPromptExtraction:
    """Verify the prompt extractor works on real and synthetic scripts."""

    def test_extracts_from_real_script(self) -> None:
        if not CLOSEOUT_PATH.exists():
            pytest.skip("cron-closeout.sh not found")

        prompts = checker.extract_phase_prompts(CLOSEOUT_PATH)
        # Should find at least the major phases
        assert "A1_merge_sweep" in prompts
        # C1 is C1_release_check on main (renamed to C1_release after OMN-7401)
        assert "C1_release_check" in prompts or "C1_release" in prompts
        assert "E1_foundation_tests" in prompts

    def test_extracts_prompt_text(self) -> None:
        if not CLOSEOUT_PATH.exists():
            pytest.skip("cron-closeout.sh not found")

        prompts = checker.extract_phase_prompts(CLOSEOUT_PATH)
        # C1 is C1_release_check on main (pre-OMN-7401), C1_release after
        c1_id = "C1_release" if "C1_release" in prompts else "C1_release_check"
        c1 = prompts.get(c1_id, "")
        # On main (pre-OMN-7401), C1 is report-only and won't contain /release.
        # After OMN-7401 merges, C1_release will contain /release.
        assert len(c1) > 0, f"C1 phase ({c1_id}) prompt should not be empty"


class TestComplianceChecker:
    """Test the compliance logic against synthetic data."""

    def _write_contract(self, tmp_path: Path, phases: list[dict]) -> Path:
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(
            yaml.dump({"contract_version": "1.0.0", "phases": phases})
        )
        return contract_path

    def _write_script(self, tmp_path: Path, phases: dict[str, str]) -> Path:
        script_path = tmp_path / "cron-closeout.sh"
        lines = ["#!/usr/bin/env bash\n"]
        for phase_id, prompt in phases.items():
            lines.append(
                f'run_phase "{phase_id}" \\\n  "{prompt}" \\\n  "Bash,Read"\n\n'
            )
        script_path.write_text("".join(lines))
        return script_path

    def test_passes_when_compliant(self, tmp_path: Path) -> None:
        contract = self._write_contract(
            tmp_path,
            [
                {
                    "id": "C1_release",
                    "name": "Release",
                    "category": "action",
                    "blocking": False,
                    "expected_action": "Execute /release",
                    "required_keywords": ["/release", "--autonomous"],
                }
            ],
        )
        script = self._write_script(
            tmp_path,
            {
                "C1_release": "Execute /release --autonomous for all repos",
            },
        )
        violations = checker.check_compliance(contract, script)
        assert violations == []

    def test_catches_missing_keyword(self, tmp_path: Path) -> None:
        contract = self._write_contract(
            tmp_path,
            [
                {
                    "id": "C1_release",
                    "name": "Release",
                    "category": "action",
                    "blocking": False,
                    "expected_action": "Execute /release",
                    "required_keywords": ["/release"],
                }
            ],
        )
        script = self._write_script(
            tmp_path,
            {
                "C1_release": "Check for unreleased commits and report them",
            },
        )
        violations = checker.check_compliance(contract, script)
        assert len(violations) == 1
        assert "KEYWORD_MISSING" in violations[0]
        assert "/release" in violations[0]

    def test_catches_forbidden_text(self, tmp_path: Path) -> None:
        """This is the exact bug that C1/C2 had — 'Do NOT execute'."""
        contract = self._write_contract(
            tmp_path,
            [
                {
                    "id": "C1_release",
                    "name": "Release",
                    "category": "action",
                    "blocking": False,
                    "expected_action": "Execute /release",
                    "required_keywords": ["/release"],
                    "must_not_contain": ["Do NOT execute", "report only"],
                }
            ],
        )
        script = self._write_script(
            tmp_path,
            {
                "C1_release": "Run /release but Do NOT execute the actual release. Report only.",
            },
        )
        violations = checker.check_compliance(contract, script)
        assert len(violations) == 2
        assert any("FORBIDDEN_TEXT" in v and "Do NOT execute" in v for v in violations)
        assert any("FORBIDDEN_TEXT" in v and "report only" in v for v in violations)

    def test_catches_stale_infra_reference(self, tmp_path: Path) -> None:
        """This is the exact bug E1 had — referencing docker ps after migration."""
        contract = self._write_contract(
            tmp_path,
            [
                {
                    "id": "E1_foundation_tests",
                    "name": "Foundation Verification",
                    "category": "gate",
                    "blocking": True,
                    "expected_action": "Verify on INFRA_HOST",
                    "required_keywords": ["INFRA_HOST"],
                    "infra_consistency": {
                        "must_reference": "INFRA_HOST",
                        "must_not_reference": ["docker ps", "docker logs"],
                    },
                }
            ],
        )
        script = self._write_script(
            tmp_path,
            {
                "E1_foundation_tests": "Run docker ps to check containers. "
                "Also check INFRA_HOST health.",
            },
        )
        violations = checker.check_compliance(contract, script)
        assert len(violations) == 1
        assert "INFRA_STALE" in violations[0]
        assert "docker ps" in violations[0]

    def test_catches_missing_infra_host(self, tmp_path: Path) -> None:
        contract = self._write_contract(
            tmp_path,
            [
                {
                    "id": "B1_runtime_sweep",
                    "name": "Runtime Sweep",
                    "category": "gate",
                    "blocking": True,
                    "expected_action": "Verify on INFRA_HOST",
                    "required_keywords": ["INTEGRATION: PASS"],
                    "infra_consistency": {
                        "must_reference": "INFRA_HOST",
                    },
                }
            ],
        )
        script = self._write_script(
            tmp_path,
            {
                "B1_runtime_sweep": "Check localhost:8085/health. INTEGRATION: PASS",
            },
        )
        violations = checker.check_compliance(contract, script)
        assert len(violations) == 1
        assert "INFRA_MISSING" in violations[0]

    def test_catches_missing_phase(self, tmp_path: Path) -> None:
        contract = self._write_contract(
            tmp_path,
            [
                {
                    "id": "E4_golden_chain",
                    "name": "Golden Chain Sweep",
                    "category": "gate",
                    "blocking": True,
                    "expected_action": "Run golden chain sweep",
                    "required_keywords": ["/golden_chain_sweep"],
                }
            ],
        )
        script = self._write_script(tmp_path, {})
        violations = checker.check_compliance(contract, script)
        assert len(violations) == 1
        assert "MISSING" in violations[0]


class TestCurrentScriptCompliance:
    """Verify the CURRENT cron-closeout.sh against the contract."""

    def test_current_script_is_compliant(self) -> None:
        """The current cron-closeout.sh should pass all contract checks.

        OMN-7401 fixed E1/C1/C2 to use remote INFRA_HOST and execute
        /release and /redeploy autonomously. Zero violations expected.
        """
        if not CONTRACT_PATH.exists() or not CLOSEOUT_PATH.exists():
            pytest.skip("Contract or script not found")

        violations = checker.check_compliance(
            CONTRACT_PATH, CLOSEOUT_PATH, verbose=True
        )
        assert violations == [], (
            "Unexpected violations after OMN-7401 fix:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_passing_phases_are_compliant(self) -> None:
        """Phases that are NOT part of the OMN-7401 fix should pass."""
        if not CONTRACT_PATH.exists() or not CLOSEOUT_PATH.exists():
            pytest.skip("Contract or script not found")

        violations = checker.check_compliance(CONTRACT_PATH, CLOSEOUT_PATH)
        # These phases should NOT have violations
        non_violating = {
            "A1",
            "A2",
            "A3",
            "B1",
            "B2",
            "B3",
            "B4b",
            "B5",
            "B6",
            "D3",
            "E2",
            "E3",
        }
        for v in violations:
            match = re.search(r"Phase\s+(\w+)", v)
            assert match, f"Could not parse phase ID from violation: {v}"
            phase_prefix = match.group(1)[:2]
            assert phase_prefix not in non_violating, (
                f"Unexpected violation in passing phase: {v}"
            )
