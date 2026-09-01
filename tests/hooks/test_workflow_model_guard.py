# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Background-agent model guard: the checker and the registered hook (OMN-17499).

Two layers are tested, and both are load-bearing for different reasons.

The **checker** cases pin the parsing. The originating forensics pass wrote a
regex first; it reported 131 of 131 ``agent()`` calls as missing ``model:``
when a structural count over the same corpus finds 38. A regex cannot tell an options object from a
prompt that happens to contain the characters ``model:``, and it cannot follow
a multi-line object or a nested one. Every one of those specific confusions has
a case below, including the exact false positive the spec named.

The **hook** case runs the registered script end to end as a subprocess. That
is not redundant with the checker cases: OMN-8928 is the counterexample this
whole plugin's canary harness exists for -- its Python returned a correct
``{"decision": "block"}`` and the registered hook still exited 0, because
``error-guard.sh`` installs an EXIT trap that converts a non-zero exit to 0 and
that script never called ``trap - EXIT``. A unit test on the decision core
would have passed. Only running the command the harness runs tells the two
apart.

Fixtures under ``fixtures/workflow_model_guard/`` are verbatim ``agent()``
calls lifted out of the dead 2026-09-01 session's script corpus -- real
prompts, real template literals, real ``${}`` substitutions, real apostrophes
and braces inside prose. Synthetic fixtures would test the scanner against the
shapes its author already thought of.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_GUARD_PY = _HOOKS_DIR / "lib" / "workflow_model_guard.py"
_HOOK_SCRIPT = _HOOKS_DIR / "scripts" / "pre_tool_use_agent_model_guard.sh"
_HOOKS_JSON = _HOOKS_DIR / "hooks.json"
_FIXTURES = Path(__file__).parent / "fixtures" / "workflow_model_guard"

#: Generous. The hook shells out to Python; a guard that cannot answer inside
#: this is itself a finding.
_TIMEOUT_S = 120


def _load_guard() -> ModuleType:
    """Load the decision core by path, not by package name.

    The hook itself runs the file as a plain script from the plugin cache,
    where no ``plugins`` package exists (the OMN-16983 lesson). Loading it the
    same way here keeps the test honest about what actually runs.
    """
    spec = importlib.util.spec_from_file_location("workflow_model_guard", _GUARD_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_GUARD = _load_guard()
ALLOWLIST: frozenset[str] = _GUARD.load_allowlist()


def _check(source: str) -> list[Any]:
    return list(_GUARD.check_workflow_script(source, ALLOWLIST, filename="case.js"))


# ---------------------------------------------------------------------------
# The shipped policy
# ---------------------------------------------------------------------------


def test_shipped_allowlist_is_exactly_the_three_background_models() -> None:
    assert set(ALLOWLIST) == {"opus", "sonnet", "haiku"}


def test_shipped_allowlist_has_no_inherit_escape_hatch() -> None:
    """An inherited model is the defect, so no spelling of it may pass.

    The originating spec proposed ``model: 'inherit'`` as a visible-in-the-diff
    opt-out. It is deliberately absent: the incident was 41 agents running on
    an inherited model, and a sanctioned spelling for that is a sanctioned
    incident.
    """
    assert "inherit" not in ALLOWLIST
    assert "fable" not in ALLOWLIST


def test_allowlist_is_read_from_config_not_hardcoded(tmp_path: Path) -> None:
    override = tmp_path / "allowlist.json"
    override.write_text(json.dumps({"allowed_models": ["haiku"]}), encoding="utf-8")
    assert _GUARD.load_allowlist(override) == frozenset({"haiku"})


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ("{}", "no allowed_models key"),
        ('{"allowed_models": []}', "empty list would refuse every dispatch"),
        ('{"allowed_models": ["opus", ""]}', "blank entry"),
        ('{"allowed_models": "opus"}', "not a list"),
        ("not json at all", "unparseable"),
    ],
)
def test_malformed_allowlist_raises_rather_than_defaulting(
    tmp_path: Path, payload: str, why: str
) -> None:
    """No silent default. A guard that cannot read its own policy refuses."""
    bad = tmp_path / "bad.json"
    bad.write_text(payload, encoding="utf-8")
    with pytest.raises(_GUARD.AllowlistError):
        _GUARD.load_allowlist(bad)


