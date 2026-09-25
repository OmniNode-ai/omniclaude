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

There is a THIRD way, added by OMN-18205 residual 4 after it cost nine days of
ungreenable `main`-push CI (OMN-18616): the gate can resolve the arms correctly
and never ask WHICH EVENT reaches them. `A && X || Y` has no single answer, and
a guard spelled as a fork test is true under a push for a reason that has
nothing to do with forks -- the head-repository field is simply null there. So
the assertions below are a MATRIX: each selector shape is asserted per trigger
event, and the real pre-fix and post-fix omninode_infra expressions are carried
verbatim as the positive and negative control of the whole change.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "private_repo_runner_placement_gate.py"

FLEET = '["self-hosted","omnibase-ci"]'
HOSTED = '["ubuntu-latest"]'

# THE PRE-FIX SHAPE, copied verbatim from omninode_infra `ci.yml` at
# `c9d0ae9d` -- the commit whose push to `main` acquired no runner at all
# (empty `runner_name`, `labels: ["ubuntu-latest"]`, zero steps). It tests the
# head repository WITHOUT testing the event first, so on every event carrying
# no pull-request payload the field is null, the inequality holds, and the
# public hosted arm is selected. This is the positive control of the change.
SEAM_EXPRESSION = (
    "${{\n"
    "  (github.event.pull_request.head.repo.full_name != github.repository)\n"
    "  && fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]')\n"
    "  || fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
    '\'["self-hosted","omnibase-ci"]\')\n'
    "}}"
)

# THE POST-FIX SHAPE, copied verbatim from omninode_infra `ci.yml` at
# `origin/dev` after `#1540`. The event is tested BEFORE the head repository,
# so every non-pull-request event falls through to the fleet arm. This is the
# negative control: a gate that fails this one is refusing the fix.
GUARDED_SEAM_EXPRESSION = (
    "${{\n"
    '  (contains(fromJSON(\'["pull_request","pull_request_review"]\'), '
    "github.event_name) &&\n"
    "   github.event.pull_request.head.repo.full_name != github.repository)\n"
    "  && fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]')\n"
    "  || fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
    '\'["self-hosted","omnibase-ci"]\')\n'
    "}}"
)

# The triggers omninode_infra `ci.yml` actually declares, at both commits.
CI_TRIGGERS = ("push", "pull_request", "merge_group")

SEAM_VARIABLES = {
    "OMNI_TRUSTED_CI_RUNS_ON_JSON": '["self-hosted","omnibase-ci"]',
    "OMNI_PUBLIC_PR_RUNS_ON_JSON": '["ubuntu-latest"]',
}


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


@contextmanager
def _outside_github_actions():
    existing = os.environ.pop("GITHUB_ACTIONS", None)
    try:
        yield
    finally:
        if existing is not None:
            os.environ["GITHUB_ACTIONS"] = existing


def _fixture_call(call: Callable[[], int]) -> int:
    with _outside_github_actions():
        return call()


def _run(
    module,
    root: Path,
    variables: dict[str, str],
    tmp_path: Path,
    branches: list[str] | None = None,
) -> int:
    vars_file = tmp_path / "vars.json"
    vars_file.write_text(json.dumps(variables), encoding="utf-8")
    argv = [
        "--repo-root",
        str(root),
        "--repo",
        "OmniNode-ai/fixture",
        "--assume-visibility",
        "private",
        "--variables-json",
        str(vars_file),
    ]
    # Default to a repository with no branch this gate could read, which is the
    # pessimistic reading: a ref comparison is assumed satisfiable. Tests that
    # care about the branch list pass one explicitly.
    argv += ["--branches-json", json.dumps(branches if branches is not None else [])]
    return _fixture_call(lambda: module.main(argv))


