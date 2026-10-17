# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Every shipped launchd plist template parses with plistlib once rendered. [OMN-17427]

Read on the operator Mac 2026-10-17: the installed ai.omninode.canonical-clone-sync and
ai.omninode.transcript-s3-archive plists failed plistlib with "not well-formed (invalid
token)" at line 27 col 53 and line 9 col 68. Both templates carried a double hyphen inside
their header comment, which XML 1.0 forbids and `plutil -lint` accepts, so nothing strict
ever read them. These tests render every template under scripts/launchd/ and parse it, and
check that the tick-bundle installer refuses a rendered plist a strict reader cannot parse.
"""

from __future__ import annotations

import plistlib
import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES = sorted((_REPO_ROOT / "scripts" / "launchd").glob("*.plist"))
_INSTALLER = _REPO_ROOT / "scripts" / "tick-bundle-install.sh"
_PLACEHOLDER = re.compile(r"__[A-Z_]+__")


@pytest.mark.unit
@pytest.mark.parametrize("template", _TEMPLATES, ids=lambda p: p.name)
def test_rendered_template_parses_with_plistlib(template: Path) -> None:
    rendered = _PLACEHOLDER.sub("1", template.read_text(encoding="utf-8"))
    payload = plistlib.loads(rendered.encode("utf-8"))
    assert payload["Label"] == template.stem


def _run_verify(rendered: str) -> subprocess.CompletedProcess[str]:
    source = _INSTALLER.read_text(encoding="utf-8")
    body = source.split("\nverify_well_formed() {", 1)[1].split("\n}\n", 1)[0]
    script = f'verify_well_formed() {{{body}\n}}\nverify_well_formed label "$1"'
    return subprocess.run(
        ["/bin/bash", "-c", script, "verify", rendered],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
    )


_PLIST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<!-- usage: tool {flag} -->\n'
    '<plist version="1.0"><dict><key>Label</key><string>x</string></dict></plist>\n'
)


@pytest.mark.unit
def test_installer_refuses_a_double_hyphen_comment() -> None:
    result = _run_verify(_PLIST.format(flag="--only"))
    assert result.returncode != 0
    assert "not well-formed" in result.stderr


@pytest.mark.unit
def test_installer_passes_a_well_formed_plist() -> None:
    """Positive control: the same plist without the double hyphen passes."""
    result = _run_verify(_PLIST.format(flag="only"))
    assert result.returncode == 0, result.stderr
