# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""RED/GREEN fixture tests for the Required-Check Skip-Vector Guard (OMN-14854).

Uses synthetic fixture workflow YAML written to a tmp_path per test, never the
live repo's own `.github/workflows/` tree — this keeps the suite stable
regardless of how the live workflows evolve (a live-file test would silently
start passing/failing as unrelated CI changes land elsewhere).

Table mirrors the design spec's section 6 RED/GREEN matrix.
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD_DIR = REPO_ROOT / ".github" / "actions" / "required-check-skip-guard"
if str(_GUARD_DIR) not in sys.path:
    sys.path.insert(0, str(_GUARD_DIR))

from validate_no_required_check_skip_vectors import run  # noqa: E402


def _write(
    tmp_path: Path, workflows: dict[str, str], manifest_gates: list[dict]
) -> tuple[Path, Path]:
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    for name, content in workflows.items():
        (wf_dir / name).write_text(dedent(content), encoding="utf-8")

    manifest_path = tmp_path / "required-checks.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "classification": "toolchain",
                "repo": "fixture",
                "gates": manifest_gates,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, wf_dir


def _manifest_row(name: str, **extra) -> dict:
    row = {
        "name": name,
        "mode": "REQUIRED",
        "producer_kind": "local",
        "skip_semantics": "never",
    }
    row.update(extra)
    return row