def _seam_job(
    expression: str = SEAM_EXPRESSION,
    triggers: tuple[str, ...] = ("pull_request",),
) -> str:
    """One job whose runs-on is `expression`, under the given triggers.

    The trigger list is a parameter rather than a constant because it is half
    of the verdict: the same selector is a live defect in a workflow that
    declares `push` and a latent one in a workflow that does not, and a fixture
    that hardcoded one trigger could only ever assert half the matrix.
    """
    return (
        "name: CI\non:\n"
        + "".join(f"  {trigger}: {{}}\n" for trigger in triggers)
        + "jobs:\n"
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
        _fixture_call(
            lambda: module.main(
                [
                    "--repo-root",
                    str(root),
                    "--repo",
                    "OmniNode-ai/fixture",
                    "--assume-visibility",
                    "public",
                ]
            )
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

    THE NEGATIVE CONTROL OF THIS WHOLE CHANGE. The expression is the post-fix
    omninode_infra one, verbatim, under the triggers that file really declares.
    A gate that fails this is refusing the fix rather than the defect.
    """
    module = _module()
    root = _tree(tmp_path, "ci.yml", _seam_job(GUARDED_SEAM_EXPRESSION, CI_TRIGGERS))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path) == 0


def test_positive_control_the_pre_fix_omninode_infra_expression_is_caught(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The defect this change exists to see, in the bytes that carried it.

    omninode_infra `ci.yml` at `c9d0ae9d`: the head repository tested with no
    event test in front of it, in a workflow declaring `push`, `pull_request`
    and `merge_group`. On `push` and on `merge_group` the head-repository field
    is null, `null != 'OmniNode-ai/fixture'` holds, and the run takes the
    public hosted arm. The pre-change gate reported this repository GREEN for
    nine days while `main`-push CI could not go green at all.
    """
    module = _module()
    root = _tree(tmp_path, "ci.yml", _seam_job(SEAM_EXPRESSION, CI_TRIGGERS))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path) == 1
    reported = capsys.readouterr().err
    assert "push" in reported and "merge_group" in reported, reported
    # The fork cell is the one hosted placement that is REQUIRED, so it must
    # not be named among the offending events -- otherwise the gate would be
    # asking for the prohibited placement.
    assert "pull_request:fork" not in reported, reported


def test_the_same_pre_fix_expression_is_latent_not_red_without_the_trigger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The narrowing, asserted rather than assumed.

    A job cannot run under a trigger its workflow does not carry, so the very
    same expression in a pull-request-only workflow places nothing hosted
    today. It is still PRINTED, on the pass path, because that is the state
    `infra-consistency-check.yml` sat in for months -- its own comment said
    "a live defect the day somebody adds a push trigger" and nothing but that
    comment was watching. The pull request that adds the trigger is judged by
    this gate at that moment, which is the mechanism this narrowing rests on.
    """
    module = _module()
    root = _tree(tmp_path, "ci.yml", _seam_job(SEAM_EXPRESSION, ("pull_request",)))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path) == 0
    printed = capsys.readouterr().out
    assert "LATENT" in printed and "push" in printed, printed


def test_an_inverted_guard_that_defaults_to_hosted_is_still_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The OMN-16683 inversion, judged for the reason it is actually wrong.

    Here the guard selects the TRUSTED class and the unguarded default is the
    public one. The previous revision of this test asserted that "an ordinary
    same-repo pull request lands on a hosted runner", and that claim was FALSE
    of this expression: on a same-repo pull request the equality holds and the
    run goes to the fleet. The old gate flagged it anyway, because it reported
    any hosted arm that was not fork-guarded without asking which event reached
    it -- a correct verdict resting on a wrong reading.

    Evaluated per event the inversion is still a defect, and now for its real
    reason: on every event with no pull-request payload the equality is FALSE,
    so the fall-through hosted arm is the one that places the run.
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
    root = _tree(tmp_path, "ci.yml", _seam_job(inverted, CI_TRIGGERS))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path) == 1
    assert "push" in capsys.readouterr().err


def test_a_fork_guarded_branch_that_is_the_only_branch_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A carve-out with nothing to fall back to is just a hosted pin.

    Seen from the event side this is not a hosted placement at all, it is a
    placement onto NOTHING: under an ordinary same-repository pull request the
    fork guard is false, no arm is selected, `runs-on` evaluates to a falsy
    value and GitHub schedules the job onto no runner. Reported as its own
    finding, because "the job cannot start" is a different defect from "the job
    starts in the wrong place" and the fix is different too.
    """
    module = _module()
    only_fork = (
        "${{\n"
        "  (github.event.pull_request.head.repo.full_name != github.repository)\n"
        "  && fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]')\n"
        "}}"
    )
    root = _tree(tmp_path, "ci.yml", _seam_job(only_fork))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path) == 1
    assert "selects no arm at all" in capsys.readouterr().err


