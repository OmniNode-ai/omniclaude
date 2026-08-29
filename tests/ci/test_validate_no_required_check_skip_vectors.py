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
    of a cross-repo reusable caller's `gate:` job condition (modelled on the
    former cr-thread-gate-caller.yml, deleted in OMN-16933). Real-shape
    regression fixture per design spec section 6."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "reusable-caller.yml": """\
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
                    uses: ./.github/workflows/reusable-gate.yml
                """,
            "reusable-gate.yml": """\
                name: CR Thread Gate
                on:
                  workflow_call: {}
                jobs:
                  gate:
                    name: Thread Check
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """,
        },
        [_manifest_row("gate / Thread Check")],
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


# ---------------------------------------------------------------------------
# Vector 6 — result-triage fail-open (OMN-15304)
#
# The RED/GREEN pair below is not synthetic: both `run:` blocks are the real
# omnimarket `hostile-review-gate` script, extracted byte-for-byte from
# `.github/workflows/hostile-reviewer.yml` at 848d3333^ (pre-#1926, the shape
# that went green over a CANCELLED reviewer on omnimarket#1920 run
# 30298837182) and at 848d3333 (post-#1926, the OMN-15296 fix). The pre shape
# PASSES vectors 1-5 — it has `if: always()` — which is exactly why vector 6
# has to exist.
# ---------------------------------------------------------------------------

_HOSTILE_GATE_RUN_PRE_1926 = """\
                        echo "=== Hostile Review Gate ==="
                        RESULT="${{ needs.hostile-review.result }}"
                        echo "hostile-review: $RESULT"

                        # OMN-15057: the occ-preflight cross-check that used to live here was
                        # dropped along with `needs: occ-preflight` -- OCC eligibility is
                        # already independently enforced as its own required status check
                        # (`occ-preflight / eligibility`), so re-checking it here was
                        # redundant AND was the exact skip-then-vacuous-green vector: when
                        # the same-file poller job failed, this whole job (and its required
                        # context) went `skipped`, which GitHub branch protection treats as
                        # passing. See OMN-14668 for the precedent fix.
                        if [ "$RESULT" = "failure" ]; then
                          echo "::error::Hostile reviewer found CRITICAL/ERROR findings — resolve before merge."
                          exit 1
                        fi
                        echo "Hostile Review Gate PASSED"
"""

_HOSTILE_GATE_RUN_POST_1926 = """\
                        echo "=== Hostile Review Gate ==="
                        RESULT="${{ needs.hostile-review.result }}"
                        echo "hostile-review: $RESULT"

                        # OMN-15057: the occ-preflight cross-check that used to live here was
                        # dropped along with `needs: occ-preflight` -- OCC eligibility is
                        # already independently enforced as its own required status check
                        # (`occ-preflight / eligibility`), so re-checking it here was
                        # redundant AND was the exact skip-then-vacuous-green vector: when
                        # the same-file poller job failed, this whole job (and its required
                        # context) went `skipped`, which GitHub branch protection treats as
                        # passing. See OMN-14668 for the precedent fix.
                        # OMN-15296: `needs.<job>.result` is one of success/failure/cancelled/
                        # skipped. Only `success` is a real reviewer verdict. This block used to
                        # test `= "failure"` alone, so `cancelled` and `skipped` fell straight
                        # through to the PASSED line and turned this required context green with
                        # no adversarial verdict in existence -- observed live on #1920 (run
                        # 30298837182: reviewer cancelled 04:13:14Z, gate SUCCESS 04:13:21Z, 7s
                        # later). Everything that is not `success` now fails closed, including a
                        # result value GitHub may add in future.
                        case "$RESULT" in
                          success)
                            echo "Hostile Review Gate PASSED"
                            ;;
                          failure)
                            echo "::error::Hostile reviewer found CRITICAL/ERROR findings — resolve before merge. If instead the job died before emitting a verdict (runner or reviewer-endpoint loss), this signal is today indistinguishable from real findings — that split is OMN-14046; re-run the reviewer rather than merging on it."
                            exit 1
                            ;;
                          cancelled)
                            echo "::error::Hostile reviewer run was cancelled, so it produced no adversarial verdict. A cancelled review is not evidence that the review passed — re-run it before merge (OMN-15296)."
                            exit 1
                            ;;
                          skipped)
                            echo "::error::Hostile reviewer job was skipped, so it produced no adversarial verdict. Failing closed: a skipped required check must never read as review evidence (OMN-15296)."
                            exit 1
                            ;;
                          *)
                            echo "::error::Unrecognised hostile-review result '$RESULT'. Failing closed by default-deny — a result this gate cannot interpret must never open the merge path (OMN-15296)."
                            exit 1
                            ;;
                        esac
