# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Every launchd plist template must render to XML that plistlib parses (OMN-17427).

XML 1.0 forbids a double hyphen inside a comment. launchd and plistlib both
refuse such a file, so a template whose header comment quotes a command-line
flag installs a LaunchAgent that cannot load. The installer also expands
placeholders into the XML text, so a value holding an ampersand or an angle
bracket must be escaped or the rendered file stops being well-formed.

The render step under test is ``render_plist`` in scripts/tick-bundle-install.sh,
extracted from the script and run by bash, not a Python copy of it.
"""

from __future__ import annotations

import plistlib
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO_ROOT / "scripts" / "tick-bundle-install.sh"
_TEMPLATES = sorted((_REPO_ROOT / "scripts" / "launchd").glob("*.plist"))

_OMNI_HOME = "/srv/Omni Lab/registry"
_HOME = "/Users/sample"

# A value with an ampersand and a bracket proves the renderer escapes XML; the
# pipe and backslash prove it does not trip over the sed delimiter or its
# replacement syntax.
_AWKWARD_OMNI_HOME = "/srv/Omni & Co <lab>/registry|root\\x"
_AWKWARD_HOME = "/Users/sample&user"

# Placeholders other installers expand (hook-emit-drainer, hook-process-canary).
# tick-bundle-install.sh does not own them, so the test fills them with plain
# absolute paths after its own render.
_OTHER_PLACEHOLDERS = {
    "__PYTHON__": "/usr/bin/python3",
    "__ROOT__": "/opt/sample/omniclaude",
    "__STATE_DIR__": "/var/tmp/sample-state",
    "__INTERNAL_HOME__": "/opt/sample/internal",
    "__LEDGER__": "/var/tmp/sample-ledger.jsonl",
    "__UV_DIR__": "/opt/sample/uv",
}


def _render_function() -> str:
    """The body of render_plist, taken verbatim from the installer script."""
    text = _INSTALLER.read_text(encoding="utf-8")
    match = re.search(r"^render_plist\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert match, "render_plist() not found in tick-bundle-install.sh"
    return match.group(0)


def _render(template: Path, registry: str = _OMNI_HOME, home: str = _HOME) -> str:
    script = f'{_render_function()}\nrender_plist "$1"\n'
    result = subprocess.run(
        ["bash", "-c", script, "render", str(template)],
        env={
            "PATH": "/usr/bin:/bin",
            "OMNI_HOME_RESOLVED": registry,
            "HOME": home,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _fill_other_placeholders(rendered: str) -> str:
    for placeholder, value in _OTHER_PLACEHOLDERS.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def test_templates_are_found() -> None:
    assert len(_TEMPLATES) >= 14, "scripts/launchd/*.plist glob found too few templates"


@pytest.mark.parametrize("template", _TEMPLATES, ids=lambda p: p.name)
def test_rendered_plist_parses(template: Path) -> None:
    rendered = _fill_other_placeholders(_render(template))
    assert "__OMNI_HOME__" not in rendered
    assert "__HOME__" not in rendered
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["Label"] == template.stem


@pytest.mark.parametrize("template", _TEMPLATES, ids=lambda p: p.name)
def test_no_double_hyphen_inside_a_comment(template: Path) -> None:
    text = template.read_text(encoding="utf-8")
    for match in re.finditer(r"<!--(.*?)-->", text, re.S):
        body = match.group(1)
        line = text.count("\n", 0, match.start(1)) + 1
        assert "--" not in body and not body.endswith("-"), (
            f"{template.name}: comment at line {line} holds a double hyphen"
        )


@pytest.mark.parametrize("template", _TEMPLATES, ids=lambda p: p.name)
def test_rendered_plist_parses_with_xml_special_characters_in_paths(
    template: Path,
) -> None:
    rendered = _fill_other_placeholders(
        _render(template, registry=_AWKWARD_OMNI_HOME, home=_AWKWARD_HOME)
    )
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["Label"] == template.stem


def test_substituted_values_round_trip_through_xml_escaping() -> None:
    template = _TEMPLATES[0].parent / "ai.omninode.merge-sweep.plist"
    parsed = plistlib.loads(
        _render(template, registry=_AWKWARD_OMNI_HOME, home=_AWKWARD_HOME).encode(
            "utf-8"
        )
    )
    program = parsed["ProgramArguments"][0]
    assert program.startswith(_AWKWARD_OMNI_HOME + "/"), program
    assert "&amp;" not in repr(parsed), "the escape was applied twice"