def test_a_guard_that_is_not_a_fork_test_excuses_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-fork guard cannot inherit the fork cell's exemption.

    The exemption is now one CELL of the matrix -- a pull request whose head
    repository is a fork -- rather than a list of blessed guard spellings, so
    there is no spelling to inherit. A hosted arm reached by a schedule is a
    hosted arm reached by a schedule, and the workflow here declares `schedule`
    so the cell is live rather than latent.
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
    root = _tree(
        tmp_path, "ci.yml", _seam_job(not_a_fork_test, ("pull_request", "schedule"))
    )
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path) == 1
    assert "schedule" in capsys.readouterr().err


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


# ---------------------------------------------------------------------------
# THE EVALUATOR. The fork regex these tests replaced asserted that a STRING
# looked like a fork test. It could not answer the only question that matters
# -- when is the guard TRUE -- so `head.repo.full_name != github.repository`
# passed as "a fork test" while being true on every push in the estate. What is
# asserted now is the truth value of each guard under each event.
# ---------------------------------------------------------------------------


def _context(module, key: str):
    for context in module.EVENT_MATRIX:
        if context.key == key:
            return context
    raise AssertionError(f"no such event context: {key}")


FORK_SPELLINGS = [
    "github.event.pull_request.head.repo.full_name != github.repository",
    "github.event.pull_request.head.repo.fork == true",
    "github.event.pull_request.head.repo.fork",
]


@pytest.mark.parametrize("guard", FORK_SPELLINGS)
@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("pull_request:fork", True),
        ("pull_request:base", False),
        ("push", None),
        ("workflow_dispatch", None),
        ("repository_dispatch", None),
        ("schedule", None),
        ("merge_group", None),
        ("workflow_run", None),
        ("release", None),
    ],
)
def test_each_fork_spelling_is_evaluated_per_event(
    guard: str, event: str, expected: bool | None
) -> None:
    """The whole defect, reduced to a truth table.

    `expected is None` marks the events with no pull-request payload, where the
    three spellings DISAGREE and the disagreement is the bug. The `!=` form is
    TRUE there -- null is unequal to a non-empty slug -- and selects the public
    hosted arm on every push, dispatch and schedule in a private repository.
    The two `fork`-flag forms are FALSE there, because null is falsy. A gate
    that matched these three as interchangeable "fork tests" was reading a
    string where the estate's behaviour differs.
    """
    module = _module()
    context = _context(module, event)
    actual = module._guard(guard, context, "OmniNode-ai/fixture", "fixture::job")
    if expected is None:
        expected = "full_name" in guard
    assert actual is expected


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("pull_request:fork", True),
        ("pull_request:base", False),
        ("pull_request_review:fork", True),
        ("pull_request_review:base", False),
        ("push", False),
        ("workflow_dispatch", False),
        ("repository_dispatch", False),
        ("schedule", False),
        ("merge_group", False),
        ("workflow_run", False),
        ("release", False),
    ],
)
def test_the_event_guarded_spelling_is_true_only_for_a_fork_pull_request(
    event: str, expected: bool
) -> None:
    """The fix, asserted cell by cell rather than as a subset claim.

    Testing the event FIRST collapses every non-pull-request cell to false, so
    the public arm becomes reachable from exactly the two cells where a hosted
    placement is required. Both `pull_request_review` cells are asserted
    because the estate's guard names that event in its `contains()` list; a
    matrix that never fired it would leave half the guard unexercised.
    """
    module = _module()
    guard = (
        '(contains(fromJSON(\'["pull_request","pull_request_review"]\'), '
        "github.event_name) && "
        "github.event.pull_request.head.repo.full_name != github.repository)"
    )
    context = _context(module, event)
    assert (
        module._guard(guard, context, "OmniNode-ai/fixture", "fixture::job") is expected
    )