"""


def _hostile_gate_workflow(run_script: str) -> str:
    body = "\n".join(
        "          " + line if line.strip() else ""
        for line in run_script.rstrip("\n").split("\n")
    )
    return (
        "name: Hostile Reviewer\n"
        "on:\n"
        "  pull_request:\n"
        "jobs:\n"
        "  hostile-review:\n"
        "    name: Hostile Reviewer (adversarial gate)\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo review\n"
        "  hostile-review-gate:\n"
        "    name: Hostile Review Gate\n"
        "    needs: [hostile-review]\n"
        "    if: always()\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Evaluate gate\n"
        "        run: |\n" + body + "\n"
    )


def test_result_triage_pre_1926_hostile_gate_is_red(tmp_path: Path) -> None:
    """RED: the real pre-#1926 gate. Blocks on `failure` only; `cancelled` and
    `skipped` fall through to `Hostile Review Gate PASSED`."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {"hostile-reviewer.yml": _hostile_gate_workflow(_HOSTILE_GATE_RUN_PRE_1926)},
        [_manifest_row("Hostile Review Gate")],
    )
    findings = run(manifest_path, wf_dir)
    vectors = [f.vector for f in findings]
    assert "vector-6-result-triage-fail-open" in vectors, findings
    msg = next(
        f.message for f in findings if f.vector == "vector-6-result-triage-fail-open"
    )
    assert "cancelled" in msg and "skipped" in msg, msg
    # The point of the ticket: vectors 1-5 are all silent on this shape.
    assert [v for v in vectors if not v.startswith("vector-6")] == [], vectors


def test_result_triage_post_1926_hostile_gate_is_green(tmp_path: Path) -> None:
    """GREEN: the real post-#1926 gate — four-way `case` with a default-deny
    `*` branch. No findings of any vector."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {"hostile-reviewer.yml": _hostile_gate_workflow(_HOSTILE_GATE_RUN_POST_1926)},
        [_manifest_row("Hostile Review Gate")],
    )
    assert run(manifest_path, wf_dir) == []


def test_result_triage_if_not_success_form_is_green(tmp_path: Path) -> None:
    """GREEN: the terser hardened form — `!= success` guarding a non-zero exit."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  upstream:
                    name: Upstream
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [upstream]
                    if: always()
                    runs-on: ubuntu-latest
                    steps:
                      - run: |
                          RESULT="${{ needs.upstream.result }}"
                          if [ "$RESULT" != "success" ]; then
                            echo "::error::upstream did not succeed: $RESULT"
                            exit 1
                          fi
                """
        },
        [_manifest_row("Required Gate")],
    )
    assert run(manifest_path, wf_dir) == []


def test_result_triage_case_without_catch_all_is_red(tmp_path: Path) -> None:
    """RED: a `case` covering all four values today but with no `*` default-deny
    branch — a fifth result value GitHub adds later would open the merge path."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  upstream:
                    name: Upstream
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [upstream]
                    if: always()
                    runs-on: ubuntu-latest
                    steps:
                      - run: |
                          RESULT="${{ needs.upstream.result }}"
                          case "$RESULT" in
                            success) echo ok ;;
                            failure) exit 1 ;;
                            cancelled) exit 1 ;;
                            skipped) exit 1 ;;
                          esac
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert [f.vector for f in findings] == ["vector-6-result-triage-unverifiable"], (
        findings
    )


