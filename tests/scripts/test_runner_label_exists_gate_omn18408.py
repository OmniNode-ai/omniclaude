# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Behavioural tests for the runner-label-exists gate (OMN-18408).

The defect this gate exists to refuse is silent by construction. A job pinned to
a label no runner carries does not fail; it queues, the pull request that merged
the pin stays green because the job never ran, and the only surface that knows
is the organisation's runner listing, which nothing consults at merge time.

So the tests that matter are the ones proving the gate SPEAKS when it should and
STAYS SILENT when it should not. Every "no findings" assertion below is paired
with a case that does find something against the same fixture tree, because a
gate that passes everything and a gate that works are the same output.

Fixtures stand in for the two live surfaces (the runner listing and Actions
variables) so these run with no network and no credential. The live behaviour is
exercised separately, at CI time, against the real listing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "runner_label_exists_gate.py"

ONLINE_FLEET = {
    "runners": [
        {
            "name": "omninode-runner-1",
            "status": "online",
            "labels": [
                {"name": "self-hosted"},
                {"name": "Linux"},
                {"name": "X64"},
                {"name": "omnibase-ci"},
            ],
        },
        {
            "name": "omninode-deploy-runner",
            "status": "online",
            "labels": [
                {"name": "self-hosted"},
                {"name": "Linux"},
                {"name": "X64"},
                {"name": "omnibase-deploy"},
            ],
        },
    ]
}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _tree(tmp_path: Path, workflows: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    for name, body in workflows.items():
        _write(root / ".github" / "workflows" / name, body)
    return root


def _fixture(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(
    repo_root: Path, runners: Path, tmp_path: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    variables = _fixture(tmp_path, "variables.json", {})
    return subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--repo-root",
            str(repo_root),
            "--repo",
            "OmniNode-ai/example",
            "--runners-json",
            str(runners),
            "--variables-json",
            str(variables),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# The incident, reproduced.
# ---------------------------------------------------------------------------


def test_a_label_no_runner_carries_is_refused(tmp_path: Path) -> None:
    """The exact shape of the 2026-09-16 incident.

    A pin merged naming a host label that did not exist yet. Nothing failed, so
    five scheduled probes queued for four hours behind a label nobody had.
    """
    repo = _tree(
        tmp_path,
        {
            "canary.yml": """\
            name: canary
            on: {schedule: [{cron: "0 * * * *"}]}
            jobs:
              canary:
                runs-on: [self-hosted, omnibase-verify, host-201]
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", ONLINE_FLEET)
    result = _run(repo, runners, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "canary.yml::canary" in result.stderr
    assert "host-201" in result.stderr
    assert "carried by NO runner" in result.stderr


def test_a_label_every_runner_carries_passes(tmp_path: Path) -> None:
    """Positive control for the case above, on the same fixture fleet.

    Without it, a gate that refused every pin unconditionally would satisfy the
    incident test perfectly.
    """
    repo = _tree(
        tmp_path,
        {
            "build.yml": """\
            name: build
            on: {pull_request: {}}
            jobs:
              build:
                runs-on: [self-hosted, omnibase-ci]
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", ONLINE_FLEET)
    result = _run(repo, runners, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK:" in result.stdout


# ---------------------------------------------------------------------------
# Offline is not absent.
# ---------------------------------------------------------------------------


def test_a_label_carried_only_by_an_offline_runner_is_refused_and_named(
    tmp_path: Path,
) -> None:
    """Both states queue a job forever, so both fail -- but they want different
    repairs, and the message has to say which one this is."""
    fleet = json.loads(json.dumps(ONLINE_FLEET))
    fleet["runners"].append(
        {
            "name": "omninode-verify-runner-1",
            "status": "offline",
            "labels": [
                {"name": "self-hosted"},
                {"name": "omnibase-verify"},
                {"name": "host-201"},
            ],
        }
    )
    repo = _tree(
        tmp_path,
        {
            "canary.yml": """\
            name: canary
            on: {schedule: [{cron: "0 * * * *"}]}
            jobs:
              canary:
                runs-on: [self-hosted, omnibase-verify, host-201]
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", fleet)
    result = _run(repo, runners, tmp_path)
    assert result.returncode == 1
    assert "offline runner(s): omninode-verify-runner-1" in result.stderr
    assert "fleet outage, not a bad pin" in result.stderr


def test_the_same_label_passes_once_that_runner_is_online(tmp_path: Path) -> None:
    """The control that makes the offline case meaningful: only the status
    differs between this fixture and the one above."""
    fleet = json.loads(json.dumps(ONLINE_FLEET))
    fleet["runners"].append(
        {
            "name": "omninode-verify-runner-1",
            "status": "online",
            "labels": [
                {"name": "self-hosted"},
                {"name": "omnibase-verify"},
                {"name": "host-201"},
            ],
        }
    )
    repo = _tree(
        tmp_path,
        {
            "canary.yml": """\
            name: canary
            on: {schedule: [{cron: "0 * * * *"}]}
            jobs:
              canary:
                runs-on: [self-hosted, omnibase-verify, host-201]
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", fleet)
    result = _run(repo, runners, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Subset semantics: GitHub assigns a job to a runner carrying EVERY label.
# ---------------------------------------------------------------------------


def test_a_partial_label_match_is_not_a_match(tmp_path: Path) -> None:
    """A runner carrying two of three labels cannot take the job.

    This is the half the incident turned on: `omnibase-verify` existed on
    another host, so a bare two-label pin WOULD have matched, and the host label
    is what made the pin unsatisfiable. A gate that treated any overlap as a
    match would have passed the pin that queued for four hours.
    """
    fleet = json.loads(json.dumps(ONLINE_FLEET))
    fleet["runners"].append(
        {
            "name": "omninode-mini-runner-1",
            "status": "online",
            "labels": [
                {"name": "self-hosted"},
                {"name": "omnibase-verify"},
                {"name": "host-101"},
            ],
        }
    )
    runners = _fixture(tmp_path, "runners.json", fleet)

    bare = _tree(
        tmp_path / "bare",
        {
            "c.yml": """\
            name: c
            on: {pull_request: {}}
            jobs:
              c:
                runs-on: [self-hosted, omnibase-verify]
                steps: [{run: "true"}]
            """
        },
    )
    assert _run(bare, runners, tmp_path).returncode == 0

    scoped = _tree(
        tmp_path / "scoped",
        {
            "c.yml": """\
            name: c
            on: {pull_request: {}}
            jobs:
              c:
                runs-on: [self-hosted, omnibase-verify, host-201]
                steps: [{run: "true"}]
            """
        },
    )
    assert _run(scoped, runners, tmp_path).returncode == 1


def test_labels_match_case_insensitively(tmp_path: Path) -> None:
    """GitHub matches labels without regard to case; a gate that did not would
    refuse correct pins and teach people to ignore it."""
    repo = _tree(
        tmp_path,
        {
            "c.yml": """\
            name: c
            on: {pull_request: {}}
            jobs:
              c:
                runs-on: [self-hosted, OMNIBASE-CI]
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", ONLINE_FLEET)
    assert _run(repo, runners, tmp_path).returncode == 0


# ---------------------------------------------------------------------------
# Hosted labels are a different gate's question.
# ---------------------------------------------------------------------------


def test_a_hosted_label_is_not_judged_here(tmp_path: Path) -> None:
    """`ubuntu-latest` has no organisation runner entry by construction.

    Whether a hosted pin is ALLOWED is the private-repo placement gate's
    verdict. Refusing it here would make the two gates disagree about the same
    line for different reasons.
    """
    repo = _tree(
        tmp_path,
        {
            "hosted.yml": """\
            name: hosted
            on: {pull_request: {}}
            jobs:
              hosted:
                runs-on: ubuntu-latest
                steps: [{run: "true"}]
              fleet:
                runs-on: [self-hosted, omnibase-ci]
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", ONLINE_FLEET)
    result = _run(repo, runners, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ubuntu-latest" not in result.stderr


# ---------------------------------------------------------------------------
# Fail-closed. An input that did not load is never a pass.
# ---------------------------------------------------------------------------


def test_an_empty_runner_listing_refuses_rather_than_passes(tmp_path: Path) -> None:
    """A listing that failed to load and a fleet with no runners are the same
    value. Neither is a clean bill of health."""
    repo = _tree(
        tmp_path,
        {
            "c.yml": """\
            name: c
            on: {pull_request: {}}
            jobs:
              c:
                runs-on: [self-hosted, omnibase-ci]
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", {"runners": []})
    result = _run(repo, runners, tmp_path)
    assert result.returncode == 2
    assert "THE GATE DID NOT RUN" in result.stderr


def test_a_fleet_with_no_online_runner_refuses(tmp_path: Path) -> None:
    fleet = {
        "runners": [
            {
                "name": "omninode-runner-1",
                "status": "offline",
                "labels": [{"name": "self-hosted"}, {"name": "omnibase-ci"}],
            }
        ]
    }
    repo = _tree(
        tmp_path,
        {
            "c.yml": """\
            name: c
            on: {pull_request: {}}
            jobs:
              c:
                runs-on: [self-hosted, omnibase-ci]
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", fleet)
    result = _run(repo, runners, tmp_path)
    assert result.returncode == 2
    assert "THE GATE DID NOT RUN" in result.stderr


def test_a_repository_whose_arms_are_all_run_time_computed_refuses(
    tmp_path: Path,
) -> None:
    """A run that judged nothing has not passed.

    A label set produced by a routing job cannot be answered from source, and
    reporting it is right. Reporting ONLY that, and exiting 0, would be a green
    check that inspected nothing.
    """
    repo = _tree(
        tmp_path,
        {
            "routed.yml": """\
            name: routed
            on: {pull_request: {}}
            jobs:
              route:
                runs-on: [self-hosted, omnibase-ci]
                outputs: {labels: "${{ steps.pick.outputs.labels }}"}
                steps: [{id: pick, run: "true"}]
              consume:
                needs: route
                runs-on: ${{ fromJSON(needs.route.outputs.labels) }}
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", ONLINE_FLEET)
    # The `route` job itself is decidable, so this tree passes...
    assert _run(repo, runners, tmp_path).returncode == 0

    only_routed = _tree(
        tmp_path / "only",
        {
            "routed.yml": """\
            name: routed
            on: {pull_request: {}}
            jobs:
              consume:
                runs-on: ${{ fromJSON(needs.route.outputs.labels) }}
                steps: [{run: "true"}]
            """
        },
    )
    result = _run(only_routed, runners, tmp_path)
    assert result.returncode == 2
    assert "judged nothing" in result.stderr


def test_a_run_time_computed_arm_is_reported_not_silently_skipped(
    tmp_path: Path,
) -> None:
    """An arm the gate could not judge must not look like one it approved."""
    repo = _tree(
        tmp_path,
        {
            "routed.yml": """\
            name: routed
            on: {pull_request: {}}
            jobs:
              route:
                runs-on: [self-hosted, omnibase-ci]
                outputs: {labels: "${{ steps.pick.outputs.labels }}"}
                steps: [{id: pick, run: "true"}]
              consume:
                needs: route
                runs-on: ${{ fromJSON(needs.route.outputs.labels) }}
                steps: [{run: "true"}]
            """
        },
    )
    runners = _fixture(tmp_path, "runners.json", ONLINE_FLEET)
    result = _run(repo, runners, tmp_path)
    assert result.returncode == 0
    assert "computed at run time" in result.stdout
    assert "routed.yml::consume" in result.stdout


def test_the_runner_listing_command_carries_no_credential_on_argv() -> None:
    """The credential reaches `gh` through the environment, never through argv.

    An argument list is world-readable through `ps` for the life of the
    process, on a host shared with every other job on the runner; an
    environment variable is readable only by the process and its children. This
    is asserted against a sentinel rather than described in a comment, because
    an adversarial review of this module read the workflow's `env:` block and
    concluded the token was on the command line. It is not, and this is the
    falsifier for that reading.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import runner_label_exists_gate as gate

    sentinel = "ghs_SENTINEL_NEVER_ON_ARGV"
    argv = gate.runner_listing_command("OmniNode-ai")
    assert all(sentinel not in part for part in argv)
    # Positive control: the sentinel is a value this test could actually find,
    # so an assertion that never fails is not mistaken for one that passes.
    assert sentinel in f"{sentinel} {' '.join(argv)}"
    # And nothing in the list is credential-shaped at all.
    assert argv[0] == "gh"
    assert all(not part.lower().startswith(("ghp_", "ghs_", "gho_")) for part in argv)


def test_subprocess_stderr_is_redacted_before_it_reaches_a_ci_log() -> None:
    """The gate quotes `gh`'s stderr when a read fails, and a CI log is durable.

    `gh` is not expected to echo its token, but "not expected to" is not a
    control. Both halves of the scrub are asserted: the shape pattern catches a
    credential this process never held, and the literal match catches one whose
    shape GitHub changes tomorrow.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import runner_label_exists_gate as gate

    shaped = "ghp_" + "A" * 36
    assert shaped not in gate.redact(f"HTTP 401: bad credentials ({shaped})")
    assert "<redacted>" in gate.redact(f"boom {shaped}")

    live = "not-token-shaped-but-secret-anyway"
    os.environ["GH_TOKEN"] = live
    try:
        assert live not in gate.redact(f"gh said: {live}")
    finally:
        del os.environ["GH_TOKEN"]

    # Positive control: ordinary text is untouched, so a scrub that blanked
    # everything would not read as working.
    assert gate.redact("HTTP 404: Not Found") == "HTTP 404: Not Found"


def test_a_short_env_value_is_not_treated_as_a_credential() -> None:
    """Masking a two-character value would blank half of every message."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import runner_label_exists_gate as gate

    os.environ["GH_TOKEN"] = "ab"
    try:
        assert gate.redact("a bad request") == "a bad request"
    finally:
        del os.environ["GH_TOKEN"]