@pytest.mark.parametrize(
    ("guard", "event", "expected"),
    [
        ("github.event_name == 'push'", "push", True),
        ("github.event_name == 'push'", "schedule", False),
        ("github.event_name != 'push'", "schedule", True),
        ("!(github.event_name == 'push')", "push", False),
        ("github.repository == 'OmniNode-ai/fixture'", "push", True),
        ("github.repository_owner == 'OmniNode-ai'", "push", True),
        ("contains('abcdef', 'cd')", "push", True),
        (
            "github.event_name == 'push' || github.event_name == 'schedule'",
            "schedule",
            True,
        ),
        (
            "github.event_name == 'push' && github.repository == 'other/repo'",
            "push",
            False,
        ),
        # A parenthesised disjunction of conjunctions -- omniclaude's own
        # kb-doc-gate reusable writes exactly this, and parsing its arms as a
        # comparison produced three operands and a refusal that hid a live
        # omnistream finding.
        (
            "((github.event_name == 'pull_request' && github.base_ref == 'dev') || "
            "(github.event_name == 'pull_request' && "
            "github.event.pull_request.head.repo.full_name != github.repository))",
            "push",
            False,
        ),
        # The OMN-16683 inversion, and the reason it is a defect: the equality
        # is FALSE on every event with no pull-request payload.
        (
            "github.event.pull_request.head.repo.full_name == github.repository",
            "push",
            False,
        ),
        # GitHub casts mismatched types to number: null -> 0 and false -> 0,
        # so `null == false` is TRUE. This guard therefore selects its arm on
        # every event with no pull-request payload -- the inverted twin of the
        # OMN-18616 defect, and just as invisible to a textual reading.
        ("github.event.pull_request.head.repo.fork == false", "push", True),
        (
            "github.event.pull_request.head.repo.fork == false",
            "pull_request:base",
            True,
        ),
    ],
)
def test_the_expression_subset_the_estate_writes(
    guard: str, event: str, expected: bool
) -> None:
    module = _module()
    context = _context(module, event)
    assert (
        module._guard(guard, context, "OmniNode-ai/fixture", "fixture::job") is expected
    )


@pytest.mark.parametrize(
    "guard",
    [
        # A context field the evaluator has not been taught.
        "github.event.pull_request.draft == true",
        # A filter expression -- the shape the old regex list happened to name.
        "contains(github.event.pull_request.labels.*.name, 'fork')",
        # An ordering comparison: nothing routes on one, so its arrival means
        # a shape landed that this gate was never taught.
        "github.run_number > 3",
        # A function it does not implement.
        "startsWith(github.ref, 'refs/tags/')",
        # Chained equality, which GitHub does not mean the way it reads.
        "github.event_name == 'push' == true",
    ],
)
def test_an_unreadable_guard_refuses_rather_than_passing(guard: str) -> None:
    """Fail closed, naming the job -- never a silent pass.

    This is the property that makes the narrowing safe. A gate that skipped a
    guard it could not parse would report exactly the green it reported for
    nine days; refusing means a new selector shape stops the merge until
    somebody teaches the evaluator what it means.
    """
    module = _module()
    context = _context(module, "push")
    with pytest.raises(module.GateError) as caught:
        module._guard(guard, context, "OmniNode-ai/fixture", "ci.yml::build")
    assert "ci.yml::build" in str(caught.value)
    assert "THE GATE DID NOT RUN" in str(caught.value)