def test_result_triage_echo_only_consumer_is_red(tmp_path: Path) -> None:
    """RED (fail-closed on unparseable, ticket scope item 2): a gate that reads
    the upstream result but only echoes it never gates on anything."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  upstream:
                    name: Upstream
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [upstream]
                    if: always()
                    runs-on: ubuntu-latest
                    steps:
                      - run: echo "upstream=${{ needs.upstream.result }}"
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert [f.vector for f in findings] == ["vector-6-result-triage-unverifiable"], (
        findings
    )


def test_result_triage_waiver_requires_cited_ticket(tmp_path: Path) -> None:
    """`result_triage: waived` suppresses the finding only with a cited ticket;
    a free-text rationale waives nothing."""
    workflows = {
        "hostile-reviewer.yml": _hostile_gate_workflow(_HOSTILE_GATE_RUN_PRE_1926)
    }

    unratified_manifest, wf_dir = _write(
        tmp_path / "unratified",
        workflows,
        [
            _manifest_row(
                "Hostile Review Gate",
                result_triage="waived",
                rationale="we looked at it and it is fine",
            )
        ],
    )
    assert [f.vector for f in run(unratified_manifest, wf_dir)] == [
        "vector-6-result-triage-fail-open"
    ]

    ratified_manifest, wf_dir2 = _write(
        tmp_path / "ratified",
        workflows,
        [
            _manifest_row(
                "Hostile Review Gate",
                result_triage="waived",
                rationale="Tracked in OMN-15304; remediation lands separately.",
            )
        ],
    )
    assert run(ratified_manifest, wf_dir2) == []


def test_result_triage_absent_consumer_is_green(tmp_path: Path) -> None:
    """A job that never reads a result token is out of vector 6's scope."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    assert run(manifest_path, wf_dir) == []


def test_sibling_dependency_observation_is_emitted(tmp_path: Path) -> None:
    """OMN-15304 §4: the fail-open aggregator's upstream is ITSELF a required
    context — defence-in-depth by accident. Record it, do not fail on it."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {"hostile-reviewer.yml": _hostile_gate_workflow(_HOSTILE_GATE_RUN_PRE_1926)},
        [
            _manifest_row("Hostile Review Gate"),
            _manifest_row("Hostile Reviewer (adversarial gate)"),
        ],
    )
    observations: list = []
    run(manifest_path, wf_dir, observations=observations)
    rendered = [o.render() for o in observations]
    assert any(
        "Hostile Review Gate" in r and "Hostile Reviewer (adversarial gate)" in r
        for r in rendered
    ), rendered


def test_result_triage_skipped_treated_as_pass_is_red(tmp_path: Path) -> None:
    """RED: the conjunction weakening `[ != success ] && [ != skipped ]`.

    It reads as "fail unless success" locally, but lets `skipped` through — and
    a skipped upstream is the absence of a verdict exactly like a cancelled one.
    This is the live shape of omniclaude's own `quality-gate`/`tests-gate`
    aggregators, so it must not certify as hardened.
    """
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  upstream:
                    name: Upstream
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [upstream]
                    if: always()
                    runs-on: ubuntu-latest
                    steps:
                      - run: |
                          RESULT="${{ needs.upstream.result }}"
                          if [ "$RESULT" != "success" ] && [ "$RESULT" != "skipped" ]; then
                            exit 1
                          fi
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert [f.vector for f in findings] == ["vector-6-result-triage-fail-open"], (
        findings
    )
    assert "skipped" in findings[0].message


def test_result_triage_ignores_job_level_if(tmp_path: Path) -> None:
    """A result read in the JOB-level `if:` decides whether the job RUNS —
    vectors 2/3/5 own that shape. Vector 6 must not double-report it."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  upstream:
                    name: Upstream
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [upstream]
                    if: needs.upstream.result == 'success'
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                """
        },
        [_manifest_row("Required Gate")],
    )
    vectors = [f.vector for f in run(manifest_path, wf_dir)]
    assert not any(v.startswith("vector-6") for v in vectors), vectors


def test_result_triage_positive_success_test_with_else_exit_is_green(
    tmp_path: Path,
) -> None:
    """GREEN: the positive form `if = success ... else exit 1` is fail-closed on
    every non-success value INCLUDING one GitHub adds later. Live shape:
    omnibase_spi `tests-gate` at origin/dev."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  test-parallel:
                    name: Upstream
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [test-parallel]
                    if: always()
                    runs-on: ubuntu-latest
                    steps:
                      - run: |
                          RESULT="${{ needs.test-parallel.result }}"
                          if [ "${RESULT}" = "success" ]; then
                            echo "PASSED"
                          else
                            echo "FAILED: ${RESULT}"
                            exit 1
                          fi
                """
        },
        [_manifest_row("Required Gate")],
    )
    assert run(manifest_path, wf_dir) == []


def test_result_triage_success_or_skipped_pass_condition_is_red(
    tmp_path: Path,
) -> None:
    """RED: `== success || == skipped` admits a verdict-less upstream. Live
    shape: omnibase_compat / omnibase_core `tests-gate` at origin/dev."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  test-parallel:
                    name: Upstream
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [test-parallel]
                    if: always()
                    runs-on: ubuntu-latest
                    steps:
                      - run: |
                          result="${{ needs.test-parallel.result }}"
                          if [[ "$result" == "success" || "$result" == "skipped" ]]; then
                            echo "PASSED ($result)"
                            exit 0
                          else
                            echo "FAILED ($result)"
                            exit 1
                          fi
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert [f.vector for f in findings] == ["vector-6-result-triage-fail-open"], (
        findings
    )
    assert "skipped" in findings[0].message