def test_missing_allowlist_file_raises(tmp_path: Path) -> None:
    with pytest.raises(_GUARD.AllowlistError):
        _GUARD.load_allowlist(tmp_path / "absent.json")


# ---------------------------------------------------------------------------
# Parsing: the cases a regex gets wrong
# ---------------------------------------------------------------------------


def test_multiline_options_object_with_model_passes() -> None:
    """The exact false positive the spec named.

    The forensics pass's first-draft regex looked for ``model:`` on the same
    line as the closing of the call and so reported every multi-line options
    object as missing. This is the shape that has to pass.
    """
    source = """
const r = await agent(`do a thing`, {
  label: 'multi-line',
  phase: 'Land',
  schema: SCHEMA,
  model: 'opus',
})
"""
    assert _check(source) == []


def test_nested_options_object_with_model_passes() -> None:
    source = (
        "await agent(`x`, { label: 'nested', model: 'sonnet', "
        "schema: { type: 'object', properties: { a: { type: 'string' } } } })"
    )
    assert _check(source) == []


def test_model_key_nested_inside_a_schema_is_not_the_call_model() -> None:
    """``model`` deep inside ``schema`` is a JSON-schema property, not a choice."""
    source = (
        "await agent(`x`, { label: 'nested-miss', "
        "schema: { type: 'object', properties: { model: { type: 'string' } } } })"
    )
    findings = _check(source)
    assert len(findings) == 1
    assert "no model: key" in findings[0].reason
    assert findings[0].label == "nested-miss"


def test_model_supplied_by_a_variable_fails() -> None:
    """Not a literal, so not verifiable before dispatch. Refused, not guessed."""
    source = "const MODEL = 'opus'\nawait agent(`x`, { label: 'var', model: MODEL })"
    findings = _check(source)
    assert len(findings) == 1
    assert "not a quoted string literal" in findings[0].reason
    assert "MODEL" in findings[0].reason


def test_model_built_by_concatenation_fails() -> None:
    source = "await agent(`x`, { label: 'concat', model: 'op' + 'us' })"
    findings = _check(source)
    assert len(findings) == 1
    assert "not a quoted string literal" in findings[0].reason


def test_fable_fails_and_the_message_quotes_the_offending_value() -> None:
    """The banned model, named in the refusal so the author sees what they wrote."""
    source = "await agent(`x`, { label: 'fable-call', model: 'fable' })"
    findings = _check(source)
    assert len(findings) == 1
    assert "'fable'" in findings[0].reason
    assert "not an allowed background model" in findings[0].reason
    assert "haiku, opus, sonnet" in findings[0].reason
    assert findings[0].label == "fable-call"


def test_model_only_inside_the_prompt_string_fails() -> None:
    """``model: 'opus'`` in the prompt text is not a model choice.

    This is the regex's signature failure in the other direction: the
    characters are present in the file, on the same line, and mean nothing.
    """
    source = (
        "await agent(`Write a doc that says model: 'opus' somewhere.`, "
        "{ label: 'prompt-only' })"
    )
    findings = _check(source)
    assert len(findings) == 1
    assert "no model: key" in findings[0].reason


def test_agent_call_written_inside_a_prompt_is_not_a_call_site() -> None:
    source = (
        "await agent(`Do not call agent({ label: 'x' }) yourself.`, "
        "{ label: 'quoted-agent', model: 'haiku' })"
    )
    assert _check(source) == []


def test_commented_out_call_is_ignored_and_the_real_one_is_not() -> None:
    source = (
        "// await agent(`x`, { label: 'commented', model: 'opus' })\n"
        "await agent(`y`, { label: 'real' })"
    )
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].label == "real"
    assert findings[0].line == 2


def test_meta_phases_model_is_informational_only() -> None:
    """``meta.phases[].model`` describes UI phases, not where an agent runs.

    A file whose phase metadata names a banned model but whose every agent()
    call names an allowed one is clean: the per-call model is what decides
    where the work executes.
    """
    source = (
        "export const meta = { name: 'x', phases: [{ title: 'A', model: 'fable' }] }\n"
        "await agent(`x`, { label: 'ok', model: 'opus' })"
    )
    assert _check(source) == []


def test_nested_template_substitution_does_not_desynchronise_the_scan() -> None:
    source = (
        "await agent(`a ${ `b ${c}` } d`, { label: 'nested-tmpl', model: 'sonnet' })"
    )
    assert _check(source) == []