def test_an_unreadable_guard_in_an_all_fleet_expression_is_not_refused(
    tmp_path: Path,
) -> None:
    """Evaluation is demanded exactly where the answer depends on it.

    When no arm carries a hosted label and some arm is unguarded, every event
    lands on some arm and none of them is hosted -- whatever the guard means.
    Refusing there would take the gate down over a shape that cannot change any
    verdict, which is how an enforcement surface gets switched off.
    """
    module = _module()
    exotic = (
        "${{\n"
        "  startsWith(github.ref, 'refs/tags/')\n"
        "  && fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON)\n"
        "  || fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON)\n"
        "}}"
    )
    root = _tree(tmp_path, "ci.yml", _seam_job(exotic, CI_TRIGGERS))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path) == 0


def test_null_compares_the_way_github_compares_it() -> None:
    """The one semantic the entire defect turns on, pinned on its own.

    An absent context field is null. Null is unequal to a non-empty string and
    equal to the empty one, and it is falsy. Bound here as a named assertion
    rather than left implicit inside a guard, because if this is wrong every
    cell of the matrix is wrong in the same direction.
    """
    module = _module()
    assert module._equal(module.MISSING, "OmniNode-ai/fixture") is False
    assert module._equal(module.MISSING, "") is True
    assert module._equal(module.MISSING, False) is True
    assert module._truthy(module.MISSING) is False


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("on:\n  pull_request: {}\n", {"pull_request"}),
        ("on: push\n", {"push"}),
        ("on: [push, schedule]\n", {"push", "schedule"}),
        ("'on':\n  push: {}\n", {"push"}),
    ],
)
def test_the_trigger_block_is_read_through_the_yaml_boolean_key(
    block: str, expected: set[str]
) -> None:
    """`on` is the YAML 1.1 boolean true, and PyYAML resolves it that way.

    A gate that read only the string key would find no triggers in any real
    workflow file, judge every job over an empty matrix, and pass everything --
    a silent green produced by a parser quirk rather than by the estate.
    """
    module = _module()
    document = yaml.safe_load(block + "jobs:\n  build:\n    runs-on: x\n")
    contexts = module.declared_contexts(document, "ci.yml")
    assert {context.event_name for context in contexts} == expected


def test_a_reusable_workflow_is_judged_over_the_whole_matrix() -> None:
    """A called workflow runs under whatever event its CALLER fired.

    Its own `on:` block says only `workflow_call`, which names no event at all,
    so narrowing to it would judge every reusable over an empty matrix. The
    whole matrix is the only honest reading available from here.
    """
    module = _module()
    document = yaml.safe_load(
        "on:\n  workflow_call: {}\njobs:\n  build:\n    runs-on: x\n"
    )
    contexts = module.declared_contexts(document, "reusable.yml")
    assert contexts == module.EVENT_MATRIX


