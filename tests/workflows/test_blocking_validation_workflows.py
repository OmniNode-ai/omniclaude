# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for blocking validation workflow gates."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CONTRACT_VALIDATION_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "contract-validation.yml"
)


def _load_workflow(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _job(workflow: dict[str, Any], job_name: str) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    job = jobs.get(job_name)
    assert isinstance(job, dict), f"job {job_name!r} must exist"
    return cast("dict[str, Any]", job)


def _step(job: dict[str, Any], step_name: str) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list), "job must define steps"
    step = next(
        item
        for item in steps
        if isinstance(item, dict) and item.get("name") == step_name
    )
    return cast("dict[str, Any]", step)


def test_skill_node_boundary_gate_is_blocking_for_changed_skills() -> None:
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    step = _step(
        _job(workflow, "arch-invariants"), "Validate skill-node boundary (OMN-8094)"
    )
    run = step.get("run")
    assert isinstance(run, str)

    assert step.get("continue-on-error") is not True
    assert "git diff --name-only" in run
    assert "'plugins/onex/skills/**/SKILL.md'" in run
    assert '--skill "$skill"' in run
    assert "--strict" in run
    assert "baseline violations remain tracked separately" in run


def test_contract_proof_resolution_gate_is_blocking() -> None:
    workflow = _load_workflow(CONTRACT_VALIDATION_WORKFLOW_PATH)
    step = _step(_job(workflow, "contract-validation"), "Resolve proof references")
    run = step.get("run")
    assert isinstance(run, str)

    assert step.get("continue-on-error") is not True
    assert "cli_validate_proofs.py" in run
    assert "--json" in run
    assert "json_status=$?" in run
    assert "human_status=$?" in run
    assert "exit 1" in run
    assert "|| echo" not in run
    assert "Phase 1" not in step["name"]


def test_contract_validation_reads_a_pinned_validator_that_accepts_binds_ac() -> None:
    """The composite action reads OCC main, whose schema refused `binds_ac`.

    A contract that binds its criteria (which repo-evidence / dod-verify requires)
    was refused as `dod_evidence.N.binds_ac: Extra inputs are not permitted`. The
    validators are fetched at a full sha instead, as omnimarket and
    omnibase_infra do.
    """
    workflow = _load_workflow(CONTRACT_VALIDATION_WORKFLOW_PATH)
    job = _job(workflow, "contract-validation")
    steps = [item for item in job["steps"] if isinstance(item, dict)]

    assert not [
        item
        for item in steps
        if "onex_change_control/.github/actions/validate-contract"
        in str(item.get("uses", ""))
    ], "the OCC composite action resolves OCC main; fetch the validators at a sha"

    fetch = _step(job, "Check out pinned contract validators")
    run = str(fetch.get("run", ""))
    match = re.search(r"^\s*occ_sha=([0-9a-f]{40})$", run, re.MULTILINE)
    assert match, "the validators must be fetched at a full sha"
    assert "https://github.com/OmniNode-ai/onex_change_control.git" in run
    assert '"$occ_sha"' in run

    validate = _step(job, "Run contract validation")
    assert validate.get("id") == "validate-contract"
    assert "validate-yaml" in str(validate.get("run", ""))


# ---------------------------------------------------------------------------
# OMN-20074: the path-filtered standalone gates folded into ci.yml.
#
# Each of these jobs used to live in its own workflow file whose only required
# context was a nested `occ-preflight / eligibility`, and whose `paths:` filter
# decided whether the file ran at all. Folded into ci.yml, each job keeps its
# name, reads the `changes` job's output for its own filter, and is judged by
# CI Summary's in-run default-deny sweep: a skip passes, a failure fails.
#
# The table below is the ORIGINAL trigger of every folded file, copied from
# dev at dc1a8721c, so the equivalence is checked against what the gate used to
# watch rather than against the new filter itself. The one rewrite is the
# gate's own workflow file, which is now ci.yml.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Folded:
    job_id: str
    name: str
    old_file: str
    paths: tuple[str, ...]
    push: tuple[str, ...]
    dispatch: bool