def test_options_object_that_spreads_another_value_fails() -> None:
    """Nothing static can say whether the spread carried a model. So: refuse."""
    source = "await agent(`x`, { ...base, label: 'spread' })"
    findings = _check(source)
    assert len(findings) == 1
    assert "spreads another value" in findings[0].reason


def test_call_with_no_options_object_fails() -> None:
    findings = _check("await agent(`x`)")
    assert len(findings) == 1
    assert "no options object" in findings[0].reason


def test_options_argument_that_is_not_an_object_literal_fails() -> None:
    findings = _check("await agent(`x`, opts)")
    assert len(findings) == 1
    assert "not an object literal" in findings[0].reason


def test_double_quoted_model_passes() -> None:
    assert _check('await agent("x", { label: "dq", model: "haiku" })') == []


def test_line_numbers_point_at_the_offending_call() -> None:
    source = "\n\n\nawait agent(`x`, { label: 'late' })\n"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 4
    assert "line 4" in findings[0].render()


# ---------------------------------------------------------------------------
# Real snippets from the 2026-09-01 corpus
# ---------------------------------------------------------------------------


def _fixtures(prefix: str) -> list[Path]:
    found = sorted(_FIXTURES.glob(f"{prefix}_*.js"))
    assert len(found) == 3, (
        f"expected 3 {prefix} fixtures from the real corpus, found {len(found)}: "
        f"{[p.name for p in found]!r}"
    )
    return found


@pytest.mark.parametrize("path", _fixtures("offending"), ids=lambda p: p.name)
def test_real_offending_snippet_is_refused(path: Path) -> None:
    findings = _GUARD.check_workflow_script(
        path.read_text(encoding="utf-8"), ALLOWLIST, filename=path.name
    )
    assert findings, f"{path.name} omits model: in the real corpus but was not flagged"
    assert all("model" in finding.reason for finding in findings)


@pytest.mark.parametrize("path", _fixtures("passing"), ids=lambda p: p.name)
def test_real_passing_snippet_is_allowed(path: Path) -> None:
    findings = _GUARD.check_workflow_script(
        path.read_text(encoding="utf-8"), ALLOWLIST, filename=path.name
    )
    assert findings == [], (
        f"{path.name} names an allowed model in the real corpus but was flagged: "
        f"{[f.render() for f in findings]!r}"
    )


# ---------------------------------------------------------------------------
# Agent tool
# ---------------------------------------------------------------------------


def test_agent_fork_is_refused_outright() -> None:
    """A fork resumes the parent conversation, so it always inherits its model.

    There is no value of ``model`` that makes the choice explicit for a fork,
    which is why this is a refusal of the subagent type rather than a check on
    a field.
    """
    findings = _GUARD.check_agent_input(
        {"subagent_type": "fork", "description": "continue the lane"}, ALLOWLIST
    )
    assert len(findings) == 1
    assert "fork" in findings[0].reason
    assert "inherits the parent" in findings[0].reason


def test_agent_fork_is_refused_even_when_it_names_an_allowed_model() -> None:
    findings = _GUARD.check_agent_input(
        {"subagent_type": "fork", "model": "opus", "description": "x"}, ALLOWLIST
    )
    assert len(findings) == 1
    assert "fork" in findings[0].reason


def test_agent_with_allowed_model_passes() -> None:
    assert (
        _GUARD.check_agent_input(
            {
                "subagent_type": "general-purpose",
                "model": "sonnet",
                "description": "do a thing",
            },
            ALLOWLIST,
        )
        == []
    )


def test_agent_with_no_model_fails() -> None:
    findings = _GUARD.check_agent_input(
        {"subagent_type": "general-purpose", "description": "do a thing"}, ALLOWLIST
    )
    assert len(findings) == 1
    assert "declares no model" in findings[0].reason
    assert findings[0].label == "do a thing"


def test_agent_with_disallowed_model_fails() -> None:
    findings = _GUARD.check_agent_input(
        {"subagent_type": "general-purpose", "model": "fable"}, ALLOWLIST
    )
    assert len(findings) == 1
    assert "'fable'" in findings[0].reason


# ---------------------------------------------------------------------------
# The registered hook, end to end
# ---------------------------------------------------------------------------