def test_an_event_outside_the_matrix_is_modelled_with_no_pull_request_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unmodelled trigger is judged, not skipped.

    Every event outside the pull-request family shares the one property any
    routing guard in this estate reads: no pull-request payload. So an
    `issue_comment`-triggered workflow carrying the pre-fix selector takes the
    public arm exactly as a push does, and is reported as such.
    """
    module = _module()
    root = _tree(tmp_path, "ci.yml", _seam_job(SEAM_EXPRESSION, ("issue_comment",)))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path) == 1
    assert "issue_comment" in capsys.readouterr().err


def test_a_workflow_with_no_trigger_block_fails_closed(tmp_path: Path) -> None:
    """Which events reach a job is what decides where it runs."""
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: true\n",
    )
    assert _run(module, root, {}, tmp_path) == 2


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
    return _fixture_call(lambda: module.main(argv))


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


# ---------------------------------------------------------------------------
# A COMPARISON AGAINST A REF THIS GATE CANNOT KNOW. omniclaude's own
# kb-doc-gate reusable sends a pull request whose BASE is `dev` to the public
# hosted class. Whether that can happen in a given private repository is not a
# property of the expression, it is a property of the repository: omnistream
# has exactly one branch, `main`, so no pull request there can ever reach that
# arm. Both readings are asserted, because a gate that reported the
# unreachable one would be teaching people to scroll past it.
# ---------------------------------------------------------------------------

KB_DOC_GATE_EXPRESSION = (
    "${{\n"
    "  ((github.event_name == 'pull_request' && github.base_ref == 'dev') ||\n"
    "   (github.event_name == 'pull_request' &&\n"
    "    github.event.pull_request.head.repo.full_name != github.repository))\n"
    "  && fromJSON(vars.OMNI_PUBLIC_PR_RUNS_ON_JSON || '[\"ubuntu-latest\"]')\n"
    "  || fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
    '\'["self-hosted","omnibase-ci"]\')\n'
    "}}"
)


def test_a_reachable_base_ref_comparison_is_a_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A repository that HAS the branch can take the hosted arm, so it is red."""
    module = _module()
    root = _tree(tmp_path, "kb.yml", _seam_job(KB_DOC_GATE_EXPRESSION))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path, ["main", "dev"]) == 1
    assert "ref matches" in capsys.readouterr().err


def test_an_unreachable_base_ref_comparison_is_not_a_finding(
    tmp_path: Path,
) -> None:
    """omnistream, live: one branch, `main`, so that arm is unreachable.

    The live branch list is what makes this answerable. A hardcoded list would
    go stale the first time somebody cuts a branch, and the first cut would
    turn a silent pass into a live hosted placement with nothing watching.
    """
    module = _module()
    root = _tree(tmp_path, "kb.yml", _seam_job(KB_DOC_GATE_EXPRESSION))
    assert _run(module, root, dict(SEAM_VARIABLES), tmp_path, ["main"]) == 0


def test_an_unreadable_branch_list_assumes_the_comparison_can_match(
    tmp_path: Path,
) -> None:
    """Fail closed: unreadable must never become "unreachable"."""
    module = _module()
    refs = module.RefNames("OmniNode-ai/does-not-exist-anywhere")
    # Force the unreadable path without a network round trip.
    refs._readable = False
    assert refs.names() is None
    assert refs.could_match({"dev"}) is True


# --- OMN-18431: every branch that runs workflows is judged, not only the one
# the gate happens to be checked out on.
#
# THE MISS THIS CLOSES. The gate judged exactly one tree: the checkout of the
# event that fired it. Its caller file lived on the default branch only, and a
# push to (or a pull request into) any OTHER branch reads that branch's own
# workflow files -- so a branch that never received the caller was never
# judged at all. One private repository's stale `main` carried eight hosted
# jobs in `ci.yml` (and five more elsewhere) while the gate reported the
# repository green from `dev`; every job on `main` was refused before it
# started, and no pull request into `main` could pass its required checks.
# The fixture below is that `main`'s trigger-and-placement skeleton.

STALE_MAIN_CI = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "private_repo_runner_placement"
    / "stale_main_ci.yml"
).read_text(encoding="utf-8")

FLEET_CI = (
    "name: CI\non:\n  push:\n    branches: [dev, 'hotfix/**']\n"
    "  pull_request:\n    branches: [main, dev, 'hotfix/**']\n"
    "jobs:\n  gates:\n    runs-on: [self-hosted, omnibase-ci]\n"
    "    steps:\n      - run: true\n"
)

STALE_MAIN_HOSTED_JOBS = (
    "gates",
    "design-guards",
    "ci-summary",
    "build-and-push",
    "notify-infra",
    "deploy",
    "lighthouse",
    "playwright-e2e",
)


