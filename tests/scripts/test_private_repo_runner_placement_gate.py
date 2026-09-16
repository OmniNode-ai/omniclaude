# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18205: private repositories never run CI on GitHub-hosted runners.

The assertions below are about the two ways a placement gate goes quietly
wrong. It can count a job as hosted because the FILE mentions a hosted label
in prose, or it can count a job as safe because its `runs-on` is an expression
it declined to resolve. Both read as a clean bill of health. So every test
here goes through the real parser against a real workflow tree, and the suite
opens with a positive control: a tree that MUST fail. A gate suite with no
failing fixture proves only that the gate is silent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "private_repo_runner_placement_gate.py"

FLEET = '["self-hosted","omnibase-ci"]'
HOSTED = '["ubuntu-latest"]'

SEAM_EXPRESSION = (
    "${{\n"
    "  (github.event.pull_request.head.repo.full_name != github.repository)\n"
    "  && fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]')\n"
    "  || fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
    '\'["self-hosted","omnibase-ci"]\')\n'
    "}}"
)


def _module():
    if "placement_gate" in sys.modules:
        return sys.modules["placement_gate"]
    spec = importlib.util.spec_from_file_location("placement_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves its annotations through
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules["placement_gate"] = module
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path, name: str, body: str) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(body, encoding="utf-8")
    return tmp_path


def _run(module, root: Path, variables: dict[str, str], tmp_path: Path) -> int:
    vars_file = tmp_path / "vars.json"
    vars_file.write_text(json.dumps(variables), encoding="utf-8")
    return module.main(
        [
            "--repo-root",
            str(root),
            "--repo",
            "OmniNode-ai/fixture",
            "--assume-visibility",
            "private",
            "--variables-json",
            str(vars_file),
        ]
    )


def _seam_job(expression: str = SEAM_EXPRESSION) -> str:
    """One pull-request job whose runs-on is `expression`, indented for YAML."""
    return (
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: >-\n      "
        + expression.replace("\n", "\n      ")
        + "\n    steps:\n      - run: true\n"
    )


def test_positive_control_a_hosted_pin_in_a_private_repo_fails(
    tmp_path: Path,
) -> None:
    """The control. Without it every other assertion here could be vacuous."""
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n",
    )
    assert _run(module, root, {}, tmp_path) == 1


def test_a_fleet_pin_in_a_private_repo_passes(tmp_path: Path) -> None:
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: [self-hosted, omnibase-ci]\n"
        "    steps:\n      - run: true\n",
    )
    assert _run(module, root, {}, tmp_path) == 0


def test_a_public_repo_is_not_judged_at_all(tmp_path: Path) -> None:
    """Hosted is the CORRECT placement in a public repo; its minutes are free."""
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n",
    )
    assert (
        module.main(
            [
                "--repo-root",
                str(root),
                "--repo",
                "OmniNode-ai/fixture",
                "--assume-visibility",
                "public",
            ]
        )
        == 0
    )


def test_an_expression_is_resolved_against_live_values_not_skipped(
    tmp_path: Path,
) -> None:
    """A variable-driven job is not 'unknown'; it resolves to whatever is set.

    Same workflow, two variable states, opposite verdicts. That pair is the
    whole point: a gate that skipped expressions would return 0 for both and
    the second case is a private repository on hosted runners.
    """
    module = _module()
    body = (
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: >-\n      "
        + SEAM_EXPRESSION.replace("\n", "\n      ")
        + "\n    steps:\n      - run: true\n"
    )
    root = _tree(tmp_path, "ci.yml", body)

    both_fleet = {
        "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
        "OMNI_PUBLIC_PR_RUNS_ON_JSON": FLEET,
    }
    assert _run(module, root, both_fleet, tmp_path) == 0

    trusted_hosted = {
        "OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED,
        "OMNI_PUBLIC_PR_RUNS_ON_JSON": FLEET,
    }
    assert _run(module, root, trusted_hosted, tmp_path) == 1