def test_result_triage_multiline_conjunction_of_success_tests_is_green(
    tmp_path: Path,
) -> None:
    """GREEN: many `== success` clauses conjoined across backslash-continued
    lines, with `else ... exit 1`. Live shape: omnibase_core `quality-gate`."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  lint:
                    name: Lint
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  pyright:
                    name: Pyright
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [lint, pyright]
                    if: always()
                    runs-on: ubuntu-latest
                    steps:
                      - run: |
                          lint="${{ needs.lint.result }}"
                          pyright="${{ needs.pyright.result }}"
                          if [[ "$lint" == "success" ]] && \\
                             [[ "$pyright" == "success" ]]; then
                            echo "PASSED"
                            exit 0
                          else
                            echo "FAILED"
                            exit 1
                          fi
                """
        },
        [_manifest_row("Required Gate")],
    )
    assert run(manifest_path, wf_dir) == []


def _aggregator_loop_workflow(triage_condition: str) -> str:
    """The dominant real aggregator idiom in the fleet: the upstream results are
    packed into a `for` list as `name=<result>` strings and unpacked with
    `${check##*=}`, so the result reaches the triage through two levels of
    indirection."""
    return f"""\
name: X
on:
  pull_request:
jobs:
  alpha:
    name: Alpha
    runs-on: ubuntu-latest
    steps: [{{run: "echo hi"}}]
  beta:
    name: Beta
    runs-on: ubuntu-latest
    steps: [{{run: "echo hi"}}]
  gate:
    name: Required Gate
    needs: [alpha, beta]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - run: |
          FAILED=false
          for check in \\
            "alpha=${{{{ needs.alpha.result }}}}" \\
            "beta=${{{{ needs.beta.result }}}}"
          do
            NAME="${{check%%=*}}"
            RESULT="${{check##*=}}"
            if {triage_condition}; then
              echo "::error::$NAME failed (result: $RESULT)"
              FAILED=true
            else
              echo "$NAME: $RESULT"
            fi
          done

          if [ "$FAILED" = "true" ]; then
            exit 1
          fi
          echo "Required Gate PASSED"
"""


def test_aggregator_loop_skipped_as_pass_is_red(tmp_path: Path) -> None:
    """RED: live shape of omniclaude `quality-gate`/`tests-gate`/
    `omni-standards-gate` and omnimarket `omni-standards-gate` at origin/dev —
    `skipped` reaches the pass path through the loop."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": _aggregator_loop_workflow(
                '[ "$RESULT" != "success" ] && [ "$RESULT" != "skipped" ]'
            )
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert [f.vector for f in findings] == ["vector-6-result-triage-fail-open"], (
        findings
    )
    assert "skipped" in findings[0].message


def test_aggregator_loop_strict_success_is_green(tmp_path: Path) -> None:
    """GREEN: the same loop with a strict `!= success` triage. Live shape of
    omnidash `omni-standards-gate` at origin/dev — it must NOT be reported just
    because the result travels through a loop variable."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {"gate.yml": _aggregator_loop_workflow('[ "$RESULT" != "success" ]')},
        [_manifest_row("Required Gate")],
    )
    assert run(manifest_path, wf_dir) == []


