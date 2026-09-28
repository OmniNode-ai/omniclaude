# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Machine-pin rules of ``.github/workflows/ban-hardcoded-runner-ip.yml`` (OMN-19895).

Operator rulings 2026-09-28T01:58:06Z ("it's a problem if checks are reliant on
a specific machine") and 01:58:17Z ("chain of responders right?"). The reusable
check gained a step that refuses four shapes of machine pin in every workflow
file, with no annotation escape and no allowlist.

Each rule is proven here on a planted violation (the step must exit 1 and name
the file and the rule) and on its nearest innocent neighbour (the step must
exit 0), by executing the workflow's own step body against a throwaway tree.
The planted values are generic: no real lab address or host name is written.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ban-hardcoded-runner-ip.yml"
STEP = "Reject machine pins in workflow files (OMN-19895)"


def _step_script() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in doc["jobs"]["ban-hardcoded-runner-ip"]["steps"]:
        if step.get("name") == STEP:
            return str(step["run"])
    raise AssertionError(f"step {STEP!r} not found")


def _scan(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "probe.yml").write_text(body, encoding="utf-8")
    return subprocess.run(
        ["bash", "-c", _step_script()],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        check=False,
    )


def _dotted(*parts: str) -> str:
    """Build a dotted literal from parts, so no private address is written as
    one token in this file: this repository's own IP gates scan tests/."""
    return ".".join(parts)


_CLASS_A_HOST = _dotted("10", "20", "30", "40")
_CLASS_B_HOST = _dotted("172", "20", "0", "9")
_CLASS_C_HOST = _dotted("192", "168", "7", "7")

# (rule tag, planted violation)
PLANTED = (
    ("MP1", "    runs-on: [self-hosted, omnibase-verify, host-77]\n"),
    ("MP1", "    runs-on: [self-hosted, host-lab-a]\n"),
    ("MP1", '          LABELS: \'["self-hosted","host-77"]\'\n'),
    ("MP2", '          test "$(hostname)" = lab-box\n'),
    ("MP2", '          if [ "`hostname`" != "lab-box" ]; then exit 1; fi\n'),
    ("MP2", "    if: runner.name == 'lab-box-runner-1'\n"),
    ("MP2", '          assert socket.gethostname() == "lab-box"\n'),
    ("MP2", '          [ "${RUNNER_NAME}" = "lab-box-runner-1" ]\n'),
    ("MP3", "          curl http://" + _CLASS_A_HOST + ":8085/health\n"),
    ("MP3", "          BROKER: " + _CLASS_B_HOST + ":19092\n"),
    ("MP3", '          if [[ "$HOST" == "' + _CLASS_C_HOST + '" ]]; then\n'),
    (
        "MP4",
        "          find / -xdev -path /home/someone/lane -prune -o -name .git -print\n",  # local-path-ok: planted fixture
    ),
    ("MP4", "          rg --exclude '/data/lab-lane/*' secret\n"),
    ("MP4", "          find / -not -path '/srv/lane-202/*' -name .git\n"),
)


@pytest.mark.unit
@pytest.mark.parametrize(("rule", "line"), PLANTED)
def test_machine_pin_planted_violation_is_rejected(
    tmp_path: Path, rule: str, line: str
) -> None:
    result = _scan(tmp_path, "name: probe\njobs:\n  j:\n" + line)
    assert result.returncode == 1, result.stdout + result.stderr
    assert ".github/workflows/probe.yml:4" in result.stdout
    assert f"[{rule} " in result.stdout


# Innocent neighbours: each is one step away from a planted pin and must pass.
INNOCENT = (
    "    runs-on: ${{ fromJSON(vars.LAB_PROBE_RUNS_ON_JSON) }}\n",
    "    runs-on: [self-hosted, omnibase-ci]\n",
    "      - id: host-paths\n",
    "    name: host-sysctls\n",
    "    # runs-on: [self-hosted, host-77]  (history, in a comment)\n",
    '          echo "hostname: $(hostname)"\n',
    '          test "$(whoami)" = ghrunner\n',
    '          ALLOW: "' + _dotted("10", "20", "0", "0") + '/16"\n',
    "          version: " + _dotted("10", "2", "3") + "\n",
    '          for d in /home/*; do [ "$d" = "$HOME" ] && continue; done\n',
    "          find . -name node_modules -prune -o -print\n",
    "          url: ${{ vars.LAB_LANES_JSON }}\n",
)


@pytest.mark.unit
@pytest.mark.parametrize("line", INNOCENT)
def test_machine_pin_innocent_neighbour_passes(tmp_path: Path, line: str) -> None:
    result = _scan(tmp_path, "name: probe\njobs:\n  j:\n" + line)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
def test_machine_pin_annotation_is_no_escape(tmp_path: Path) -> None:
    """The IP rule's annotation escape does not extend to the machine-pin rules."""
    result = _scan(
        tmp_path,
        "name: probe\njobs:\n  j:\n"
        "    runs-on: [self-hosted, host-77]  # onex-allow-internal-ip\n",
    )
    assert result.returncode == 1, result.stdout


@pytest.mark.unit
def test_machine_pin_scan_covers_the_whole_workflow_tree(tmp_path: Path) -> None:
    """A pin already on the default branch is still a pin: the step scans every
    workflow file, not only the ones a pull request changed."""
    script = _step_script()
    assert "git diff" not in script
    assert 'rglob("*")' in script


@pytest.mark.unit
def test_machine_pin_this_repository_is_clean() -> None:
    """Positive control on real input: omniclaude's own workflows pass, so a
    red elsewhere is the other repository's pin, not the scanner's noise."""
    result = subprocess.run(
        ["bash", "-c", _step_script()],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