def _git(cwd: Path, *args: str) -> str:
    import subprocess

    from omnibase_core.validators.no_unguarded_git_subprocess import (
        scrub_git_location_env,
    )

    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            **scrub_git_location_env(os.environ),
            "GIT_AUTHOR_NAME": "fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(cwd),
        },
    ).stdout


def _origin_with_branches(
    tmp_path: Path, default: str, trees: dict[str, dict[str, str] | None]
) -> Path:
    """A bare origin whose branches carry the given workflow trees.

    `trees` maps a branch name to {workflow file name: YAML text}, or to None
    for a branch with no `.github/workflows` at all. The origin's HEAD names
    `default`, which is how the gate learns the default branch.
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-q", str(origin))
    author = tmp_path / "author"
    _git(tmp_path, "init", "-q", str(author))
    _git(author, "remote", "add", "origin", str(origin))
    for branch, files in trees.items():
        _git(author, "checkout", "-q", "--orphan", branch)
        _git(author, "rm", "-rfq", "--ignore-unmatch", ".")
        (author / "README").write_text(branch, encoding="utf-8")
        for name, body in (files or {}).items():
            path = author / ".github" / "workflows" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        _git(author, "add", "-A")
        _git(author, "commit", "-qm", f"{branch} tree")
        _git(author, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    _git(origin, "symbolic-ref", "HEAD", f"refs/heads/{default}")
    return origin


def _checkout(tmp_path: Path, origin: Path, branch: str) -> Path:
    """The gate's own view: a clone of the event branch, every head fetched."""
    work = tmp_path / "checkout"
    _git(tmp_path, "clone", "-q", "--branch", branch, str(origin), str(work))
    _git(work, "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")
    return work


def _run_every_branch(
    module,
    root: Path,
    tmp_path: Path,
    event_branch: str,
    branches: list[str],
) -> int:
    vars_file = tmp_path / "vars.json"
    vars_file.write_text(json.dumps(dict(SEAM_VARIABLES)), encoding="utf-8")
    argv = [
        "--repo-root",
        str(root),
        "--repo",
        "OmniNode-ai/fixture",
        "--assume-visibility",
        "private",
        "--variables-json",
        str(vars_file),
        "--branches-json",
        json.dumps(branches),
        "--every-workflow-branch",
        "--event-branch",
        event_branch,
    ]
    return _fixture_call(lambda: module.main(argv))