def test_steps_outcome_read_without_continue_on_error_is_green(tmp_path: Path) -> None:
    """A `steps.<id>.outcome` read is only a fail-open surface when the step can
    fail without failing the job. Without `continue-on-error: true` the job has
    already failed by the time the reader runs. Live shape: omnibase_core
    `docs-validation`."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps:
                      - id: validate
                        run: ./validate.sh
                      - if: always()
                        run: |
                          if [ "${{ steps.validate.outcome }}" = "success" ]; then
                            echo "ok"
                          else
                            echo "see logs"
                          fi
                """
        },
        [_manifest_row("Required Gate")],
    )
    assert run(manifest_path, wf_dir) == []


def test_steps_outcome_read_with_continue_on_error_is_red(tmp_path: Path) -> None:
    """RED: with `continue-on-error: true` the step's failure does NOT fail the
    job, so a summary step that only echoes the outcome is a real fail-open."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  gate:
                    name: Required Gate
                    runs-on: ubuntu-latest
                    steps:
                      - id: validate
                        continue-on-error: true
                        run: ./validate.sh
                      - if: always()
                        run: |
                          if [ "${{ steps.validate.outcome }}" = "success" ]; then
                            echo "ok"
                          else
                            echo "see logs"
                          fi
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert [f.vector for f in findings] == ["vector-6-result-triage-unverifiable"], (
        findings
    )


# ---------------------------------------------------------------------------
# Vector 6, per-UPSTREAM analysis (OMN-15304 remediation round 1)
#
# The first cut of this analyzer collapsed every `needs.<job>.result` to one
# sentinel and returned on the FIRST hardened shape it found anywhere in the
# job. A hardened guard on upstream A therefore certified the whole job while
# upstream B's triage was fail-open. That masked omniclaude's OWN
# `Hostile Review Gate` — a live REQUIRED context whose `occ-preflight` guard
# hardened while `hostile-review` blocked only on `failure`: the pre-#1926
# omnimarket shape verbatim, i.e. the exact incident this vector exists to
# catch, on a repo with no sibling `Hostile Reviewer` required context to act
# as the accidental backstop.
#
# The RED script below is the omniclaude `hostile-review-gate` `run:` block as
# it stood before this remediation, extracted byte-for-byte.
# ---------------------------------------------------------------------------

_MASKED_GATE_RUN_PRE_FIX = """\
                        echo "=== Hostile Review Gate ==="
                        PREFLIGHT="${{ needs.occ-preflight.result }}"
                        RESULT="${{ needs.hostile-review.result }}"
                        echo "occ-preflight: $PREFLIGHT"
                        echo "hostile-review: $RESULT"

                        if [ "$PREFLIGHT" != "success" ]; then
                          echo "::error::OCC preflight failed or did not complete (result: $PREFLIGHT)."
                          exit 1
                        fi
                        if [ "$RESULT" = "failure" ]; then
                          echo "::error::Hostile reviewer found CRITICAL/ERROR findings — resolve before merge."
                          exit 1
                        fi
                        echo "Hostile Review Gate PASSED"
"""

_MASKED_GATE_RUN_POST_FIX = """\
                        echo "=== Hostile Review Gate ==="
                        PREFLIGHT="${{ needs.occ-preflight.result }}"
                        RESULT="${{ needs.hostile-review.result }}"
                        echo "occ-preflight: $PREFLIGHT"
                        echo "hostile-review: $RESULT"

                        if [ "$PREFLIGHT" != "success" ]; then
                          echo "::error::OCC preflight failed or did not complete (result: $PREFLIGHT)."
                          exit 1
                        fi
                        case "$RESULT" in
                          success)
                            ;;
                          failure)
                            echo "::error::Hostile reviewer found CRITICAL/ERROR findings — resolve before merge."
                            exit 1
                            ;;
                          cancelled|skipped)
                            echo "::error::Hostile reviewer produced no verdict (result: $RESULT) — the absence of a verdict is not a passing one."
                            exit 1
                            ;;
                          *)
                            echo "::error::Unrecognised hostile-review result '$RESULT' — failing closed."
                            exit 1
                            ;;
                        esac
                        echo "Hostile Review Gate PASSED"
