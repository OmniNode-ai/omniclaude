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
    """Free text is a justification, not a commitment to move the job."""
    module = _module()
    root = _tree(
        tmp_path,
        "ci.yml",
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        "  # private-repo-hosted-ok: it has always been like this\n"
        "  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n",
    )
    assert _run(module, root, {}, tmp_path) == 1


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


def test_a_uses_job_is_not_silently_exempt(tmp_path: Path) -> None:
    """A `uses:` job has no runs-on of its own; it is REPORTED, not ignored."""
    module = _module()
    root = _tree(
        tmp_path,
        "call.yml",
        "name: Call\non:\n  pull_request: {}\njobs:\n"
        "  gate:\n    uses: OmniNode-ai/other/.github/workflows/x.yml@abc\n",
    )
    calls = module.reusable_calls(root)
    assert calls == [
        ("call.yml", "gate", "OmniNode-ai/other/.github/workflows/x.yml@abc")
    ]


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