def test_the_fork_branch_may_be_hosted_when_the_trusted_branch_is_not(
    tmp_path: Path,
) -> None:
    """Fork isolation is a TRUST constraint and outranks the cost ruling.

    The canonical selector sends a pull request opened from a fork to the
    public runner class and everything else to the trusted seam. For a private
    repository both halves of that are required, not in tension: the
    2026-09-14 ruling says a private repository's CI does not run on hosted
    runners, and fork isolation says untrusted code never reaches a fleet
    runner that bind-mounts lab credentials. The routing node's own contract
    settles the order -- only a CAPACITY reason may be reversed for a
    repository that may not run hosted, never a trust reason such as fork
    isolation -- so the hosted fork branch is the REQUIRED placement here and
    reporting it as a violation would be asking for the prohibited one.

    The property that survives: the branch a same-repo pull request actually
    takes must still be the fleet, and that is asserted by the next two tests.
    """
    module = _module()
    root = _tree(tmp_path, "ci.yml", _seam_job())
    variables = {
        "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
        "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
    }
    assert _run(module, root, variables, tmp_path) == 0


def test_an_inverted_guard_that_defaults_to_hosted_is_still_reported(
    tmp_path: Path,
) -> None:
    """The OMN-16683 inversion, which is what the carve-out must not readmit.

    Here the guard selects the TRUSTED class and the unguarded default is the
    public one, so an ordinary same-repo pull request lands on a hosted runner
    while the file still reads as fork-isolated. The rule is scoped to the
    branch a fork takes; a hosted DEFAULT is a finding however the expression
    is spelled.
    """
    module = _module()
    inverted = (
        "${{\n"
        "  (github.event.pull_request.head.repo.full_name == github.repository)\n"
        "  && fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
        '\'["self-hosted","omnibase-ci"]\')\n'
        "  || fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]')\n"
        "}}"
    )
    root = _tree(tmp_path, "ci.yml", _seam_job(inverted))
    variables = {
        "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
        "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
    }
    assert _run(module, root, variables, tmp_path) == 1


def test_a_fork_guarded_branch_that_is_the_only_branch_is_reported(
    tmp_path: Path,
) -> None:
    """A carve-out with nothing to fall back to is just a hosted pin.

    The exemption exists because a NON-fork branch carries the ordinary
    placement. With no such branch every event resolves hosted, which is the
    thing the ruling forbids, so the fork guard excuses nothing.
    """
    module = _module()
    only_fork = (
        "${{\n"
        "  (github.event.pull_request.head.repo.full_name != github.repository)\n"
        "  && fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]')\n"
        "}}"
    )
    root = _tree(tmp_path, "ci.yml", _seam_job(only_fork))
    variables = {
        "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
        "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
    }
    assert _run(module, root, variables, tmp_path) == 1


def test_a_guard_that_is_not_a_fork_test_excuses_nothing(
    tmp_path: Path,
) -> None:
    """Fail closed on any guard the rule does not recognise as a fork test.

    Only two spellings of `is a fork` are recognised. Anything else guarding a
    hosted branch -- an event name, a label, a schedule -- is judged as an
    ordinary hosted placement, so a new selector shape cannot quietly inherit
    the exemption.
    """
    module = _module()
    not_a_fork_test = (
        "${{\n"
        "  (github.event_name == 'schedule')\n"
        "  && fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]')\n"
        "  || fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
        '\'["self-hosted","omnibase-ci"]\')\n'
        "}}"
    )
    root = _tree(tmp_path, "ci.yml", _seam_job(not_a_fork_test))
    variables = {
        "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
        "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
    }
    assert _run(module, root, variables, tmp_path) == 1


def test_an_annotated_job_passes_and_an_unannotated_twin_does_not(
    tmp_path: Path,
) -> None:
    """A named reason is the escape hatch; a bare pin is the failure."""
    module = _module()
    annotated = _tree(
        tmp_path / "a",
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  # private-repo-hosted-ok: needs a macOS image the fleet has none of "
        "(OMN-12345)\n"
        "  build:\n    runs-on: macos-15\n    steps:\n      - run: true\n",
    )
    assert _run(module, annotated, {}, tmp_path) == 0

    bare = _tree(
        tmp_path / "b",
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: macos-15\n    steps:\n      - run: true\n",
    )
    assert _run(module, bare, {}, tmp_path) == 1