"""


def _two_upstream_gate_workflow(run_script: str) -> str:
    body = "\n".join(
        "          " + line if line.strip() else ""
        for line in run_script.rstrip("\n").split("\n")
    )
    return (
        "name: Hostile Reviewer\n"
        "on:\n"
        "  pull_request:\n"
        "jobs:\n"
        "  occ-preflight:\n"
        "    name: OCC Preflight\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo preflight\n"
        "  hostile-review:\n"
        "    name: Hostile Reviewer (adversarial gate)\n"
        "    needs: [occ-preflight]\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo review\n"
        "  hostile-review-gate:\n"
        "    name: Hostile Review Gate\n"
        "    needs: [occ-preflight, hostile-review]\n"
        "    if: always()\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Evaluate gate\n"
        "        run: |\n" + body + "\n"
    )


def test_hardened_sibling_upstream_does_not_mask_a_fail_open_upstream(
    tmp_path: Path,
) -> None:
    """RED: two upstreams, one hardened (`occ-preflight`), one fail-open
    (`hostile-review` blocks only on `failure`). Per-JOB analysis called this
    HARDENED and reported nothing; per-UPSTREAM analysis must report it and
    must NAME the fail-open upstream, not the hardened one."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {"hostile-reviewer.yml": _two_upstream_gate_workflow(_MASKED_GATE_RUN_PRE_FIX)},
        [_manifest_row("Hostile Review Gate")],
    )
    findings = run(manifest_path, wf_dir)
    vectors = [f.vector for f in findings]
    assert "vector-6-result-triage-fail-open" in vectors, findings
    msg = next(
        f.message for f in findings if f.vector == "vector-6-result-triage-fail-open"
    )
    # The finding must attribute the fail-open to hostile-review, and must NOT
    # claim occ-preflight (which is genuinely hardened) is the problem.
    assert "needs.hostile-review.result" in msg, msg
    assert "for `needs.occ-preflight.result`" not in msg, msg
    assert "cancelled" in msg and "skipped" in msg, msg
    # Same claim as the omnimarket fixture: vectors 1-5 are silent on this shape.
    assert [v for v in vectors if not v.startswith("vector-6")] == [], vectors


def test_all_upstreams_hardened_is_green(tmp_path: Path) -> None:
    """GREEN: the same two-upstream job once BOTH upstreams fail closed. Guards
    the other direction — per-upstream analysis must not fire on a job that is
    genuinely hardened on every result it reads."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "hostile-reviewer.yml": _two_upstream_gate_workflow(
                _MASKED_GATE_RUN_POST_FIX
            )
        },
        [_manifest_row("Hostile Review Gate")],
    )
    assert run(manifest_path, wf_dir) == []


def test_masked_upstream_still_emits_the_sibling_dependency_observation(
    tmp_path: Path,
) -> None:
    """The masking also suppressed the ticket's scope-item-4 observation, which
    early-returns on TRIAGE_HARDENED. With per-upstream analysis the
    observation fires again when the fail-open upstream is itself required."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {"hostile-reviewer.yml": _two_upstream_gate_workflow(_MASKED_GATE_RUN_PRE_FIX)},
        [
            _manifest_row("Hostile Review Gate"),
            _manifest_row("Hostile Reviewer (adversarial gate)"),
        ],
    )
    observations: list = []
    run(manifest_path, wf_dir, observations=observations)
    texts = [o.message for o in observations]
    assert any(
        "hostile-review -> 'Hostile Reviewer (adversarial gate)'" in t for t in texts
    ), texts


def test_continue_on_error_triage_step_cannot_harden(tmp_path: Path) -> None:
    """RED: a triage step running `exit 1` under `continue-on-error: true` does
    not fail the job, so it hardens nothing. The analyzer modelled
    continue-on-error for the CONSUMED side only; the asymmetry certified this
    shape TRIAGE_HARDENED."""
    manifest_path, wf_dir = _write(
        tmp_path,
        {
            "gate.yml": """\
                name: X
                on:
                  pull_request:
                jobs:
                  upstream:
                    name: Upstream
                    runs-on: ubuntu-latest
                    steps: [{run: "echo hi"}]
                  gate:
                    name: Required Gate
                    needs: [upstream]
                    if: always()
                    runs-on: ubuntu-latest
                    steps:
                      - continue-on-error: true
                        run: |
                          RESULT="${{ needs.upstream.result }}"
                          if [ "$RESULT" != "success" ]; then
                            echo "::error::upstream did not succeed: $RESULT"
                            exit 1
                          fi
                """
        },
        [_manifest_row("Required Gate")],
    )
    findings = run(manifest_path, wf_dir)
    assert [f.vector for f in findings] == ["vector-6-result-triage-unverifiable"], (
        findings
    )
