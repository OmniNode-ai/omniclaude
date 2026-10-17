# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-17427: the onboarding finish step runs only when its overlay key enables it.

The step is the dev-setup node's second Bash handler. The entrypoint loads it only
when ONEX_SKILL_OVERLAY_ROOTS was set, and the handler does nothing unless the
first ``<root>/node_onboarding/overlay.yaml`` sets ``finish_greeting_enabled`` to
true. Off, it asks nothing and creates nothing.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"
NODE = REPO / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
HANDLER = NODE / "handler_onboarding_finish.sh"
ASSETS = REPO / "plugins/onex/skills/_bin/assets/finish"

pytestmark = pytest.mark.unit


def test_node_declares_the_finish_handler_and_the_entrypoint_loads_its_bytes() -> None:
    contract = yaml.safe_load((NODE / "contract.yaml").read_text())
    finish = contract["metadata"]["finish_handler"]
    assert finish["language"] == "bash"
    assert NODE / finish["source"] == HANDLER
    fingerprint = finish["sha256_fingerprint"]
    assert (
        fingerprint.replace(":", "") == hashlib.sha256(HANDLER.read_bytes()).hexdigest()
    )
    load = re.search(
        r'load_onboarding_handler finish ([0-9a-f]{40}) "([0-9a-f:]+)"',
        SCRIPT.read_text(),
    )
    assert load
    assert load.group(2) == fingerprint
    for entrypoint in finish["entrypoints"]:
        assert re.search(rf"^{entrypoint}\(\) \{{", HANDLER.read_text(), re.M)
    subprocess.run(["/bin/bash", "-n", str(HANDLER)], check=True)


def test_the_handler_pins_the_clips_it_ships() -> None:
    text = HANDLER.read_text()
    for name, var in (
        ("welcome.wav", "FINISH_WELCOME_SHA256"),
        ("to-omninode.wav", "FINISH_CLOSE_SHA256"),
    ):
        pinned = re.search(rf'^{var}="([0-9a-f:]+)"', text, re.M)
        assert pinned
        assert (
            pinned.group(1).replace(":", "")
            == hashlib.sha256((ASSETS / name).read_bytes()).hexdigest()
        )


def test_the_entrypoint_calls_the_step_where_it_belongs() -> None:
    text = SCRIPT.read_text()
    # The roots are read before the inherited ONEX_* variables are unset.
    assert text.index(
        'FINISH_OVERLAY_ROOTS="${ONEX_SKILL_OVERLAY_ROOTS:-}"'
    ) < text.index('INHERITED_ENV=""')
    # The name is asked with the other questions, before preflight's verdict.
    assert text.index("|| finish_step prepare") < text.index(
        'say "  Will set up: $SELECTED"'
    )
    main = text[text.index("\nmain() {") :]
    assert (
        main.index("phase1\n")
        < main.index("finish_step start")
        < main.index("phase2\n")
    )
    assert main.index("result=COMPLETE") < main.index("finish_step play")


def _run(snippet: str, tmp_path: Path, roots: str) -> subprocess.CompletedProcess[str]:
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    stub = tmp_path / "stubbin"
    stub.mkdir(exist_ok=True)
    (stub / "id").write_text(
        '#!/bin/sh\n[ "$1" = -F ] && { echo "Ada Lovelace"; exit 0; }\nexit 1\n'
    )
    (stub / "id").chmod(0o755)
    prelude = (
        "say() { printf '%s\\n' \"$*\"; }\n"
        "os_name() { echo Darwin; }\n"
        "brew_bin() { :; }\n"
        f'IS_TTY=1; RUN_DIR="{run_dir}"; WORKSPACE="{tmp_path}/ws"\n'
        f'FINISH_OVERLAY_ROOTS="{roots}"\n'
        f'. "{HANDLER}"\n'
    )
    return subprocess.run(
        ["/bin/bash", "-c", prelude + snippet],
        env={"HOME": str(tmp_path / "home"), "PATH": f"{stub}:/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ('finish_greeting_enabled: "true"', "ON"),
        ("finish_greeting_enabled: true  # on", "ON"),
        ("finish_greeting_enabled: 'TRUE'", "ON"),
        ('finish_greeting_enabled: "false"', "OFF"),
        ("other_field: true", "OFF"),
        ('finish_greeting_enabled: "maybe"', "OFF"),
    ],
)
def test_only_true_enables_it(tmp_path: Path, field: str, expected: str) -> None:
    root = tmp_path / "overlays"
    (root / "node_onboarding").mkdir(parents=True)
    (root / "node_onboarding/overlay.yaml").write_text(field + "\n")
    result = _run(
        "finish_enabled && echo ON || echo OFF\n", tmp_path, f"{tmp_path}/none:{root}"
    )
    assert result.stdout.splitlines()[-1] == expected, result.stdout + result.stderr
    if "maybe" in field:
        assert 'must be "true" or "false", not \'maybe\'' in result.stdout


def test_the_first_root_with_the_overlay_decides(tmp_path: Path) -> None:
    for name, value in (("first", "false"), ("second", "true")):
        (tmp_path / name / "node_onboarding").mkdir(parents=True)
        (tmp_path / name / "node_onboarding/overlay.yaml").write_text(
            f'finish_greeting_enabled: "{value}"\n'
        )
    result = _run(
        "finish_enabled && echo ON || echo OFF\n",
        tmp_path,
        f"{tmp_path}/first:{tmp_path}/second",
    )
    assert result.stdout.strip() == "OFF"


@pytest.mark.parametrize("value", ["false", None])
def test_off_it_asks_builds_and_plays_nothing(
    tmp_path: Path, value: str | None
) -> None:
    root = tmp_path / "overlays"
    (root / "node_onboarding").mkdir(parents=True)
    if value is not None:
        (root / "node_onboarding/overlay.yaml").write_text(
            f'finish_greeting_enabled: "{value}"\n'
        )
    result = _run(
        "finish_step prepare; finish_step start; finish_step play\n"
        'echo "name=[$FINISH_NAME] pid=[$FINISH_PID]"\n',
        tmp_path,
        str(root),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "name=[] pid=[]\n"
    assert not list((tmp_path / "run").iterdir())