FOLDED_JOBS: tuple[_Folded, ...] = (
    _Folded(
        "branch-claim-gate",
        "Branch Claim Gate",
        "branch-claim-gate.yml",
        paths=(
            "scripts/branch_claim.py",
            "scripts/claim_index.py",
            "scripts/lane_identity.py",
            "scripts/hooks/pre-push-branch-claim",
            "tests/scripts/test_branch_claim.py",
            "tests/scripts/test_branch_claim_hook.py",
            "tests/scripts/test_lane_identity_canary.py",
            "scripts/hooks/prepare-commit-msg-lane",
            ".github/workflows/branch-claim-gate.yml",
            ".github/workflows/branch-claim-check-reusable.yml",
        ),
        push=("main", "dev", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "check-deterministic-skills",
        "check-deterministic-skills",
        "check-deterministic-skills.yml",
        paths=(
            "plugins/onex/skills/**/SKILL.md",
            "scripts/validation/validate_deterministic_skill_routing.py",
            "tests/validation/test_validate_deterministic_skill_routing.py",
            ".github/workflows/check-deterministic-skills.yml",
        ),
        push=(),
        dispatch=True,
    ),
    _Folded(
        "check-instructional-skills",
        "check-instructional-skills",
        "check-instructional-skills.yml",
        paths=(
            "plugins/onex/skills/**/SKILL.md",
            "scripts/validation/validate_instructional_skill_routing.py",
            ".github/workflows/check-instructional-skills.yml",
        ),
        push=(),
        dispatch=True,
    ),
    _Folded(
        "daemon-venv-skew-gate",
        "Daemon Venv Skew Gate",
        "daemon-venv-skew-gate.yml",
        paths=(
            "uv.lock",
            "scripts/check_daemon_venv_skew.py",
            ".pre-commit-hooks/check-daemon-venv-skew.sh",
            "plugins/onex/hooks/scripts/ensure-plugin-venv.sh",
            ".github/workflows/daemon-venv-skew-gate.yml",
        ),
        push=("main", "dev", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "defect-anchor",
        "gate / Defect Anchor",
        "defect-anchor-gate.yml",
        paths=(
            "docs/evidence/**/*.md",
            "docs/evidence/*.md",
            ".pre-commit-hooks/check-defect-anchor.sh",
            ".github/workflows/defect-anchor-gate.yml",
        ),
        push=("main", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "distribution-classification-lint",
        "Distribution Classification Lint",
        "distribution-classification-lint.yml",
        paths=(
            "plugins/onex/skills/**",
            "plugins/onex/hooks/scripts/**",
            "plugins/onex/agents/configs/**",
            "plugins/distribution_manifest.yaml",
            "scripts/validation/validate_distribution_classification.py",
            "scripts/validation/validate_full_market_skill_inventory.py",
            ".github/workflows/distribution-classification-lint.yml",
        ),
        push=("main", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "check-infra-health-section",
        "gate / Handoff Infra Health",
        "handoff-infra-health-gate.yml",
        paths=(
            "docs/handoffs/**/*.md",
            "docs/**/*handoff*.md",
            "docs/tracking/**/*handoff*.md",
        ),
        push=(),
        dispatch=False,
    ),
    _Folded(
        "hook-log-path-lint",
        "Hook Log Path Lint",
        "hook-log-path-lint.yml",
        paths=("plugins/onex/hooks/scripts/**",),
        push=("main", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "omnimarket-dispatch-drift-gate",
        "Omnimarket Dispatch Drift Gate",
        "omnimarket-dispatch-drift-gate.yml",
        paths=(
            "uv.lock",
            "pyproject.toml",
            "scripts/check_omnimarket_dispatch_drift.py",
            ".pre-commit-hooks/check-omnimarket-dispatch-drift.sh",
            ".github/workflows/omnimarket-dispatch-drift-gate.yml",
        ),
        push=("main", "dev", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "plan-canonical-scripts-gate",
        "Plan Canonical Scripts Gate",
        "plan-canonical-scripts-gate.yml",
        paths=(
            "docs/plans/**/*.md",
            "docs/tracking/**/*.md",
            "tests/scripts/test_lint_plan_canonical_scripts.py",
            "scripts/lint_plan_canonical_scripts.py",
            ".github/workflows/plan-canonical-scripts-gate.yml",
        ),
        push=("main", "dev", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "plan-hard-fields-gate",
        "Plan Hard Fields Gate",
        "plan-hard-fields-gate.yml",
        paths=(
            "docs/plans/**/*.md",
            "docs/tracking/**/*.md",
            "scripts/lint_plan_hard_fields.py",
            ".github/workflows/plan-hard-fields-gate.yml",
        ),
        push=("main", "dev", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "plan-verified-state-gate",
        "Plan Verified State Gate",
        "plan-verified-state-gate.yml",
        paths=(
            "docs/plans/**/*.md",
            "docs/tracking/**/*.md",
            "tests/scripts/test_lint_plan_verified_state.py",
            "scripts/lint_plan_verified_state.py",
            ".github/workflows/plan-verified-state-gate.yml",
        ),
        push=("main", "dev", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "plugin-compat-gate",
        "Plugin compat.yaml presence + schema",
        "plugin-compat-gate.yml",
        paths=(
            "plugins/onex/**",
            "plugins/onex-delegate/**",
            # The original names the dev marketplace directory literally; ci.yml
            # widens it to this glob (see test_marketplace_glob_covers_the_real_directories).
            "plugins/onex-*-marketplace/**",
            ".claude-plugin/marketplace.json",
            "plugins/.claude-plugin/marketplace.json",
            ".github/workflows/plugin-compat-gate.yml",
        ),
        push=("main", "develop", "hotfix/**"),
        dispatch=True,
    ),
    _Folded(
        "precommit-fail-loud-gate",
        "Precommit Fail-Loud Gate",
        "precommit-fail-loud-gate.yml",
        paths=(
            ".pre-commit-config.yaml",
            ".github/workflows/ci.yml",
            "scripts/validation/validate_precommit_fail_loud.py",
            "scripts/validation/validate_precommit_pin_parity.py",
            ".github/workflows/precommit-fail-loud-gate.yml",
        ),
        push=("main", "dev", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "scan-imperative-skills",
        "gate / reject-imperative-skill-patterns",
        "reject-imperative-skills.yml",
        paths=(
            "plugins/onex/skills/**/SKILL.md",
            ".pre-commit-hooks/reject-imperative-skill-patterns.sh",
            ".github/workflows/reject-imperative-skills.yml",
        ),
        push=("main",),
        dispatch=False,
    ),
    _Folded(
        "session-id-canonical-lint",
        "Reject legacy session-id env-var reads",
        "session-id-canonical-lint.yml",
        paths=(
            "src/**",
            "plugins/**",
            "tests/**",
            ".pre-commit-hooks/**",
            ".github/workflows/session-id-canonical-lint.yml",
        ),
        push=(),
        dispatch=False,
    ),
    _Folded(
        "skill-mcp-ref-lint",
        "Skill MCP Reference Lint",
        "skill-mcp-ref-lint.yml",
        paths=(
            "plugins/onex/skills/**/*.md",
            "scripts/lint_skill_mcp_refs.py",
            ".github/workflows/skill-mcp-ref-lint.yml",
        ),
        push=("main", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "skill-receipt-mode-gate",
        "skill-receipt-mode-gate",
        "skill-receipt-mode-gate.yml",
        paths=(
            "plugins/onex/skills/**",
            ".onex_ratchets/skill_receipt_mode_allowlist.yaml",
            "scripts/check_skill_dispatch_receipt_mode_wrapper.sh",
            ".github/workflows/skill-receipt-mode-gate.yml",
        ),
        push=(),
        dispatch=False,
    ),
    _Folded(
        "validate-agent-configs",
        "validate-agent-configs",
        "validate-agent-configs.yml",
        paths=("plugins/onex/agents/configs/**/*.yaml",),
        push=(),
        dispatch=True,
    ),
    _Folded(
        "validate-skill-aspiration",
        "validate",
        "validate-skill-aspiration.yml",
        paths=(
            "plugins/onex/skills/**/*.md",
            "plugins/onex/skills/_lib/validate_skill_aspiration.py",
            "scripts/extract_skill_claims.py",
            "scripts/validation/validate_skill_aspiration.py",
            "tests/unit/skills/_lib/test_validate_skill_aspiration.py",
            ".github/workflows/validate-skill-aspiration.yml",
        ),
        push=("main", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "validate-skill-backing-node",
        "validate",
        "validate-skill-backing-node.yml",
        paths=(
            "plugins/onex/skills/**/*.md",
            "plugins/onex/skills/_lib/validate_skill_backing_node.py",
            "plugins/onex/skills/_lib/skill_backing_node_allowlist.yaml",
            "tests/unit/skills/_lib/test_validate_skill_backing_node.py",
            ".github/workflows/validate-skill-backing-node.yml",
        ),
        push=("main", "hotfix/**"),
        dispatch=False,
    ),
    _Folded(
        "verification-evidence-lint",
        "Verification Evidence Lint",
        "verification-evidence-lint.yml",
        paths=(
            "plugins/onex/skills/**/*.md",
            "docs/handoffs/**",
            "docs/receipts/**",
            "docs/**/*receipt*.md",
            ".onex_state/evidence/**",
            "scripts/lint_verification_evidence.py",
            ".github/workflows/verification-evidence-lint.yml",
        ),
        push=("main", "hotfix/**"),
        dispatch=False,
    ),
)

_FOLDED_IDS = [folded.job_id for folded in FOLDED_JOBS]
_CI_YML = ".github/workflows/ci.yml"


def _expected_paths(folded: _Folded) -> list[str]:
    """The original filter, with the gate's own workflow file now read as ci.yml."""
    own = f".github/workflows/{folded.old_file}"
    rewritten = [_CI_YML if path == own else path for path in folded.paths]
    return list(dict.fromkeys(rewritten))


def _changes_step(step_id: str) -> dict[str, Any]:
    steps = _job(_load_workflow(CI_WORKFLOW_PATH), "changes")["steps"]
    return cast(
        "dict[str, Any]",
        next(s for s in steps if isinstance(s, dict) and s.get("id") == step_id),
    )


def _path_filters() -> dict[str, Any]:
    filters = yaml.safe_load(_changes_step("filter")["env"]["PATH_FILTERS"])
    assert isinstance(filters, dict)
    return cast("dict[str, Any]", filters)


def _run_filter(
    tmp_path: Path,
    changed: list[str] | None,
    *,
    event: str = "pull_request",
    ref_name: str = "lane/feature",
) -> dict[str, str]:
    """Run the `changes` job's filter step exactly as ci.yml spells it.

    ``changed=None`` is the diff step's fail-safe: no change set could be
    computed, so every filter that applies to the event matches.
    """
    step = _changes_step("filter")
    assert step.get("shell") == "python", "the filter step runs its body as a file"
    script = tmp_path / "filter.py"
    script.write_text(str(step["run"]), encoding="utf-8")
    changed_file = tmp_path / "changed-files.txt"
    changed_file.write_text("\n".join(changed or []) + "\n", encoding="utf-8")
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH_FILTERS": str(step["env"]["PATH_FILTERS"]),
        "EVENT_NAME": event,
        "REF_NAME": ref_name,
        "CHANGED_FILES_ALL": "true" if changed is None else "false",
        "CHANGED_FILES_PATH": str(changed_file),
        "GITHUB_OUTPUT": str(output),
    }
    result = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    pairs = [
        cast("tuple[str, str]", tuple(line.split("=", 1)))
        for line in output.read_text().splitlines()
        if line
    ]
    return dict(pairs)


def _samples(pattern: str) -> list[str]:
    """Concrete file paths a GitHub `paths:` glob matches, shallow and deep."""
    shallow = pattern.replace("**/", "").replace("**", "x/y.txt").replace("*", "x")
    deep = pattern.replace("**/", "a/b/").replace("**", "a/b/c.txt").replace("*", "x")
    return list(dict.fromkeys([shallow, deep]))


@pytest.mark.parametrize("folded", FOLDED_JOBS, ids=_FOLDED_IDS)
def test_folded_job_lives_in_ci_under_its_own_name(folded: _Folded) -> None:
    """Same check-run name, gated only by its own filter, never advisory."""
    job = _job(_load_workflow(CI_WORKFLOW_PATH), folded.job_id)
    assert job.get("name") == folded.name
    assert job.get("needs") == "changes"
    assert job.get("if") == f"needs.changes.outputs.{folded.job_id} == 'true'"
    assert job.get("continue-on-error") is not True
    assert all(s.get("continue-on-error") is not True for s in job["steps"])


@pytest.mark.parametrize("folded", FOLDED_JOBS, ids=_FOLDED_IDS)
def test_standalone_workflow_is_gone(folded: _Folded) -> None:
    """One home per gate: a second copy would run, and drift, on its own."""
    assert not (REPO_ROOT / ".github" / "workflows" / folded.old_file).exists()


@pytest.mark.parametrize("folded", FOLDED_JOBS, ids=_FOLDED_IDS)
def test_filter_is_the_original_trigger(folded: _Folded) -> None:
    spec = _path_filters()[folded.job_id]
    assert spec["paths"] == _expected_paths(folded)
    assert tuple(spec.get("push", ())) == folded.push
    assert spec.get("workflow_dispatch", False) is folded.dispatch


def test_filters_and_outputs_cover_exactly_the_folded_jobs() -> None:
    changes = _job(_load_workflow(CI_WORKFLOW_PATH), "changes")
    assert set(_path_filters()) == set(_FOLDED_IDS)
    outputs = changes["outputs"]
    assert set(outputs) == set(_FOLDED_IDS)
    for job_id, expression in outputs.items():
        assert expression == f"${{{{ steps.filter.outputs.{job_id} }}}}"


@pytest.mark.parametrize("folded", FOLDED_JOBS, ids=_FOLDED_IDS)
def test_folded_job_runs_when_an_original_path_changes(
    folded: _Folded, tmp_path: Path
) -> None:
    for pattern in _expected_paths(folded):
        for sample in _samples(pattern):
            outputs = _run_filter(tmp_path, [sample])
            assert outputs[folded.job_id] == "true", (pattern, sample)


@pytest.mark.parametrize("folded", FOLDED_JOBS, ids=_FOLDED_IDS)
def test_folded_job_is_skipped_when_no_original_path_changes(
    folded: _Folded, tmp_path: Path
) -> None:
    outputs = _run_filter(tmp_path, ["README.md", "docs/architecture/x.txt"])
    assert outputs[folded.job_id] == "false"


@pytest.mark.parametrize(
    ("job_id", "near_miss"),
    [
        ("check-deterministic-skills", "plugins/onex/skills/x/README.md"),
        ("validate-agent-configs", "plugins/onex/agents/configs/x.json"),
        ("defect-anchor", "docs/evidence/x.txt"),
        ("hook-log-path-lint", "plugins/onex/hooks/lib/x.py"),
        ("check-infra-health-section", "docs/handoffs.txt"),
        ("plugin-compat-gate", "plugins/onex-other/x.json"),
    ],
)
def test_star_does_not_cross_a_directory_or_suffix(
    job_id: str, near_miss: str, tmp_path: Path
) -> None:
    assert _run_filter(tmp_path, [near_miss])[job_id] == "false"


@pytest.mark.parametrize("folded", FOLDED_JOBS, ids=_FOLDED_IDS)
def test_events_the_original_did_not_run_on_skip(
    folded: _Folded, tmp_path: Path
) -> None:
    sample = _samples(_expected_paths(folded)[0])[0]
    for branch in ("main", "dev", "hotfix/x/y"):
        expected = any(
            branch == b or (b.endswith("/**") and branch.startswith(b[:-2]))
            for b in folded.push
        )
        pushed = _run_filter(tmp_path, [sample], event="push", ref_name=branch)
        assert pushed[folded.job_id] == ("true" if expected else "false"), branch
    dispatched = _run_filter(tmp_path, None, event="workflow_dispatch")
    assert dispatched[folded.job_id] == ("true" if folded.dispatch else "false")
    queued = _run_filter(tmp_path, [sample], event="merge_group")
    assert queued[folded.job_id] == "false"


def test_an_uncomputable_change_set_runs_every_pull_request_gate(
    tmp_path: Path,
) -> None:
    """The diff step's fail-safe never reads as `nothing changed`."""
    outputs = _run_filter(tmp_path, None)
    assert outputs == dict.fromkeys(_FOLDED_IDS, "true")


def test_filter_refuses_glob_syntax_it_does_not_implement(tmp_path: Path) -> None:
    step = _changes_step("filter")
    script = tmp_path / "filter.py"
    script.write_text(str(step["run"]), encoding="utf-8")
    (tmp_path / "changed.txt").write_text("a\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script)],
        env={
            **os.environ,
            "PATH_FILTERS": "x:\n  paths: ['docs/?.md']\n",
            "EVENT_NAME": "pull_request",
            "REF_NAME": "b",
            "CHANGED_FILES_ALL": "false",
            "CHANGED_FILES_PATH": str(tmp_path / "changed.txt"),
            "GITHUB_OUTPUT": str(tmp_path / "out"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "docs/?.md" in result.stdout + result.stderr


def test_diff_step_falls_back_to_every_gate_rather_than_none() -> None:
    step = _changes_step("diff")
    run = str(step["run"])
    assert "all=true" in run and "all=false" in run
    assert _changes_step("filter")["env"]["CHANGED_FILES_ALL"] == (
        "${{ steps.diff.outputs.all }}"
    )


@pytest.mark.parametrize("folded", FOLDED_JOBS, ids=_FOLDED_IDS)
def test_ci_summary_passes_a_skip_and_fails_a_red(folded: _Folded) -> None:
    """CI Summary, an existing required context, is what makes the job block."""
    from scripts.ci.ci_summary_gate import (
        EXIT_FAILURE,
        EXIT_SUCCESS,
        GATE_JOBS,
        SOFT_ALLOWLIST,
        evaluate,
    )

    assert folded.name not in SOFT_ALLOWLIST
    gates = [
        {"name": g, "status": "completed", "conclusion": "success", "run_attempt": 1}
        for g in GATE_JOBS
    ]
    for conclusion, expected in (
        ("skipped", EXIT_SUCCESS),
        ("success", EXIT_SUCCESS),
        ("failure", EXIT_FAILURE),
        ("cancelled", EXIT_FAILURE),
    ):
        row = {
            "name": folded.name,
            "status": "completed",
            "conclusion": conclusion,
            "run_attempt": 1,
        }
        code, report = evaluate([*gates, row], run_attempt=1)
        assert code == expected, (conclusion, report)


# The workflow-level `env:` of the three old files that had one, now job-level.
_CARRIED_ENV: dict[str, dict[str, str]] = {
    "plugin-compat-gate": {
        "PYTHON_VERSION": "3.12",
        "UV_CONCURRENT_DOWNLOADS": "1",
        "UV_HTTP_TIMEOUT": "600",
        "UV_SYNC_ATTEMPTS": "5",
        "UV_SYNC_RETRY_DELAY_SECONDS": "10",
        "UV_TORCH_BACKEND": "cpu",
    },
    "validate-skill-aspiration": {
        "PYTHON_VERSION": "3.12",
        "UV_VERSION": "0.6.1",
        "UV_HTTP_TIMEOUT": "600",
    },
    "validate-skill-backing-node": {
        "PYTHON_VERSION": "3.12",
        "UV_VERSION": "0.6.1",
        "UV_HTTP_TIMEOUT": "900",
    },
}


@pytest.mark.parametrize(("job_id", "env"), sorted(_CARRIED_ENV.items()))
def test_old_workflow_env_is_carried_as_job_env(
    job_id: str, env: dict[str, str]
) -> None:
    job = _job(_load_workflow(CI_WORKFLOW_PATH), job_id)
    assert job.get("env") == env
    assert not set(env) & set(job), "an env key parsed as a job key"


def test_marketplace_glob_covers_the_real_directories(tmp_path: Path) -> None:
    """The widened plugin-compat entry still matches every marketplace directory.

    The original filter named the dev marketplace directory literally; that name
    carries a lab lane token the public-repo hygiene gate refuses on an added
    line, so ci.yml spells it `plugins/onex-*-marketplace/**`.
    """
    directories = sorted(
        path.name
        for path in (REPO_ROOT / "plugins").iterdir()
        if path.is_dir()
        and path.name.startswith("onex-")
        and path.name.endswith("-marketplace")
    )
    assert directories, "positive control: no marketplace directory under plugins/"
    for name in directories:
        changed = [f"plugins/{name}/.claude-plugin/marketplace.json"]
        assert _run_filter(tmp_path, changed)["plugin-compat-gate"] == "true", name
