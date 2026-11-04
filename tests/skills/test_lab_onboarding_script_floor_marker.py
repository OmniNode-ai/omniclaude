# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22180: a machine onboarding just set up is not below the proven floor.

The clean macOS VM walk of 2026-11-02 ran a bare ``onex delegate`` after phase 3
and was refused with exit 3: no floor marker. Only ``onex-host-reconcile``, a
step the guide never names, cleared it. The onboarding script owns the marker:
phase 3 stamps ``<workspace>/.onex-workspace-floor.json`` from the dispatch venv
that answered its own delegation, and the guide names no reconcile step.

These tests run the script's own ``phase3`` against a simulated fresh
workspace, then ask the question the onex wrapper asks (is the marker there, and
does it name the installed build). A mutation of the script that drops the stamp
is the positive control: the same check must refuse it with the recorded text.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins" / "onex" / "skills" / "_bin" / "lab-onboarding.sh"
GUIDE = REPO / "plugins" / "onex" / "ONBOARDING.md"
FIXTURES = REPO / "tests" / "fixtures" / "onboarding_walk_2026_11_02"

OMNIMARKET_COMMIT = "8fecf3caec1062e4d7fd4557f5d0bcf809deb344"
FLOOR_NAME = ".onex-workspace-floor.json"
# The script's own functions that phase 3 runs; everything else is stubbed.
PHASE3_FUNCTIONS = (
    "phase3",
    "delegate_hello",
    "stamp_proven_floor",
    "receipt_field",
    "set_result",
    "result_of",
    "passed_models",
    "record_model_status",
)
STAMP_STEP = (
    '  step "stamp the proven workspace floor" stamp_proven_floor ||\n'
    '    phase_fail "see the log; the proven floor could not be written from the dispatch venv"\n'
)

# The wrapper's stamp contract, reduced to what the wrapper reads: it records the
# commit of the omnimarket installed in the venv, as direct_url.json names it.
FAKE_MOVEMENT = """\
import json, sys
from pathlib import Path

args = sys.argv[1:]
site = Path(args[args.index("--site-packages") + 1])
output = Path(args[args.index("--output") + 1])
workspace_root = args[args.index("--omni-home") + 1]
direct = next(site.glob("omnimarket-*.dist-info")) / "direct_url.json"
commit = json.loads(direct.read_text())["vcs_info"]["commit_id"]
output.write_text(json.dumps({
    "schema": "onex.workspace.floor.v1",
    "workspace_root": workspace_root,
    "omnimarket_commit": commit,
}))
print(f"floor stamped: {output}")
"""


def _function_text(script: str, name: str) -> str:
    lines = script.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    if lines[start].rstrip().endswith("}") and lines[start].count("{") == lines[
        start
    ].count("}"):
        return lines[start] + "\n"
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1]) + "\n"


def _refusal(workspace: Path, template: str) -> str:
    """The wrapper's verdict for a workspace, in the recorded refusal's words."""
    floor = workspace / FLOOR_NAME
    if not floor.is_file():
        return template.replace("<workspace>", str(workspace))
    document = json.loads(floor.read_text())
    if document.get("omnimarket_commit") != OMNIMARKET_COMMIT:
        return (
            "this workspace is below the proven floor: the marker names another build"
        )
    return ""


class FreshWorkspace:
    """A just-installed machine: dispatch venv built, clones in place, no marker."""

    def __init__(self, root: Path, script_text: str) -> None:
        self.home = root / "home"
        self.workspace = root / "workspace"
        self.run_dir = root / "run"
        for directory in (self.home, self.workspace, self.run_dir):
            directory.mkdir()
        venv = self.workspace / ".onex-dispatch-venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").symlink_to(sys.executable)
        site = venv / "lib" / "python3.13" / "site-packages"
        dist_info = site / "omnimarket-0.4.316.dist-info"
        dist_info.mkdir(parents=True)
        (dist_info / "direct_url.json").write_text(
            json.dumps({"vcs_info": {"vcs": "git", "commit_id": OMNIMARKET_COMMIT}})
        )
        receipt = self.run_dir / "receipt.json"
        receipt.write_text(json.dumps({"endpoint": "provider", "model": "m"}) + "\n")
        entrypoint = venv / "bin" / "onex"
        entrypoint.write_text(
            f"#!{sys.executable}\nimport sys\n"
            'print(\'{"status": "success"}\')\n'
            f"print('delegate artifacts: {receipt}', file=sys.stderr)\n"
        )
        entrypoint.chmod(0o755)
        scripts = self.workspace / "omnibase_infra" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "reconcile_verify_movement.py").write_text(FAKE_MOVEMENT)
        fragment = "".join(_function_text(script_text, n) for n in PHASE3_FUNCTIONS)
        self.fragment = root / "fragment.sh"
        self.fragment.write_text(fragment)
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "WORKSPACE": str(self.workspace),
            "LOG": str(self.run_dir / "log"),
            "STATUS": str(self.run_dir / "status"),
        }

    @property
    def marker(self) -> Path:
        return self.workspace / FLOOR_NAME

    def run_phase3(self) -> subprocess.CompletedProcess[str]:
        prologue = """
            set -uo pipefail
            say() { printf '%s\\n' "$*"; }
            log() { :; }
            retry() { shift; "$@"; }
            retry_capture() { shift; CAPTURED="$("$@")"; }
            step() { FAILED_STEP="$1"; shift; "$@"; }
            phase_start() { :; }
            phase_pass() { printf 'PASS %s\\n' "$*"; }
            phase_fail() { printf 'FAIL %s: %s\\n' "$FAILED_STEP" "$*"; exit 1; }
            is_done() { return 1; }
            rerun_note() { :; }
            dispatch_venv_current() { return 0; }
            link_onex() { return 0; }
            onex_run() { case "${1:-}" in --version) echo "onex 0.0.0" ;; esac; return 0; }
            models_cmd() { return 0; }
            has_model() { return 1; }
            retire_lab_model_overrides() { :; }
            prepare_local_url() { :; }
            setup_model() { set_result "$1" "pass:fixture-model"; }
            result_line() { echo "$1 ok"; }
            provider_label() { echo "$1"; }
            count_words() { echo "$#"; }
            labels() { echo "$*"; }
            cause_of() { cat; }
            last_log_lines() { :; }
            place_local_url_on_ladder() { return 0; }
            FAILED_STEP=""; LAST_ERR=""; OLLAMA_HEADLESS=0
            MODELS="gemini"; SKIPPED=""
            RES_GEMINI=""; RES_OPENROUTER=""; RES_OPENAI=""; RES_OLLAMA=""; RES_LOCAL=""; RES_COMPAT=""
            source "$1"
            phase3
        """
        return subprocess.run(
            ["/bin/bash", "-c", prologue, "harness", str(self.fragment)],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )


def _refusal_template() -> str:
    return (FIXTURES / "refusal.txt").read_text().strip()


def test_phase3_leaves_the_floor_marker_naming_the_installed_build(
    tmp_path: Path,
) -> None:
    fresh = FreshWorkspace(tmp_path, SCRIPT.read_text())
    assert not fresh.marker.exists()
    result = fresh.run_phase3()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
    assert fresh.marker.is_file(), "phase 3 passed but left no floor marker"
    document = json.loads(fresh.marker.read_text())
    assert document["omnimarket_commit"] == OMNIMARKET_COMMIT
    assert document["workspace_root"] == str(fresh.workspace)
    # No hand edit after the run: the wrapper's question is answered as it stands.
    assert _refusal(fresh.workspace, _refusal_template()) == ""


def test_a_stamp_that_cannot_be_written_fails_phase3_instead_of_passing(
    tmp_path: Path,
) -> None:
    fresh = FreshWorkspace(tmp_path, SCRIPT.read_text())
    (
        fresh.workspace / "omnibase_infra" / "scripts" / "reconcile_verify_movement.py"
    ).write_text("import sys\nsys.exit(1)\n")
    result = fresh.run_phase3()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL stamp the proven workspace floor" in result.stdout
    assert "PASS" not in result.stdout
    assert not fresh.marker.exists()


def test_walk_2026_11_02_refusal_is_reproduced_by_a_script_that_never_stamps(
    tmp_path: Path,
) -> None:
    """Positive control for the check above, built from the recorded refusal."""
    walk = json.loads((FIXTURES / "walk.json").read_text())
    assert walk["exit_code"] == 3
    assert (FIXTURES / walk["refusal_file"]).is_file()
    broken_text = SCRIPT.read_text()
    assert STAMP_STEP in broken_text, "the stamp step moved; update this control"
    broken_text = broken_text.replace(STAMP_STEP, "")
    assert "stamp_proven_floor ||" not in broken_text
    (tmp_path / "broken").mkdir()
    (tmp_path / "fixed").mkdir()
    broken_ws = FreshWorkspace(tmp_path / "broken", broken_text)
    assert broken_ws.run_phase3().returncode == 0  # phase 3 itself still passes
    refusal = _refusal(broken_ws.workspace, _refusal_template())
    assert refusal.startswith("this workspace is below the proven floor")
    assert f"no floor marker at {broken_ws.workspace}/{FLOOR_NAME}" in refusal
    fixed_ws = FreshWorkspace(tmp_path / "fixed", SCRIPT.read_text())
    assert fixed_ws.run_phase3().returncode == 0
    assert _refusal(fixed_ws.workspace, _refusal_template()) == ""
    # The walk recovered by a step the guide never named; the guide now says
    # phase 3 writes the marker and names no recovery step.
    guide = GUIDE.read_text()
    recovery = walk["recovered_by"].split(",")[0]
    assert recovery not in guide, "the guide names the step the walk needed"
    assert re.search(r"phase 3[^\n]*" + re.escape(FLOOR_NAME), guide, re.I), (
        "the guide does not say phase 3 writes the floor marker"
    )


def test_guide_and_script_agree_on_who_creates_the_marker() -> None:
    """Exactly one of two shapes holds, never neither."""
    script = SCRIPT.read_text()
    guide = GUIDE.read_text()
    script_creates = (
        len(re.findall(r'^  step "[^"]+" stamp_proven_floor \|\|$', script, re.M)) == 1
        and f'--output "$WORKSPACE/{FLOOR_NAME}"' in script
    )
    guide_runs_reconcile = bool(
        re.search(r"^\s*(?:[-*]|\d+\.)?\s*`?onex-host-reconcile", guide, re.M)
    )
    guide_mentions_reconcile = "onex-host-reconcile" in guide
    assert script_creates or guide_runs_reconcile, "neither creates the marker"
    if script_creates:
        # Shape one: the script creates it, so the guide has no reconcile step.
        assert not guide_mentions_reconcile, (
            "the script creates the floor marker, yet the guide names a reconcile step"
        )
        assert FLOOR_NAME in guide, "the guide never says the script leaves the marker"
        assert re.search(r"phase 3[^\n]*" + re.escape(FLOOR_NAME), guide, re.I), (
            "the guide does not attribute the marker to phase 3"
        )