def test_an_annotation_without_a_ticket_does_not_excuse_anything(
    tmp_path: Path,
) -> None:
    """Free text is a justification, not a commitment to move the job.

    The verdict is 2 rather than 1 as of OMN-18431, and the distinction is the
    point: an incomplete marker is not judged as an ordinary bare pin, it is
    REFUSED with its own message naming what is missing. Both fail the run;
    only one of them tells the author that the exemption they wrote was read
    and rejected rather than never seen.
    """
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  # private-repo-hosted-ok: it has always been like this\n"
        "  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n",
    )
    assert _run(module, root, {}, tmp_path) == 2


def test_an_unset_variable_with_no_fallback_fails_closed(tmp_path: Path) -> None:
    """Undecidable is exit 2, never a pass. A gate that cannot decide has not run."""
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: ${{ fromJSON(vars.OMNI_NOT_SET_ANYWHERE) }}\n"
        "    steps:\n      - run: true\n",
    )
    assert _run(module, root, {}, tmp_path) == 2


def test_a_repo_with_no_workflows_fails_closed(tmp_path: Path) -> None:
    """Absence of workflows is not proof of correct placement."""
    module = _module()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert _run(module, tmp_path, {}, tmp_path) == 2


@pytest.mark.parametrize(
    "label",
    ["ubuntu-latest", "ubuntu-24.04", "macos-15", "macos-latest", "windows-2025"],
)
def test_every_hosted_image_family_is_matched_by_stem(label: str) -> None:
    """Prefix-matched on purpose: an enumeration goes stale into a false green."""
    module = _module()
    assert module.HOSTED_LABEL.match(label)


@pytest.mark.parametrize("label", ["self-hosted", "omnibase-ci", "omni-cloud-ci"])
def test_fleet_labels_are_not_matched(label: str) -> None:
    module = _module()
    assert not module.HOSTED_LABEL.match(label)


@pytest.mark.parametrize(
    "guard",
    [
        "github.event.pull_request.head.repo.full_name != github.repository",
        "github.event.pull_request.head.repo.fork == true",
        "github.event.pull_request.head.repo.fork",
    ],
)
def test_the_recognised_fork_tests(guard: str) -> None:
    module = _module()
    assert module.FORK_TEST.search(guard)


@pytest.mark.parametrize(
    "guard",
    [
        # The OMN-16683 inversion: this guards the TRUSTED arm.
        "github.event.pull_request.head.repo.full_name == github.repository",
        "github.event.pull_request.head.repo.fork == false",
        "github.event.pull_request.head.repo.fork != true",
        "github.event_name == 'schedule'",
        "contains(github.event.pull_request.labels.*.name, 'fork')",
    ],
)
def test_an_inverted_or_unrelated_guard_is_not_a_fork_test(guard: str) -> None:
    """The exemption must not be reachable by a guard that means the opposite."""
    module = _module()
    assert not module.FORK_TEST.search(guard)


def test_a_wrapped_annotation_fails_closed_instead_of_being_ignored(
    tmp_path: Path,
) -> None:
    """A wrapped annotation is a refusal that names itself, not a silent miss.

    The reason and its ticket have to share a line. When an author wraps the
    comment the ticket lands where the pattern cannot reach it, and without
    this the job is simply reported as a bare pin -- the right verdict for a
    reason the author cannot see from the message.
    """
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n"
        "    # private-repo-hosted-ok: needs a tool the fleet image does not\n"
        "    # carry (OMN-17477)\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: true\n",
    )
    assert _run(module, root, {}, tmp_path) == 2


def _variables_with_unreadable_org(module, repo_scope: dict[str, str]):
    """A resolver whose repository scope reads and whose organisation does not.

    Built through the real class with only its one I/O call replaced on the
    instance, so the lazy path under test is the one that ships.
    """

    def fake_read(flag: str, target: str) -> dict[str, str]:
        if flag == "--org":
            raise module.GateError("HTTP 403: Resource not accessible by integration")
        return dict(repo_scope)

    instance = module.Variables("OmniNode-ai/fixture")
    instance._read = fake_read
    return instance


def _variables_with_no_readable_scope(module):
    """Neither scope readable: the live shape with no credential supplied."""

    def fake_read(flag: str, target: str) -> dict[str, str]:
        raise module.GateError("HTTP 403: Resource not accessible by integration")

    instance = module.Variables("OmniNode-ai/fixture")
    instance._read = fake_read
    return instance


