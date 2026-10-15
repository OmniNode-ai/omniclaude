# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21087: onboarding on a machine that ran an earlier setup.

The run itself inherits none of an earlier setup's variables, a resumed run
binds the onboarding workspace before any phase, phase 3 checks the dispatch
venv before rebuilding it, and a failed model test prints the error that caused
it.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
_preflight = importlib.import_module("test_lab_onboarding_script_omn20150")
SCRIPT = _preflight.SCRIPT
_functions = _preflight._functions

pytestmark = pytest.mark.unit

LEFTOVER_ENV = {
    "OMNI_HOME": "/old/omni",
    "OMNIBASE_INTERNAL_PATH": "/old/omni/internal-clone",
    "ONEX_EVENT_BUS_TYPE": "kafka",
    "ONEX_LAB_TENANT_STATE_DIR": "/old/tenant",
    "ONEX_STATE_DIR": "/old/omni/.onex_state",
    "ONEX_DISPATCH_VENV": "/old/venv",
    "ONEX_CONTRACTS_DIR": "/old/contracts",
    "KAFKA_BOOTSTRAP_SERVERS": "lab:9092",
}


def _sourced(
    tmp_path: Path, snippet: str, **env: str
) -> subprocess.CompletedProcess[str]:
    """The whole script with its functions defined and main not run, then snippet."""
    body = SCRIPT.read_text()
    assert body.rstrip().endswith("\nmain")
    script = tmp_path / "sourced.sh"
    script.write_text(body.rstrip()[: -len("main")] + "\n" + snippet + "\n")
    (tmp_path / "run").mkdir(exist_ok=True)
    return subprocess.run(
        ["/bin/bash", str(script)],
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TMPDIR": str(tmp_path / "run") + "/",
            "ONBOARD_NOTIFY": "0",
            "ONBOARD_TEST_NO_USER_SHELL": "1",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_no_leftover_variable_reaches_the_run(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    result = _sourced(
        tmp_path,
        'echo "INHERITED=$INHERITED_ENV"; env | cut -d= -f1 | sort',
        **LEFTOVER_ENV,
    )
    assert result.returncode == 0, result.stderr
    names = set(result.stdout.splitlines())
    for name in LEFTOVER_ENV:
        assert name not in names, name
        assert name in result.stdout.split("INHERITED=", 1)[1].splitlines()[0]


def test_a_resumed_run_binds_the_workspace_before_any_phase(tmp_path: Path) -> None:
    """Phase 2 is skipped on resume; phase 3 must still run against this workspace."""
    (tmp_path / "home").mkdir()
    ws = tmp_path / "ws"
    stubs = "".join(f"phase{n}() {{ :; }}\n" for n in (0, 1, 2, 4, 5, 6))
    result = _sourced(
        tmp_path,
        stubs
        + 'phase3() { echo "P3 $OMNIBASE_PATH $ONEX_WORKSPACE_CONFIG_ROOT ${ONEX_STATE_DIR:-unset}"; }\n'
        + "main",
        OMNIBASE_PATH=str(ws),
        **LEFTOVER_ENV,
    )
    assert f"P3 {ws} {ws}/.onex/workspace-config unset" in result.stdout, (
        result.stdout + result.stderr
    )


def test_a_failed_model_test_prints_the_error_that_caused_it(tmp_path: Path) -> None:
    fake = tmp_path / "models"
    fake.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = default-model ]; then echo fixture-vendor/model; exit 0; fi\n'
        "cat >/dev/null\n"
        'echo "delegate artifacts (REFUSED -- refused_before_dispatch): /x" >&2\n'
        'echo "Error: lab tenant declaration /y/lab_run_hosts.yaml refused: '
        'expected one host row for omnibook, found 0" >&2\n'
        'echo \'{"provider": "openrouter", "status": "failed", '
        '"reason": "the test delegation exited with status 1"}\'\n'
    )
    fake.chmod(0o755)
    snippet = (
        f"LOG=/dev/null; RUN_DIR={tmp_path}; KEY_OPENROUTER=k; KEY_GEMINI=; KEY_OPENAI=\n"
        + _functions(
            "pending_key",
            "set_pending_key",
            "provider_label",
            "receipt_field",
            "set_result",
            "result_of",
            "result_line",
            "cause_of",
            "openrouter_default_model",
            "setup_model",
        )
        + f'\nmodels_cmd() {{ "{fake}" "$@"; }}\n'
        + "setup_model openrouter; result_line openrouter\n"
    )
    out = subprocess.run(
        ["/bin/bash", "-c", snippet], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == (
        "OpenRouter  ✗ the test delegation exited with status 1: lab tenant "
        "declaration /y/lab_run_hosts.yaml refused: expected one host row for "
        "omnibook, found 0"
    )


def test_a_resumed_phase_3_checks_the_venv_before_rebuilding_it() -> None:
    text = SCRIPT.read_text()
    phase3 = text.split("phase3() {", 1)[1].split("\n}", 1)[0]
    assert phase3.index("dispatch_venv_current") < phase3.index("--proven")
    check = text.split("dispatch_venv_current() {", 1)[1].split("\n}", 1)[0]
    assert "--check" in check and "--proven" not in check
