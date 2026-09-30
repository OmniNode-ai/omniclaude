# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20138: omniclaude's Contract Compliance Check fails closed on a missing contract.

Before this ticket the job read ``contracts/<ticket>.yaml`` from the same
change-control checkout that pins the checker code (7352cb2d, 2026-07-12), so
every contract created after that date was absent and the pinned runner's
missing-contract branch printed a warning and exited 0 with nothing executed
(omnibase_infra#4325, job 109722692581; ported to omniclaude under OMN-20138). The job now mirrors omnibase_core
(OMN-18157): the checker stays pinned, the contracts are read at the commit the
PR's evidence reference resolves to, and a ticket with no contract there fails
before any check runs. Ported from omnibase_core
tests/unit/scripts/ci/test_contract_compliance_evidence_binding.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPO_ROOT / "scripts/ci/resolve_contract_compliance_evidence.py"
RUNNER = REPO_ROOT / "scripts/ci/run_contract_compliance_with_evidence.py"
CLASSIFIER_MODULE = "scripts.ci.classify_contract_compliance_scope"


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """A deterministic gh stub; its behavior is selected through GH_CASE."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
args="$*"
case "${GH_CASE:-}" in
  valid)
    if [[ "$args" == *"pr view 7 --repo OmniNode-ai/omniclaude --json body"* ]]; then
      printf '%s\\n' '{"body":"Evidence-Source: OCC#99"}'
    elif [[ "$args" == *"pr view 99 --repo OmniNode-ai/onex_change_control"* ]]; then
      printf '%s\\n' '{"state":"OPEN","headRefOid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","mergeCommit":null}'
    else
      echo "unexpected gh invocation: $args" >&2; exit 8
    fi
    ;;
  missing)
    printf '%s\\n' '{"body":"No evidence source"}'
    ;;
  malformed)
    printf '%s\\n' '{"body":"Evidence-Source: not-a-reference!"}'
    ;;
  closed)
    if [[ "$args" == *"--json body"* ]]; then
      printf '%s\\n' '{"body":"Evidence-Source: OCC#99"}'
    else
      printf '%s\\n' '{"state":"CLOSED","headRefOid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","mergeCommit":null}'
    fi
    ;;
  unresolved-push)
    echo 'gh unavailable' >&2; exit 1
    ;;
  *)
    echo "unknown GH_CASE=${GH_CASE:-}" >&2; exit 9
    ;;
esac
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return bindir


def _env(fake_bin: Path, **values: str) -> dict[str, str]:
    """A hermetic environment: the gh stub first, then only the tools it needs."""
    tool_dirs = sorted(
        {
            str(Path(found).parent)
            for found in (shutil.which("bash"), shutil.which("env"))
            if found is not None
        }
    )
    env = {"PATH": os.pathsep.join([str(fake_bin), *tool_dirs, "/usr/bin", "/bin"])}
    env.update(values)
    return env


def _resolve(
    tmp_path: Path, fake_bin: Path, *, case: str, event: str = "pull_request"
) -> subprocess.CompletedProcess[str]:
    output = tmp_path / "github-output"
    return subprocess.run(
        [
            sys.executable,
            str(RESOLVER),
            "--repo",
            "OmniNode-ai/omniclaude",
            "--event-name",
            event,
            "--commit-sha",
            "b" * 40,
            "--pr-number",
            "7" if event == "pull_request" else "",
            "--github-output",
            str(output),
        ],
        env=_env(fake_bin, GH_CASE=case),
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_evidence_source_resolves_an_immutable_data_sha(
    tmp_path: Path, fake_bin: Path
) -> None:
    result = _resolve(tmp_path, fake_bin, case="valid")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text(encoding="utf-8") == (
        "pr_number=7\nocc_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    )


def test_missing_or_malformed_evidence_source_fails_without_fallback(
    tmp_path: Path, fake_bin: Path
) -> None:
    for case in ("missing", "malformed"):
        result = _resolve(tmp_path, fake_bin, case=case)
        assert result.returncode == 1
        assert "evidence" in result.stderr.lower()


def test_closed_unmerged_occ_reference_fails(tmp_path: Path, fake_bin: Path) -> None:
    result = _resolve(tmp_path, fake_bin, case="closed")
    assert result.returncode == 1
    assert "require OPEN or MERGED" in result.stderr


def test_unavailable_push_and_merge_group_pr_resolution_fail(
    tmp_path: Path, fake_bin: Path
) -> None:
    for event in ("push", "merge_group"):
        result = _resolve(tmp_path, fake_bin, case="unresolved-push", event=event)
        assert result.returncode == 1
        assert "resolution failed" in result.stderr


def _make_checker(tmp_path: Path) -> Path:
    checker = tmp_path / "checker"
    module = checker / "src/onex_change_control/scripts"
    module.mkdir(parents=True)
    for package in (
        checker / "src/onex_change_control/__init__.py",
        checker / "src/onex_change_control/scripts/__init__.py",
    ):
        package.write_text("", encoding="utf-8")
    (module / "contract_compliance_check.py").write_text(
        "def _extract_ticket_id(pr_number, repo):\n    return 'OMN-18157'\n",
        encoding="utf-8",
    )
    script = checker / "scripts/ci/run_contract_compliance_check.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    allowlist = checker / "scripts/ci/dod_runner_legacy_allowlist.txt"
    allowlist.write_text("", encoding="utf-8")
    return checker


def _runner_command(checker: Path, evidence: Path, workspace: Path) -> list[str]:
    return [
        sys.executable,
        str(RUNNER),
        "--pr",
        "7",
        "--repo",
        "OmniNode-ai/omniclaude",
        "--checker-dir",
        str(checker),
        "--evidence-contracts-dir",
        str(evidence),
        "--workspace",
        str(workspace),
        "--legacy-allowlist",
        str(checker / "scripts/ci/dod_runner_legacy_allowlist.txt"),
        "--deferred-record",
        str(checker.parent / "deferred/record.json"),
    ]


def test_missing_data_contract_fails_before_uv_runner(
    tmp_path: Path, fake_bin: Path
) -> None:
    checker = _make_checker(tmp_path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    log = tmp_path / "uv.log"
    uv = fake_bin / "uv"
    uv.write_text(f"#!/usr/bin/env bash\nprintf invoked > {log}\n", encoding="utf-8")
    uv.chmod(0o755)
    result = subprocess.run(
        _runner_command(checker, evidence, tmp_path),
        env=_env(fake_bin),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "lacks the resolved ticket contract" in result.stderr
    assert not log.exists()


def test_valid_evidence_invokes_pinned_runner_with_data_and_workspace(
    tmp_path: Path, fake_bin: Path
) -> None:
    checker = _make_checker(tmp_path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "OMN-18157.yaml").write_text("schema_version: '1'\n", encoding="utf-8")
    log = tmp_path / "uv.log"
    uv = fake_bin / "uv"
    uv.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$PWD|$*\" > {log}\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    workspace = tmp_path / "product"
    workspace.mkdir()
    result = subprocess.run(
        _runner_command(checker, evidence, workspace),
        env=_env(fake_bin),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    invocation = log.read_text(encoding="utf-8")
    assert str(checker) in invocation
    assert f"--contracts-dir {evidence}" in invocation
    assert f"--workspace {workspace}" in invocation
    # OMN-18157: the pinned runner runs through the test_passes deferral driver.
    assert "scripts/ci/defer_test_passes_driver.py" in invocation
    assert (
        f"--deferred-record {tmp_path / 'deferred/record.json'} -- --pr 7" in invocation
    )


def test_a_contract_present_only_after_the_checker_pin_is_read_from_evidence(
    tmp_path: Path, fake_bin: Path
) -> None:
    """The omnibase_infra#4325 shape: the checker checkout has no contracts dir
    entry for the ticket, the evidence checkout does, and the runner is pointed
    at the evidence copy rather than passing on the checker's absence."""
    checker = _make_checker(tmp_path)
    (checker / "contracts").mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "OMN-18157.yaml").write_text("schema_version: '1'\n", encoding="utf-8")
    log = tmp_path / "uv.log"
    uv = fake_bin / "uv"
    uv.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {log}\n", encoding="utf-8"
    )
    uv.chmod(0o755)
    result = subprocess.run(
        _runner_command(checker, evidence, tmp_path),
        env=_env(fake_bin),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    invocation = log.read_text(encoding="utf-8")
    assert f"--contracts-dir {evidence}" in invocation
    assert f"--contracts-dir {checker / 'contracts'}" not in invocation


def test_an_unresolvable_ticket_fails_closed(tmp_path: Path, fake_bin: Path) -> None:
    checker = _make_checker(tmp_path)
    module = checker / "src/onex_change_control/scripts/contract_compliance_check.py"
    module.write_text(
        "def _extract_ticket_id(pr_number, repo):\n    return None\n", encoding="utf-8"
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    result = subprocess.run(
        _runner_command(checker, evidence, tmp_path),
        env=_env(fake_bin),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "could not resolve an OMN ticket" in result.stderr


# --- the one declared no-contract case: a ticketless dependency-bot bump -------


def _classify(tmp_path: Path, **kw: str) -> tuple[int, str, str]:
    output = tmp_path / "classify-output"
    output.write_text("", encoding="utf-8")
    args = {
        "event_name": "pull_request",
        "pr_author": "dependabot[bot]",
        "pr_title": "build(deps): update uvicorn requirement",
        "pr_head_ref": "dependabot/pip/uvicorn-0.55.0",
    }
    args.update(kw)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            CLASSIFIER_MODULE,
            "--event-name",
            args["event_name"],
            "--pr-author",
            args["pr_author"],
            "--pr-title",
            args["pr_title"],
            "--pr-head-ref",
            args["pr_head_ref"],
            "--github-output",
            str(output),
        ],
        cwd=REPO_ROOT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, output.read_text(encoding="utf-8"), result.stdout


def test_a_ticketless_dependency_bot_bump_is_the_declared_exemption(
    tmp_path: Path,
) -> None:
    code, output, stdout = _classify(tmp_path)
    assert code == 0
    assert output == "exempt=true\n"
    assert "dependency-bot" in stdout


@pytest.mark.parametrize(
    "override",
    [
        # a human author with a bump title must carry a ticket
        {"pr_author": "a-human-author"},
        # a bot PR a lane retitled with a ticket is judged against that ticket
        {"pr_title": "build(deps): OMN-17427 bump pyjwt"},
        # a ticket in the head ref counts the same way the producers read it
        {"pr_head_ref": "deps/OMN-17427"},
        # a bot that is not one of the two dependency bots is not exempt
        {"pr_author": "github-actions[bot]"},
        # push and merge_group carry no author or title: never exempt
        {"event_name": "push"},
        {"event_name": "merge_group"},
        # an unresolved context admits nothing
        {"pr_title": ""},
        {"pr_author": ""},
    ],
)
def test_every_other_pull_request_is_evaluated(
    tmp_path: Path, override: dict[str, str]
) -> None:
    code, output, _ = _classify(tmp_path, **override)
    assert code == 0
    assert output == "exempt=false\n"