def test_a_literal_placement_never_reads_a_variable_at_all(tmp_path: Path) -> None:
    """The majority case, and the reason every read is deferred.

    A repository whose jobs pin their labels needs no credential: if a read
    happened here it would raise, because neither scope is readable.
    """
    module = _module()
    variables = _variables_with_no_readable_scope(module)
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: [self-hosted, omnibase-ci]\n"
        "    steps:\n      - run: true\n",
    )
    assert module.scan(root, "OmniNode-ai/fixture", variables) == []


def test_an_unreadable_repository_scope_refuses_by_name(tmp_path: Path) -> None:
    """No credential plus an expression is a refusal, not a default."""
    module = _module()
    variables = _variables_with_no_readable_scope(module)
    root = _tree(tmp_path, "ci.yml", _seam_job())
    with pytest.raises(module.GateError) as error:
        module.scan(root, "OmniNode-ai/fixture", variables)
    assert "ACTIONS_VARIABLES_TOKEN" in str(error.value)


def test_a_repo_scoped_value_never_needs_the_organisation(tmp_path: Path) -> None:
    """The organisation scope is not read at all when the shadow answers.

    That is what makes the gate runnable with only a job token in every
    repository whose variables are shadowed locally or whose jobs use literals.
    """
    module = _module()
    variables = _variables_with_unreadable_org(
        module,
        {"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET, "OMNI_PUBLIC_PR_RUNS_ON_JSON": FLEET},
    )
    root = _tree(tmp_path, "ci.yml", _seam_job())
    assert module.scan(root, "OmniNode-ai/fixture", variables) == []


def test_an_unreadable_organisation_scope_refuses_rather_than_defaulting(
    tmp_path: Path,
) -> None:
    """ "Unset here" and "unreadable above here" are different facts.

    Falling through to the expression own literal default when the
    organisation scope could not be read is how a repository carrying no
    shadow at all comes back green while inheriting a hosted organisation
    value -- which is exactly what the organisation seam holds today.
    """
    module = _module()
    variables = _variables_with_unreadable_org(module, {})
    root = _tree(tmp_path, "ci.yml", _seam_job())
    with pytest.raises(module.GateError) as error:
        module.scan(root, "OmniNode-ai/fixture", variables)
    assert "ACTIONS_VARIABLES_TOKEN" in str(error.value)


# ---------------------------------------------------------------------------
# OMN-18431: a `uses:` job is judged where the run is BILLED.
#
# The gap these close, measured on omnistream 2026-09-16: its REQUIRED
# `kb-doc-gate` job calls a reusable defined in a PUBLIC repository, whose
# `runs-on` resolves the trusted seam in OMNISTREAM's scope -- no repository
# shadow, organisation value hosted -- so the job lands on a hosted label in a
# private repository and does not start at all. Three seconds, no runner, no
# steps, failing every run since 2026-09-02. The gate reported the repository
# green, because it read the called workflow's placement in the repository that
# DEFINES it, where hosted is the correct answer.
#
# Red-first: with only these tests applied and the resolution unimplemented,
# the two FAIL cases below returned 0 and the unfetchable case returned 0 --
# the gate skipped every `uses:` job. The PASS and public-caller cases already
# passed, which is what makes them controls rather than restatements.
# ---------------------------------------------------------------------------

CALLED = "OmniNode-ai/omniclaude/.github/workflows/kb-doc-gate-reusable.yml@a78b103"

REUSABLE_SEAM = (
    "name: KB Doc Gate (reusable)\non:\n  workflow_call: {}\njobs:\n"
    "  kb-doc-gate:\n    runs-on: >-\n      "
    + SEAM_EXPRESSION.replace("\n", "\n      ")
    + "\n    steps:\n      - run: true\n"
)

CALLER = (
    "name: KB Doc Gate\non:\n  pull_request: {}\njobs:\n"
    "  kb-doc-gate:\n    uses: " + CALLED + "\n"
)


def _run_delegating(
    module,
    root: Path,
    variables: dict[str, str],
    tmp_path: Path,
    called: dict[str, str] | None,
    visibility: str = "private",
) -> int:
    vars_file = tmp_path / "vars.json"
    vars_file.write_text(json.dumps(variables), encoding="utf-8")
    argv = [
        "--repo-root",
        str(root),
        "--repo",
        "OmniNode-ai/omnistream",
        "--assume-visibility",
        visibility,
        "--variables-json",
        str(vars_file),
    ]
    if called is not None:
        called_file = tmp_path / "called.json"
        called_file.write_text(json.dumps(called), encoding="utf-8")
        argv += ["--called-workflows-json", str(called_file)]
    return module.main(argv)


def test_a_delegated_required_job_inheriting_a_hosted_org_value_fails(
    tmp_path: Path,
) -> None:
    """omnistream's exact live shape: private caller, public reusable, no shadow.

    The caller's own file contains no runner label at all, and the called
    workflow is defined in a public repository where `ubuntu-latest` is the
    correct placement. The run is nonetheless billed to the private caller and
    the label is resolved in the private caller's scopes, so this is a
    violation and must be reported against the caller's job.
    """
    module = _module()
    root = _tree(tmp_path, "kb-doc-gate.yml", CALLER)
    assert (
        _run_delegating(
            module,
            root,
            {
                "OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED,
                "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
            },
            tmp_path,
            {CALLED: REUSABLE_SEAM},
        )
        == 1
    )


def test_the_same_delegation_passes_once_the_caller_carries_a_fleet_shadow(
    tmp_path: Path,
) -> None:
    """The fix is the CALLER's routing variable, not an edit to the reusable.

    Same caller file, same called workflow, byte for byte. Only the repository
    scope differs. If this failed too, the gate would be reporting the shared
    workflow rather than the placement, and no repository could ever be green.
    """
    module = _module()
    root = _tree(tmp_path, "kb-doc-gate.yml", CALLER)
    assert (
        _run_delegating(
            module,
            root,
            {
                "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
                "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
            },
            tmp_path,
            {CALLED: REUSABLE_SEAM},
        )
        == 0
    )


def test_a_public_caller_delegating_to_a_hosted_reusable_stays_correct(
    tmp_path: Path,
) -> None:
    """Positive control. Hosted is the RIGHT answer in a public repository.

    Without this, a change that simply failed every delegation would satisfy
    the first test and look like a fix.
    """
    module = _module()
    root = _tree(tmp_path, "kb-doc-gate.yml", CALLER)
    assert (
        _run_delegating(
            module,
            root,
            {
                "OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED,
                "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
            },
            tmp_path,
            {CALLED: REUSABLE_SEAM},
            visibility="public",
        )
        == 0
    )


def test_a_called_workflow_that_cannot_be_fetched_fails_closed(
    tmp_path: Path,
) -> None:
    """Unreadable is exit 2. A gate that cannot see the job has not judged it.

    This is the failure mode the whole change exists to remove: skipping the
    job reports the caller green, and the jobs that delegate are this estate's
    REQUIRED checks.
    """
    module = _module()
    root = _tree(tmp_path, "kb-doc-gate.yml", CALLER)
    assert (
        _run_delegating(
            module,
            root,
            {
                "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
                "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
            },
            tmp_path,
            {},
        )
        == 2
    )


def test_a_delegated_hosted_placement_is_excused_beside_the_CALLER_job(
    tmp_path: Path,
) -> None:
    """The annotation goes where the repository can write it, and only there.

    Writing it beside the called job would excuse every other caller of the
    same shared workflow at once, which is the allowlist this gate refuses to
    have.
    """
    module = _module()
    root = _tree(
        tmp_path,
        "kb-doc-gate.yml",
        "name: KB Doc Gate\non:\n  pull_request: {}\njobs:\n"
        "  kb-doc-gate:\n"
        "    # private-repo-hosted-ok: fixture reason (OMN-18431)\n"
        "    uses: " + CALLED + "\n",
    )
    assert (
        _run_delegating(
            module,
            root,
            {
                "OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED,
                "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
            },
            tmp_path,
            {CALLED: REUSABLE_SEAM},
        )
        == 0
    )


def test_a_nested_delegation_is_followed_to_the_job_that_actually_runs(
    tmp_path: Path,
) -> None:
    """A reusable that calls a reusable still places the run somewhere.

    Stopping at the first hop would restore the original blindness one level
    down, where it is harder to see.
    """
    module = _module()
    inner = "OmniNode-ai/omniclaude/.github/workflows/inner.yml@" + "b" * 40
    outer = "OmniNode-ai/omniclaude/.github/workflows/outer.yml@" + "a" * 40
    root = _tree(
        tmp_path,
        "call.yml",
        "name: Call\non:\n  pull_request: {}\njobs:\n  gate:\n    uses: "
        + outer
        + "\n",
    )
    assert (
        _run_delegating(
            module,
            root,
            {
                "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
                "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
            },
            tmp_path,
            {
                outer: "name: Outer\non:\n  workflow_call: {}\njobs:\n"
                "  hop:\n    uses: " + inner + "\n",
                inner: "name: Inner\non:\n  workflow_call: {}\njobs:\n"
                "  work:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n",
            },
        )
        == 1
    )


def test_an_unrecognised_uses_shape_is_refused_rather_than_skipped(
    tmp_path: Path,
) -> None:
    """A shape the gate cannot parse is not a job it has cleared."""
    module = _module()
    root = _tree(
        tmp_path,
        "call.yml",
        "name: Call\non:\n  pull_request: {}\njobs:\n"
        "  gate:\n    uses: docker://example/thing:1\n",
    )
    assert (
        _run_delegating(
            module,
            root,
            {
                "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
                "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
            },
            tmp_path,
            {},
        )
        == 2
    )


def test_an_annotation_on_the_CALLED_job_does_not_excuse_the_caller(
    tmp_path: Path,
) -> None:
    """A same-repository delegation is read from the checkout, per CALLER.

    The called workflow here carries its own annotation, so the DIRECT scan of
    that file clears it -- which is how this fixture isolates the delegation:
    the only remaining way to reach a finding is by judging the caller's job.
    An exemption written once beside a shared job would otherwise excuse every
    caller of it at a stroke, which is the global allowlist this gate refuses
    to have.
    """
    module = _module()
    root = _tree(
        tmp_path,
        "call.yml",
        "name: Call\non:\n  pull_request: {}\njobs:\n"
        "  gate:\n    uses: ./.github/workflows/local.yml\n",
    )
    _tree(
        tmp_path,
        "local.yml",
        "name: Local\non:\n  workflow_call: {}\njobs:\n"
        "  # private-repo-hosted-ok: cleared for the direct scan (OMN-18431)\n"
        "  work:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n",
    )
    assert (
        _run_delegating(
            module,
            root,
            {
                "OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET,
                "OMNI_PUBLIC_PR_RUNS_ON_JSON": HOSTED,
            },
            tmp_path,
            None,
        )
        == 1
    )


# ---------------------------------------------------------------------------
# OMN-18431: the fixture flags are a TEST boundary, and it is now enforced.
#
# Raised by the adversarial reviewer against `CalledWorkflows`: the class takes
# a fixture from a file and serves it in place of a live fetch. The docstrings
# said "CI never passes it", which is a claim, not a control. A workflow that
# added one would get a gate reporting on a file somebody wrote rather than on
# the live estate, and it would report SUCCESS -- the same false-green shape
# this whole gate exists to remove, one level up.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--variables-json", "vars.json"),
        ("--called-workflows-json", "called.json"),
        ("--assume-visibility", "private"),
    ],
)
def test_a_fixture_flag_is_refused_inside_github_actions(
    flag: str,
    value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inside Actions a fixture cannot stand in for a live read.

    The assertion is on the REASON, not only on exit 2. Without the refusal
    this same invocation ALSO exits 2 -- because the live variable read then
    fails against a fixture repository -- so an exit-code-only test passes on
    the unguarded script and proves nothing. That was measured, not assumed.
    """
    module = _module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    root = _tree(tmp_path, "ci.yml", _seam_job())
    assert (
        module.main(
            ["--repo-root", str(root), "--repo", "OmniNode-ai/fixture", flag, value]
        )
        == 2
    )
    message = capsys.readouterr().err
    assert flag in message
    assert "replaces a live read with a file" in message


def test_the_same_flags_still_work_outside_github_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control. The refusal is scoped, not a removal of the flags.

    Without this, deleting the flags entirely would satisfy the refusals above
    and look like a fix, while taking every test in this file with it.
    """
    module = _module()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    root = _tree(tmp_path, "ci.yml", _seam_job())
    assert _run(module, root, {"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET}, tmp_path) == 0