def test_paths_filter_on_pull_request_is_red(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                    paths: ['docs/**']
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert findings, "expected RED for pull_request.paths filter"
    assert any(f.vector == "vector-1-paths" for f in findings)


def test_paths_filter_on_pull_request_target_is_red_higher_severity(
    tmp_path: Path,
) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request_target:
                    paths-ignore: ['docs/**']
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-1-pull_request_target-paths" for f in findings)


def test_ungated_actor_if_on_shape_a_job_is_red(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  gate:
                    name: Required Gate
                    if: github.actor != 'some-bot'
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-2-ungated-job-if" for f in findings)


def test_always_if_is_green(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  gate:
                    name: Required Gate
                    if: always()
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_event_name_push_guard_is_green(tmp_path: Path) -> None:
    """Job's `if:` only differentiates a non-PR event (push) — safe negative control."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  push: {}
                  pull_request: {}
                jobs:
                  gate:
                    name: Required Gate
                    if: github.event_name == 'push' || github.event_name == 'pull_request'
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_ungated_caller_if_on_reusable_call_is_red(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "caller.yml": """\
                name: Caller
                on:
                  pull_request: {}
                jobs:
                  callerjob:
                    if: needs.something.result == 'success'
                    uses: ./.github/workflows/reusable.yml
                """,
            "reusable.yml": """\
                name: Reusable
                on:
                  workflow_call: {}
                jobs:
                  inner:
                    name: Reusable Job
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """,
        },
        [_manifest_row("callerjob / Reusable Job")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-3-ungated-caller-if" for f in findings)


def test_real_shape_regression_cr_thread_gate_caller_condition_is_red(
    tmp_path: Path,
) -> None:
    """Reproduction (copied verbatim as a fixture, not read from the live file)
    of the real cr-thread-gate-caller.yml `gate:` job condition. Real-shape
    regression fixture per design spec section 6."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "cr-thread-gate-caller.yml": """\
                name: CR Thread Gate (caller)
                on:
                  pull_request:
                    types: [opened, synchronize, reopened]
                  merge_group:
                    types: [checks_requested]
                jobs:
                  gate:
                    if: >-
                      github.event_name == 'merge_group' ||
                      ((github.event_name != 'issue_comment' || github.event.issue.pull_request != null) &&
                      github.actor != 'dependabot[bot]')
                    uses: ./.github/workflows/cr-thread-gate.yml
                """,
            "cr-thread-gate.yml": """\
                name: CR Thread Gate
                on:
                  workflow_call: {}
                jobs:
                  gate:
                    name: CodeRabbit Thread Check
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """,
        },
        [_manifest_row("gate / CodeRabbit Thread Check")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-3-ungated-caller-if" for f in findings)


def test_workflow_dispatch_only_has_no_pr_trigger_is_red(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  workflow_dispatch: {}
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-4-no-pr-trigger" for f in findings)


def test_cross_repo_producer_local_caller_clean_is_green(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "call-occ.yml": """\
                name: Caller
                on:
                  pull_request: {}
                jobs:
                  occ-preflight:
                    uses: OmniNode-ai/omnibase_core/.github/workflows/occ-preflight.yml@main
                """
        },
        [_manifest_row("occ-preflight / eligibility", producer_kind="cross_repo")],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_cross_repo_producer_local_caller_ungated_if_is_red(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "call-occ.yml": """\
                name: Caller
                on:
                  pull_request: {}
                jobs:
                  occ-preflight:
                    if: github.actor == 'x'
                    uses: OmniNode-ai/omnibase_core/.github/workflows/occ-preflight.yml@main
                """
        },
        [_manifest_row("occ-preflight / eligibility", producer_kind="cross_repo")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-3-ungated-caller-if" for f in findings)


def test_unresolved_local_context_is_red(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  gate:
                    name: Some Other Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Renamed Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-unresolved" for f in findings)


def test_deploy_gate_shape_positive_control_is_green(tmp_path: Path) -> None:
    """Reproduces the real deploy-gate.yml/deploy-gate-reusable.yml shape:
    no paths filter, only step-level `if:` (merge_group short-circuit), never
    a job-level `if:`. This is the canonical good pattern this guard is
    designed around — it must never false-positive."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "deploy-gate.yml": """\
                name: Deploy Gate
                on:
                  pull_request:
                    branches: [main, dev, develop]
                  merge_group: {}
                  workflow_dispatch: {}
                jobs:
                  deploy-gate:
                    name: deploy-gate
                    runs-on: ubuntu-latest
                    steps:
                      - name: Skip on merge_group
                        if: github.event_name == 'merge_group'
                        run: "echo skip"
                      - name: Run deploy gate
                        if: github.event_name != 'merge_group'
                        run: "echo run"
                """
        },
        [_manifest_row("deploy-gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_runs_on_conditional_is_green_negative_control(tmp_path: Path) -> None:
    """Reproduces main-target-guard.yml's `runs-on:` conditional — only the
    *runner* is conditional, the job always executes. Must not be flagged."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "main-target-guard.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  main-target-guard:
                    name: main-target-guard
                    runs-on: >-
                      ${{ github.event.pull_request.head.repo.full_name != github.repository
                          && 'ubuntu-latest' || 'self-hosted' }}
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("main-target-guard")],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_neutral_ok_with_rationale_suppresses_ungated_if(tmp_path: Path) -> None:
    """The sanctioned escape hatch (design spec section 3a): a REQUIRED row
    with `skip_semantics: neutral_ok` AND a non-empty `rationale` suppresses
    the vector-2 finding for an otherwise-ungated job-level `if:`."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  gate:
                    name: Required Gate
                    if: github.actor != 'some-bot'
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [
            _manifest_row(
                "Required Gate",
                skip_semantics="neutral_ok",
                rationale="Ratified exception, see OMN-99999.",
            )
        ],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_neutral_ok_without_rationale_is_still_red(tmp_path: Path) -> None:
    """An un-ratified `neutral_ok` (no rationale cited) does not suppress
    anything — treated as `never`, per the module docstring's mandatory-ticket
    rule."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  gate:
                    name: Required Gate
                    if: github.actor != 'some-bot'
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate", skip_semantics="neutral_ok", rationale="")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-2-ungated-job-if" for f in findings)


def test_neutral_ok_does_not_suppress_paths_filter(tmp_path: Path) -> None:
    """neutral_ok is scoped to conditional `if:` findings only — it must
    never suppress a vector-1 path filter, which is an unconditional wedge,
    not a documented/reviewed exception."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                    paths: ['docs/**']
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [
            _manifest_row(
                "Required Gate",
                skip_semantics="neutral_ok",
                rationale="Ratified exception, see OMN-99999.",
            )
        ],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-1-paths" for f in findings)


def test_neutral_ok_does_not_suppress_missing_trigger(tmp_path: Path) -> None:
    """neutral_ok must never suppress a vector-4 missing-trigger finding —
    that is permanent silence, not a documented risk acceptance."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  workflow_dispatch: {}
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [
            _manifest_row(
                "Required Gate",
                skip_semantics="neutral_ok",
                rationale="Ratified exception, see OMN-99999.",
            )
        ],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-4-no-pr-trigger" for f in findings)


def test_needs_occ_preflight_cascade_is_red(tmp_path: Path) -> None:
    """Vector 5 (OMN-15057). Reproduces the REAL omnimarket deploy-gate.yml
    shape: a same-file 'OCC Preflight Dependency' poller job that `exit 1`s
    when occ-preflight/eligibility fails, and a downstream required-context
    job with `needs: occ-preflight` and NO job-level `if:` override.

    GitHub's *implicit* job-level `if:` is `success()` evaluated over the
    job's `needs:` list -- not an unconditional true. When the poller job
    fails, the downstream job is SKIPPED, and a skipped job satisfies GitHub
    branch protection (skipped counts as passing). This is a live silent-pass
    bypass, structurally identical to vector-2, but keyed off `needs:`
    instead of `if:` -- vectors 1-4 never inspect `needs:` at all, so this
    shape was a blind spot until OMN-15057.

    Live proof: omnimarket#1880 -- 18 required gates (including this guard's
    OWN required check) went `skipped` when occ-preflight failed on first
    run, satisfying branch protection without ever executing.
    """
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "deploy-gate.yml": """\
                name: Deploy Gate
                on:
                  pull_request:
                    branches: [main, dev, develop]
                  merge_group: {}
                jobs:
                  occ-preflight:
                    name: OCC Preflight Dependency
                    runs-on: ubuntu-latest
                    steps:
                      - name: Wait for required OCC preflight
                        run: "exit 1  # simplified: real script polls then exits 1 on failure"
                  deploy-gate:
                    needs: occ-preflight
                    name: deploy-gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo run"}]
                """
        },
        [_manifest_row("deploy-gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert any(f.vector == "vector-5-ungated-needs-cascade" for f in findings), (
        f"expected RED for needs:occ-preflight cascade, got: {findings}"
    )


def test_needs_with_if_always_override_is_green(tmp_path: Path) -> None:
    """The sanctioned fix shape: `if: always()` on the downstream job means
    it always runs regardless of the needs-job's conclusion, so an explicit
    in-job check (not modeled by this guard) is the job's own responsibility.
    Must not false-positive."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  occ-preflight:
                    name: OCC Preflight Dependency
                    runs-on: ubuntu-latest
                    steps: [{run: "exit 1"}]
                  gate:
                    needs: occ-preflight
                    if: always()
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_needs_absent_is_unaffected_by_vector_5(tmp_path: Path) -> None:
    """No `needs:` at all -- vector 5 must never fire (negative control,
    mirrors the OMN-14668-fixed precommit-fail-loud-gate.yml shape)."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_neutral_ok_with_rationale_suppresses_needs_cascade(tmp_path: Path) -> None:
    """The same sanctioned escape hatch (design spec section 3a) applies to
    vector-5: a ratified `neutral_ok` + rationale suppresses it."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request: {}
                jobs:
                  occ-preflight:
                    name: OCC Preflight Dependency
                    runs-on: ubuntu-latest
                    steps: [{run: "exit 1"}]
                  gate:
                    needs: occ-preflight
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [
            _manifest_row(
                "Required Gate",
                skip_semantics="neutral_ok",
                rationale="Ratified exception, see OMN-99999.",
            )
        ],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []


def test_advisory_gate_is_never_checked(tmp_path: Path) -> None:
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  workflow_dispatch: {}
                jobs:
                  gate:
                    name: Not Required Yet
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [
            {
                "name": "Not Required Yet",
                "mode": "ADVISORY",
                "producer_kind": "local",
                "skip_semantics": "never",
            }
        ],
    )
    findings = run(manifest_path, wf_dir)
    assert findings == []