def test_positive_control_a_stale_main_fails_the_gate_run_from_dev(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The miss itself: judged from `dev`, the stale `main` must go red.

    Every hosted job of that `main` is named, against the branch it lives on,
    so the finding says where to make the change.
    """
    module = _module()
    origin = _origin_with_branches(
        tmp_path,
        "dev",
        {"dev": {"ci.yml": FLEET_CI}, "main": {"ci.yml": STALE_MAIN_CI}},
    )
    work = _checkout(tmp_path, origin, "dev")
    assert _run_every_branch(module, work, tmp_path, "dev", ["dev", "main"]) == 1
    err = capsys.readouterr().err
    for job in STALE_MAIN_HOSTED_JOBS:
        assert f"main:ci.yml::{job}\n" in err, job


def test_the_same_tree_passes_when_only_the_checkout_is_judged(
    tmp_path: Path,
) -> None:
    """Why the miss happened: the single-tree reading never sees `main`.

    Kept as a test rather than a comment so that the difference between the
    two readings stays measured: if this ever fails, the default reading has
    started enumerating branches and the flag above is no longer the switch.
    """
    module = _module()
    origin = _origin_with_branches(
        tmp_path,
        "dev",
        {"dev": {"ci.yml": FLEET_CI}, "main": {"ci.yml": STALE_MAIN_CI}},
    )
    work = _checkout(tmp_path, origin, "dev")
    assert _run(module, work, dict(SEAM_VARIABLES), tmp_path, ["dev", "main"]) == 0


def test_every_branch_passes_once_main_is_on_the_fleet(tmp_path: Path) -> None:
    """The negative control: a gate that fails this is refusing the fix."""
    module = _module()
    fixed_main = STALE_MAIN_CI.replace(
        "runs-on: ubuntu-latest", "runs-on: [self-hosted, omnibase-ci]"
    )
    origin = _origin_with_branches(
        tmp_path,
        "dev",
        {"dev": {"ci.yml": FLEET_CI}, "main": {"ci.yml": fixed_main}},
    )
    work = _checkout(tmp_path, origin, "dev")
    assert _run_every_branch(module, work, tmp_path, "dev", ["dev", "main"]) == 0


def test_the_event_branch_is_judged_from_the_checkout_not_its_old_tip(
    tmp_path: Path,
) -> None:
    """A pull request INTO the stale branch that fixes it must be able to pass.

    The checkout is the merge of the fix onto `main`, and it supersedes
    `origin/main`. Judging the old tip as well would fail the one change that
    repairs it.
    """
    module = _module()
    origin = _origin_with_branches(
        tmp_path,
        "dev",
        {"dev": {"ci.yml": FLEET_CI}, "main": {"ci.yml": STALE_MAIN_CI}},
    )
    work = _checkout(tmp_path, origin, "main")
    fixed = STALE_MAIN_CI.replace(
        "runs-on: ubuntu-latest", "runs-on: [self-hosted, omnibase-ci]"
    )
    (work / ".github" / "workflows" / "ci.yml").write_text(fixed, encoding="utf-8")
    assert _run_every_branch(module, work, tmp_path, "main", ["dev", "main"]) == 0


def test_a_branch_named_by_a_push_filter_glob_is_judged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`hotfix/**` in a trigger filter makes every `hotfix/` branch run CI.

    A dormant branch of that shape is refused the moment somebody pushes to
    it, so it is judged now, not then.
    """
    module = _module()
    origin = _origin_with_branches(
        tmp_path,
        "dev",
        {
            "dev": {"ci.yml": FLEET_CI},
            "hotfix/old": {"ci.yml": STALE_MAIN_CI},
        },
    )
    work = _checkout(tmp_path, origin, "dev")
    assert _run_every_branch(module, work, tmp_path, "dev", ["dev", "hotfix/old"]) == 1
    assert "hotfix/old:ci.yml::gates\n" in capsys.readouterr().err


def test_a_feature_branch_no_filter_names_is_not_enumerated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only a match-all filter reaches `feature/x`; its own PR judges it.

    Enumerating every branch a match-all pattern admits would make every
    abandoned feature branch in the repository a red on every other pull
    request -- a gate people learn to scroll past.
    """
    module = _module()
    everything = FLEET_CI.replace("branches: [dev, 'hotfix/**']", "branches: ['**']")
    origin = _origin_with_branches(
        tmp_path,
        "dev",
        {"dev": {"ci.yml": everything}, "feature/x": {"ci.yml": STALE_MAIN_CI}},
    )
    work = _checkout(tmp_path, origin, "dev")
    assert _run_every_branch(module, work, tmp_path, "dev", ["dev", "feature/x"]) == 0
    assert "feature/x" not in capsys.readouterr().err


def test_a_branch_with_no_workflows_is_reported_and_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No workflow directory on a branch means nothing runs there."""
    module = _module()
    origin = _origin_with_branches(
        tmp_path, "dev", {"dev": {"ci.yml": FLEET_CI}, "main": None}
    )
    work = _checkout(tmp_path, origin, "dev")
    assert _run_every_branch(module, work, tmp_path, "dev", ["dev", "main"]) == 0
    assert "main" in capsys.readouterr().out


def test_no_fetched_branches_fails_closed(tmp_path: Path) -> None:
    """A checkout that never fetched the other heads has judged nothing."""
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  build:\n    runs-on: [self-hosted, omnibase-ci]\n"
        "    steps:\n      - run: true\n",
    )
    _git(root, "init", "-q")
    assert _run_every_branch(module, root, tmp_path, "dev", ["dev"]) == 2
