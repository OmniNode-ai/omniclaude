# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Idempotency verification for stable.json (OMN-3508).

Verifies that two consecutive feature-dashboard audit runs against the real
plugins/onex/skills/ directory produce byte-identical stable.json output.

This is the programmatic equivalent of the manual verification step in
OMN-3508:

    Run 1 -> copy stable.json -> Run 2 -> diff (must be empty)

Fields excluded from stable JSON (and therefore contributing to idempotency):
    - generated_at: ISO-8601 timestamp (different every run)

Fields that guarantee determinism:
    - skills: sorted alphabetically by name
    - sort_keys=True: all dict keys in sorted order
    - frozen models: no mutable state between runs
    - No timestamps, UUIDs, or other non-deterministic fields in stable output

Test markers:
    @pytest.mark.unit — all tests here
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.classifier import (
    ORCHESTRATOR_TYPES,
    applicable_checks,
)
from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.models.model_result import (
    AuditCheckName,
    AuditCheckStatus,
    GapSeverity,
    ModelAuditCheck,
    ModelContractYaml,
    ModelFeatureDashboardResult,
    ModelGap,
    ModelSkillAudit,
    SkillStatus,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Repository paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[4]  # omniclaude/
_SKILLS_DIR = _REPO_ROOT / "plugins/onex/skills"
_NODES_DIR = _REPO_ROOT / "src/omniclaude/nodes"
_TESTS_DIR = _REPO_ROOT / "tests"
_COVERAGE_TEST = _TESTS_DIR / "unit/nodes/test_skill_node_coverage.py"
_GOLDEN_PATH_DIR = _REPO_ROOT / "plugins/onex/skills/_golden_path_validate"
_STABLE_JSON_NAME = "feature-dashboard.stable.json"

_TOPIC_PATTERN = re.compile(r"onex\.(cmd|evt)\.[a-z0-9_-]+\.[a-z0-9_.-]+\.v\d+")
_TICKET_PATTERN = re.compile(r"OMN-[1-9]\d+")
_EFFECT_TYPES: frozenset[str] = frozenset({"EFFECT_GENERIC"})

# ---------------------------------------------------------------------------
# Audit helpers (mirror of the SKILL.md audit logic)
# These helpers are intentionally self-contained so the test does not
# depend on any external audit runner module that does not yet exist.
# ---------------------------------------------------------------------------


def _kebab_to_snake(name: str) -> str:
    return name.replace("-", "_")


def _load_canonical_coverage_list() -> frozenset[str]:
    """Extract skill names (kebab-case) from test_skill_node_coverage.py."""
    if not _COVERAGE_TEST.exists():
        return frozenset()
    text = _COVERAGE_TEST.read_text(encoding="utf-8")
    match = re.search(r"CANONICAL_SKILLS\s*[:=]\s*\{([^}]+)\}", text, re.DOTALL)
    if not match:
        match = re.search(r"CANONICAL_SKILLS\s*[:=]\s*\[([^\]]+)\]", text, re.DOTALL)
    if not match:
        return frozenset()
    block = match.group(1)
    names = re.findall(r'"([^"]+)"', block)
    names += re.findall(r"'([^']+)'", block)
    return frozenset(names)


def _parse_contract(
    skill_name: str,
) -> tuple[ModelContractYaml | None, str | None]:
    slug = _kebab_to_snake(skill_name)
    path = _NODES_DIR / f"node_skill_{slug}_orchestrator" / "contract.yaml"
    if not path.exists():
        return None, f"contract.yaml not found at {path}"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            return None, "contract.yaml is empty"
        return ModelContractYaml.model_validate(raw), None
    except Exception as exc:
        return None, f"Parse error: {exc}"


def _check_skill_md(skill_name: str) -> ModelAuditCheck:
    skill_path = _SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        return ModelAuditCheck(
            name=AuditCheckName.SKILL_MD,
            status=AuditCheckStatus.FAIL,
            evidence=[f"plugins/onex/skills/{skill_name}/SKILL.md: not found"],
        )
    try:
        text = skill_path.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.index("---", 3)
            fm = yaml.safe_load(text[3:end].strip()) or {}
        else:
            fm = {}
        name_val = fm.get("name", "")
        desc_val = fm.get("description", "")
        if not name_val or not desc_val:
            return ModelAuditCheck(
                name=AuditCheckName.SKILL_MD,
                status=AuditCheckStatus.FAIL,
                evidence=[
                    f"plugins/onex/skills/{skill_name}/SKILL.md: "
                    f"name={'present' if name_val else 'MISSING'}, "
                    f"description={'present' if desc_val else 'MISSING'}"
                ],
            )
        return ModelAuditCheck(
            name=AuditCheckName.SKILL_MD,
            status=AuditCheckStatus.PASS,
            evidence=[
                f"plugins/onex/skills/{skill_name}/SKILL.md: "
                f"name='{name_val}', description present"
            ],
        )
    except Exception as exc:
        return ModelAuditCheck(
            name=AuditCheckName.SKILL_MD,
            status=AuditCheckStatus.FAIL,
            evidence=[f"plugins/onex/skills/{skill_name}/SKILL.md: read error: {exc}"],
        )


def _check_orchestrator_node(skill_name: str) -> ModelAuditCheck:
    slug = _kebab_to_snake(skill_name)
    node_dir = _NODES_DIR / f"node_skill_{slug}_orchestrator"
    if node_dir.exists() and node_dir.is_dir():
        return ModelAuditCheck(
            name=AuditCheckName.ORCHESTRATOR_NODE,
            status=AuditCheckStatus.PASS,
            evidence=[f"src/omniclaude/nodes/node_skill_{slug}_orchestrator/ exists"],
        )
    return ModelAuditCheck(
        name=AuditCheckName.ORCHESTRATOR_NODE,
        status=AuditCheckStatus.FAIL,
        evidence=[f"src/omniclaude/nodes/node_skill_{slug}_orchestrator/ not found"],
    )


def _check_contract_yaml(
    skill_name: str,
    contract: ModelContractYaml | None,
    error_msg: str | None,
) -> ModelAuditCheck:
    if error_msg:
        return ModelAuditCheck(
            name=AuditCheckName.CONTRACT_YAML,
            status=AuditCheckStatus.FAIL,
            evidence=[error_msg],
        )
    assert contract is not None
    node_type = contract.node_type
    in_allowlist = node_type in ORCHESTRATOR_TYPES or node_type in _EFFECT_TYPES
    if not in_allowlist:
        return ModelAuditCheck(
            name=AuditCheckName.CONTRACT_YAML,
            status=AuditCheckStatus.WARN,
            evidence=[f"contract.yaml: node_type='{node_type}' (not in allowlist)"],
        )
    return ModelAuditCheck(
        name=AuditCheckName.CONTRACT_YAML,
        status=AuditCheckStatus.PASS,
        evidence=[f"contract.yaml: node_type='{node_type}'"],
    )


def _check_event_bus_present(
    skill_name: str,
    contract: ModelContractYaml | None,
    override: AuditCheckStatus | None,
) -> ModelAuditCheck:
    if override == AuditCheckStatus.WARN:
        return ModelAuditCheck(
            name=AuditCheckName.EVENT_BUS_PRESENT,
            status=AuditCheckStatus.WARN,
            evidence=["node_type unknown: event_bus check downgraded to WARN"],
        )
    if contract is None or contract.event_bus is None:
        return ModelAuditCheck(
            name=AuditCheckName.EVENT_BUS_PRESENT,
            status=AuditCheckStatus.FAIL,
            evidence=["contract.yaml: event_bus key absent"],
        )
    return ModelAuditCheck(
        name=AuditCheckName.EVENT_BUS_PRESENT,
        status=AuditCheckStatus.PASS,
        evidence=["contract.yaml: event_bus block present"],
    )


def _check_topics_nonempty(
    skill_name: str,
    contract: ModelContractYaml | None,
    override: AuditCheckStatus | None,
) -> ModelAuditCheck:
    if override == AuditCheckStatus.WARN:
        return ModelAuditCheck(
            name=AuditCheckName.TOPICS_NONEMPTY,
            status=AuditCheckStatus.WARN,
            evidence=["node_type unknown: topics check downgraded to WARN"],
        )
    eb = contract.event_bus if contract else None
    sub = len(eb.subscribe_topics) if eb else 0
    pub = len(eb.publish_topics) if eb else 0
    if sub + pub >= 1:
        return ModelAuditCheck(
            name=AuditCheckName.TOPICS_NONEMPTY,
            status=AuditCheckStatus.PASS,
            evidence=[f"topics: {sub} subscribe, {pub} publish"],
        )
    return ModelAuditCheck(
        name=AuditCheckName.TOPICS_NONEMPTY,
        status=AuditCheckStatus.FAIL,
        evidence=["topics: 0 subscribe, 0 publish"],
    )


def _check_topics_namespaced(
    skill_name: str,
    contract: ModelContractYaml | None,
    override: AuditCheckStatus | None,
) -> ModelAuditCheck:
    if override == AuditCheckStatus.WARN:
        return ModelAuditCheck(
            name=AuditCheckName.TOPICS_NAMESPACED,
            status=AuditCheckStatus.WARN,
            evidence=["node_type unknown: topics check downgraded to WARN"],
        )
    eb = contract.event_bus if contract else None
    all_topics: list[str] = []
    if eb:
        all_topics = list(eb.subscribe_topics) + list(eb.publish_topics)
    invalid = [t for t in all_topics if not _TOPIC_PATTERN.fullmatch(t)]
    if not invalid:
        return ModelAuditCheck(
            name=AuditCheckName.TOPICS_NAMESPACED,
            status=AuditCheckStatus.PASS,
            evidence=[f"All {len(all_topics)} topics match namespace pattern"],
        )
    return ModelAuditCheck(
        name=AuditCheckName.TOPICS_NAMESPACED,
        status=AuditCheckStatus.FAIL,
        evidence=[f"Invalid topic(s): {invalid}"],
    )


def _check_test_coverage(
    skill_name: str,
    canonical_list: frozenset[str],
) -> ModelAuditCheck:
    if skill_name in canonical_list:
        return ModelAuditCheck(
            name=AuditCheckName.TEST_COVERAGE,
            status=AuditCheckStatus.PASS,
            evidence=[
                f"skill '{skill_name}' in canonical coverage list "
                f"in test_skill_node_coverage.py"
            ],
        )
    slug = _kebab_to_snake(skill_name)
    score = 0
    signals: list[str] = []
    test_glob = list(_TESTS_DIR.glob(f"**/test_*{slug}*"))
    if test_glob:
        score += 2
        signals.append(f"test file(s) found: {[p.name for p in test_glob[:3]]}")
    for tf in _TESTS_DIR.rglob("test_*.py"):
        try:
            content = tf.read_text(encoding="utf-8", errors="ignore")
            if skill_name in content and "def test_" in content:
                score += 1
                signals.append(f"name found in {tf.name}")
                break
        except Exception:
            pass
    fixture = _GOLDEN_PATH_DIR / f"node_skill_{slug}_orchestrator.json"
    if fixture.exists():
        score += 1
        signals.append(f"golden path fixture: {fixture.name}")
    if score >= 1:
        return ModelAuditCheck(
            name=AuditCheckName.TEST_COVERAGE,
            status=AuditCheckStatus.WARN,
            evidence=[f"covered by heuristic (score={score}): {'; '.join(signals)}"],
        )
    return ModelAuditCheck(
        name=AuditCheckName.TEST_COVERAGE,
        status=AuditCheckStatus.FAIL,
        evidence=[f"No coverage signal found for '{skill_name}' (score=0)"],
    )


def _check_linear_ticket(
    skill_name: str,
    contract: ModelContractYaml | None,
) -> ModelAuditCheck:
    ticket: str | None = None
    if contract and contract.metadata:
        ticket = contract.metadata.ticket
    if ticket and _TICKET_PATTERN.fullmatch(ticket):
        return ModelAuditCheck(
            name=AuditCheckName.LINEAR_TICKET,
            status=AuditCheckStatus.PASS,
            evidence=[f"metadata.ticket='{ticket}'"],
        )
    return ModelAuditCheck(
        name=AuditCheckName.LINEAR_TICKET,
        status=AuditCheckStatus.FAIL,
        evidence=[f"metadata.ticket absent or invalid: '{ticket}'"],
    )


_SEVERITY_FOR_CHECK: dict[AuditCheckName, GapSeverity] = {
    AuditCheckName.SKILL_MD: GapSeverity.CRITICAL,
    AuditCheckName.ORCHESTRATOR_NODE: GapSeverity.CRITICAL,
    AuditCheckName.CONTRACT_YAML: GapSeverity.CRITICAL,
    AuditCheckName.EVENT_BUS_PRESENT: GapSeverity.HIGH,
    AuditCheckName.TOPICS_NONEMPTY: GapSeverity.HIGH,
    AuditCheckName.TOPICS_NAMESPACED: GapSeverity.HIGH,
    AuditCheckName.TEST_COVERAGE: GapSeverity.MEDIUM,
    AuditCheckName.LINEAR_TICKET: GapSeverity.LOW,
}


def _compute_status(checks: list[ModelAuditCheck]) -> SkillStatus:
    critical_high_fail = any(
        c.status == AuditCheckStatus.FAIL
        and _SEVERITY_FOR_CHECK.get(c.name, GapSeverity.LOW)
        in (GapSeverity.CRITICAL, GapSeverity.HIGH)
        for c in checks
    )
    if critical_high_fail:
        return SkillStatus.BROKEN
    any_fail = any(c.status == AuditCheckStatus.FAIL for c in checks)
    any_warn = any(c.status == AuditCheckStatus.WARN for c in checks)
    if any_fail or any_warn:
        return SkillStatus.PARTIAL
    return SkillStatus.WIRED


def _build_gaps(checks: list[ModelAuditCheck]) -> list[ModelGap]:
    return [
        ModelGap(
            layer=c.name,
            severity=_SEVERITY_FOR_CHECK.get(c.name, GapSeverity.LOW),
            message=c.evidence[0] if c.evidence else str(c.name),
            suggested_fix=None,
        )
        for c in checks
        if c.status == AuditCheckStatus.FAIL
    ]


def _audit_skill(skill_name: str, canonical_list: frozenset[str]) -> ModelSkillAudit:
    slug = _kebab_to_snake(skill_name)
    contract, contract_err = _parse_contract(skill_name)
    node_type = contract.node_type if contract else "unknown"
    event_bus_block = contract.event_bus if contract else None
    app_map = applicable_checks(node_type, event_bus_block)

    checks: list[ModelAuditCheck] = []
    if AuditCheckName.SKILL_MD in app_map:
        checks.append(_check_skill_md(skill_name))
    if AuditCheckName.ORCHESTRATOR_NODE in app_map:
        checks.append(_check_orchestrator_node(skill_name))
    if AuditCheckName.CONTRACT_YAML in app_map:
        checks.append(_check_contract_yaml(skill_name, contract, contract_err))
    if AuditCheckName.EVENT_BUS_PRESENT in app_map:
        checks.append(
            _check_event_bus_present(
                skill_name, contract, app_map[AuditCheckName.EVENT_BUS_PRESENT]
            )
        )
    if AuditCheckName.TOPICS_NONEMPTY in app_map:
        checks.append(
            _check_topics_nonempty(
                skill_name, contract, app_map[AuditCheckName.TOPICS_NONEMPTY]
            )
        )
    if AuditCheckName.TOPICS_NAMESPACED in app_map:
        checks.append(
            _check_topics_namespaced(
                skill_name, contract, app_map[AuditCheckName.TOPICS_NAMESPACED]
            )
        )
    if AuditCheckName.TEST_COVERAGE in app_map:
        checks.append(_check_test_coverage(skill_name, canonical_list))
    if AuditCheckName.LINEAR_TICKET in app_map:
        checks.append(_check_linear_ticket(skill_name, contract))

    status = _compute_status(checks)
    return ModelSkillAudit(
        name=skill_name,
        slug=slug,
        node_type=node_type,
        status=status,
        checks=checks,
        gaps=_build_gaps(checks),
    )


def _run_audit(output_dir: Path) -> Path:
    """Run the full audit against the real skills directory. Returns stable.json path."""
    skill_names = sorted(
        d.name
        for d in _SKILLS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_") and (d / "SKILL.md").exists()
    )
    canonical_list = _load_canonical_coverage_list()
    skill_audits = sorted(
        [_audit_skill(name, canonical_list) for name in skill_names],
        key=lambda s: s.name,
    )
    broken = sum(1 for s in skill_audits if s.status == SkillStatus.BROKEN)
    partial = sum(1 for s in skill_audits if s.status == SkillStatus.PARTIAL)
    wired = sum(1 for s in skill_audits if s.status == SkillStatus.WIRED)
    unknown = sum(1 for s in skill_audits if s.status == SkillStatus.UNKNOWN)
    result = ModelFeatureDashboardResult(
        generated_at=datetime.now(tz=UTC).isoformat(),
        total=len(skill_audits),
        wired=wired,
        partial=partial,
        broken=broken,
        unknown=unknown,
        failed=False,
        fail_reason=None,
        skills=skill_audits,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    stable_path = output_dir / _STABLE_JSON_NAME
    stable_data = result.stable_json()
    stable_path.write_text(
        json.dumps(stable_data, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return stable_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRealAuditIdempotency:
    """Idempotency tests against the real plugins/onex/skills/ directory.

    These tests constitute the programmatic verification required by OMN-3508:
    two consecutive audit runs on the same codebase state must produce
    byte-identical stable.json output.

    Stability guarantees:
        - ``generated_at`` excluded from stable JSON (different per run)
        - ``skills`` sorted alphabetically by name
        - ``sort_keys=True`` on all dict keys
        - Frozen models: no mutable state
    """

    def test_two_consecutive_runs_byte_identical(self) -> None:
        """Core idempotency check: run audit twice, diff must be empty.

        Equivalent to:
            Run 1 -> stable-run1.json
            Run 2 -> stable-run2.json
            diff stable-run1.json stable-run2.json && echo PASS
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            dir1 = Path(tmpdir) / "run1"
            dir2 = Path(tmpdir) / "run2"

            path1 = _run_audit(dir1)
            path2 = _run_audit(dir2)

            bytes1 = path1.read_bytes()
            bytes2 = path2.read_bytes()

            assert bytes1 == bytes2, (
                f"Audit runs produced different stable.json output.\n"
                f"Run 1 size: {len(bytes1)} bytes\n"
                f"Run 2 size: {len(bytes2)} bytes\n"
                "Check for non-deterministic fields (timestamps, UUIDs, "
                "unsorted keys, non-sorted skill lists)."
            )

    def test_stable_json_excludes_generated_at(self) -> None:
        """stable.json must not contain generated_at regardless of run time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _run_audit(Path(tmpdir))
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "generated_at" not in data, (
                "generated_at must be excluded from stable.json"
            )

    def test_top_level_keys_sorted(self) -> None:
        """All top-level keys in stable.json must be in sorted order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _run_audit(Path(tmpdir))
            # Parse preserving order
            raw = path.read_text(encoding="utf-8")
            data_ordered = json.loads(raw, object_pairs_hook=dict)
            keys = list(data_ordered.keys())
            assert keys == sorted(keys), f"Top-level keys not sorted: {keys}"

    def test_skills_sorted_alphabetically(self) -> None:
        """Skills array in stable.json must be sorted alphabetically by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _run_audit(Path(tmpdir))
            data = json.loads(path.read_text(encoding="utf-8"))
            names = [s["name"] for s in data["skills"]]
            assert names == sorted(names), (
                f"Skills not sorted alphabetically: first disorder at "
                f"{next((i, names[i], names[i + 1]) for i in range(len(names) - 1) if names[i] > names[i + 1])}"
            )

    def test_skills_count_matches_directory(self) -> None:
        """Number of skills in stable.json matches actual skill count on disk."""
        actual_count = sum(
            1
            for d in _SKILLS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith("_") and (d / "SKILL.md").exists()
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _run_audit(Path(tmpdir))
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["total"] == actual_count, (
                f"stable.json total={data['total']} but {actual_count} skills on disk"
            )
            assert len(data["skills"]) == actual_count

    def test_same_bytes_different_run_timestamps(self) -> None:
        """Stable JSON is identical even when runs happen at different times.

        This explicitly verifies that generated_at (the only per-run
        non-deterministic field) does not leak into the stable output.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = _run_audit(Path(tmpdir) / "run1")
            path2 = _run_audit(Path(tmpdir) / "run2")

            # Both paths exist
            assert path1.exists()
            assert path2.exists()

            # Parse both to confirm generated_at excluded
            d1 = json.loads(path1.read_text(encoding="utf-8"))
            d2 = json.loads(path2.read_text(encoding="utf-8"))
            assert "generated_at" not in d1
            assert "generated_at" not in d2

            # Byte-identical despite different run timestamps
            assert path1.read_bytes() == path2.read_bytes(), (
                "Stable JSON must not change between runs with different timestamps"
            )