def _registered_command() -> str:
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for group in data["hooks"]["PreToolUse"]
        for hook in group["hooks"]
    ]
    matching = [c for c in commands if c.endswith("/" + _HOOK_SCRIPT.name)]
    assert matching, (
        f"hooks.json does not register {_HOOK_SCRIPT.name}. This test FAILS "
        "rather than skips on purpose: an unregistered enforcement hook is "
        "exactly the OMN-13244 defect, and a skipped check reports it as green."
    )
    return matching[0]


def _run_hook(
    payload: dict[str, Any], tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(_HOOKS_DIR.parent),
        "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        # Pinned, not inherited: mode.sh resolves "lite" for a CI runner's cwd,
        # and the question here is whether the hook enforces, not what mode the
        # host happens to be in.
        "OMNICLAUDE_MODE": "full",
    }
    return subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_S,
        check=False,
    )


def test_hook_script_is_registered_and_executable() -> None:
    assert _registered_command().endswith("/" + _HOOK_SCRIPT.name)
    assert os.access(_HOOK_SCRIPT, os.X_OK), f"{_HOOK_SCRIPT} is not executable"


def test_jq_is_available() -> None:
    """The hook renders its decision with ``jq -n``, as every sibling guard does.

    Asserted rather than skipped around: without jq the block payload never
    reaches stdout, the script exits non-zero, and ``error-guard.sh`` converts
    that to exit 0 -- a silent fail-OPEN. If this fails, the environment cannot
    run any of this plugin's guards, which is the finding.
    """
    assert shutil.which("jq") is not None


def test_registered_hook_blocks_a_workflow_with_no_model(tmp_path: Path) -> None:
    """The OMN-8928 shape: a correct verdict whose exit code is swallowed
    enforces nothing. Assert the exit code and the payload, from the command
    the harness actually runs."""
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {
                "script": "await agent(`do a thing`, { label: 'e2e-canary' })\n"
            },
        },
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2, (
        f"expected a block (exit 2), got {result.returncode}.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert '"decision": "block"' in combined
    assert "background agent model not chosen explicitly" in combined
    assert "e2e-canary" in combined
    assert "line 1" in combined
    assert "opus" in combined and "sonnet" in combined and "haiku" in combined


def test_registered_hook_blocks_an_agent_fork(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "fork", "description": "e2e-fork"},
        },
        tmp_path,
    )
    assert result.returncode == 2
    assert '"decision": "block"' in result.stdout
    assert "fork" in result.stdout


def test_registered_hook_passes_a_clean_workflow_silently(tmp_path: Path) -> None:
    """Silence on the allow path is deliberate: the Workflow payload carries the
    entire script body, and echoing it back would copy every prompt into the
    hook output stream for no benefit."""
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {
                "script": "await agent(`do a thing`, { label: 'ok', model: 'sonnet' })\n"
            },
        },
        tmp_path,
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_registered_hook_ignores_other_tools(tmp_path: Path) -> None:
    """A bug in this guard must never be able to brick unrelated tool traffic."""
    result = _run_hook(
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}, tmp_path
    )
    assert result.returncode == 0
    assert '"decision": "block"' not in result.stdout


def test_registered_hook_fails_closed_on_malformed_payload(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        input="this is not json",
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "CLAUDE_PLUGIN_ROOT": str(_HOOKS_DIR.parent),
            "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
            "OMNICLAUDE_MODE": "full",
        },
        timeout=_TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 2
    assert '"decision": "block"' in result.stdout
    assert "not readable JSON" in result.stdout


def test_registered_hook_fails_closed_on_unreadable_script_path(
    tmp_path: Path,
) -> None:
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {"scriptPath": str(tmp_path / "absent" / "nope.js")},
        },
        tmp_path,
    )
    assert result.returncode == 2
    assert '"decision": "block"' in result.stdout
    assert "could not be read" in result.stdout


def test_registered_hook_reads_a_script_from_script_path(tmp_path: Path) -> None:
    """``scriptPath`` is the shape a Workflow dispatch uses on resume, where the
    script is on disk rather than inline."""
    script = tmp_path / "on-disk.js"
    script.write_text(
        "await agent(`x`, { label: 'from-disk', model: 'fable' })\n", encoding="utf-8"
    )
    result = _run_hook(
        {"tool_name": "Workflow", "tool_input": {"scriptPath": str(script)}}, tmp_path
    )
    assert result.returncode == 2
    assert "from-disk" in result.stdout
    assert "fable" in result.stdout
