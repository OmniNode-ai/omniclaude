# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21484: the model menu lists only models the developer's key can call.

After the OMN-21465 probe landed, the menu printed the usable and throttled
models and then a "Not offered" list the developer cannot pick and does not need
(standup 2026-10-28). The rows are still worth having for diagnosis, so they go
to the onboarding log instead of the screen.

The provider is stubbed by the OMN-21465 harness; no real provider is called.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.skills.test_onboarding_model_probe_omn21465 import (
    DEPRECATED,
    FUNCTIONS,
    KEY,
    NOT_FOUND,
    SCRIPT,
    _catalogue,
    _function,
    _provider,
)

pytestmark = pytest.mark.unit

MENU = f'key_models openai "{KEY}"; rc=$?; echo "rc=$rc"; echo "---"\n'


def _run_with_log(
    tmp_path: Path, catalogue: Path, script: str, log: Path
) -> tuple[str, str]:
    """Run the menu with the real log() writing to `log`, and say() printing only.

    The OMN-21465 harness stubs say() as a bare printer with LOG=/dev/null, which
    cannot tell a screen row from a logged one. Here the two are separate: say()
    goes to stdout and log() goes to the file, exactly as lab-onboarding.sh wires
    them.
    """
    funcs = "\n".join(_function(f) for f in FUNCTIONS)
    prelude = (
        "set -uo pipefail\n"
        + _function("in_list", SCRIPT)
        + _function("drop_model", SCRIPT)
        + f"LOG={log}; TAB=$(printf '\\t'); MODELS='openai gemini'; SKIPPED=''\n"
        + _function("log", SCRIPT)
        + "say() { printf '%s\\n' \"$*\"; }\n"
        "ram_gb() { echo 16; }\n"
        'provider_label() { case "$1" in openai) echo OpenAI ;; *) echo "$1" ;; esac; }\n'
        'set_result() { RESULT="$2"; }\n'
        "CHOSEN_OPENAI=''; CHOSEN_GEMINI=''; CHOSEN_OPENROUTER=''; CHOSEN_OLLAMA=''\n"
        "MODEL_LIST=''; MODEL_LIST_ERR=''; RECOMMENDED=''; REC_BASIS=''\n"
        "WORKSPACE=/nonexistent; CATALOGUE_REL=omnimarket/x.yaml\n"
    )
    done = subprocess.run(
        ["/bin/bash", "-c", f"{prelude}{funcs}\n{script}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "ONBOARD_TEST_CATALOGUE": str(catalogue),
        },
    )
    assert done.returncode == 0, done.stderr
    return done.stdout, log.read_text() if log.exists() else ""


def test_model_menu_no_not_offered_section(tmp_path: Path) -> None:
    """AC1: the menu prints usable and throttled models only, with no not-offered
    heading and no not-offered rows.

    AC2: the not-offered model ids and their reasons are still in the onboarding
    log, so a failed pick can be diagnosed afterwards.
    """
    models = ["gpt-4.1", "gpt-4.1-nano", "gpt-4o-2024-05-13", "gpt-4o-mini"]
    chat = {
        "gpt-4.1-nano": (404, DEPRECATED),
        "gpt-4o-2024-05-13": (404, NOT_FOUND),
        "gpt-4o-mini": (429, {"error": {"message": "Rate limit reached"}}),
    }
    log = tmp_path / "run.log"
    with _provider(models, chat) as served:
        cat = _catalogue(tmp_path, served["url"], [])
        out, logged = _run_with_log(
            tmp_path,
            cat,
            MENU + 'choose_models openai <<< "1,2"\necho "chosen=$CHOSEN_OPENAI"',
            log,
        )
    menu = out.split("---")[1]

    # The usable and throttled models are still offered, and still numbered.
    numbered = re.findall(r"^\s+\d+\) (\S+)", menu, re.M)
    assert numbered == ["gpt-4.1", "gpt-4o-mini"]
    assert "gpt-4o-mini  (busy just now, HTTP 429)" in menu

    # AC1: no heading and no rows for what the key could not call.
    assert "Not offered" not in menu
    assert "✗ gpt-4.1-nano" not in menu
    assert "✗ gpt-4o-2024-05-13" not in menu
    # and the ids do not reach the screen at all, under any wording
    assert "gpt-4.1-nano" not in menu
    assert "gpt-4o-2024-05-13" not in menu

    # AC2: both unusable ids, with the provider's reason, are in the log.
    assert "gpt-4.1-nano" in logged
    assert "gpt-4o-2024-05-13" in logged
    assert "has been deprecated" in logged
    assert "The model does not exist" in logged

    # The developer's pick still resolves against the offered list.
    assert "chosen=gpt-4.1 gpt-4o-mini" in out


def test_model_menu_no_not_offered_section_when_every_model_answers(
    tmp_path: Path,
) -> None:
    """AC1, the negative control: with nothing unusable the menu is unchanged, so
    the assertion above is testing the section and not an empty provider."""
    models = ["gpt-4.1", "gpt-4o-mini"]
    log = tmp_path / "run.log"
    with _provider(models, {}) as served:
        cat = _catalogue(tmp_path, served["url"], [])
        out, logged = _run_with_log(
            tmp_path,
            cat,
            MENU + 'choose_models openai <<< "1"\necho "chosen=$CHOSEN_OPENAI"',
            log,
        )
    menu = out.split("---")[1]
    numbered = re.findall(r"^\s+\d+\) (\S+)", menu, re.M)
    assert numbered == ["gpt-4.1", "gpt-4o-mini"]
    assert "Not offered" not in menu
    assert "could not call" not in logged
