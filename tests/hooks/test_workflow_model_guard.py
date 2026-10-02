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
from typing import Any, Final

import pytest
import yaml

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
ROUTING: Any = _GUARD.load_routing()

# Dimension sums are chosen so that no R or J is 3 unless a case says so.
_ROUTE_B2 = (
    "ROUTE: band=B2 score=5 dims=S1A1R1V1N1C0J0 dest=codex model=sonnet effort=medium"
)
_ROUTE_B3 = (
    "ROUTE: band=B3 score=9 dims=S2A1R1V2N1C1J1 dest=lane model=sonnet effort=high"
)
_ROUTE_B4 = (
    "ROUTE: band=B4 score=14 dims=S2A2R2V2N2C2J2 dest=lane model=opus effort=high"
)
_ROUTE_B5 = (
    "ROUTE: band=B5 score=18 dims=S3A3R2V2N3C2J3 dest=lane model=opus effort=xhigh"
)


def _check(source: str) -> list[Any]:
    return list(_GUARD.check_workflow_script(source, ALLOWLIST, filename="case.js"))


def _check_routed(source: str) -> list[Any]:
    return list(
        _GUARD.check_workflow_script(
            source, ALLOWLIST, filename="case.js", routing=ROUTING
        )
    )


def _routed_call(route: str | None, model: str) -> str:
    body = f"{route}\\ndo a thing" if route else "do a thing"
    return f"await agent(`{body}`, {{ label: 'r', model: '{model}' }})\n"


# ---------------------------------------------------------------------------
# The shipped policy
# ---------------------------------------------------------------------------


def test_shipped_allowlist_is_exactly_the_two_background_models() -> None:
    assert set(ALLOWLIST) == {"opus", "sonnet"}


def test_shipped_allowlist_has_no_haiku() -> None:
    """Operator ruling OMN-17427: haiku is removed from background dispatch."""
    assert "haiku" not in ALLOWLIST


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
    override.write_text(json.dumps({"allowed_models": ["sonnet"]}), encoding="utf-8")
    assert _GUARD.load_allowlist(override) == frozenset({"sonnet"})


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
    assert "opus, sonnet" in findings[0].reason
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
        "{ label: 'quoted-agent', model: 'sonnet' })"
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
    assert _check('await agent("x", { label: "dq", model: "sonnet" })') == []


@pytest.mark.parametrize("model", ["sonnet", "opus"])
def test_workflow_agent_on_an_allowed_model_passes(model: str) -> None:
    assert _check(f"await agent(`x`, {{ label: 'ok', model: '{model}' }})") == []


@pytest.mark.parametrize("model", ["haiku", "claude-haiku-4-5-20251001"])
def test_workflow_agent_on_haiku_is_refused_and_says_it_is_removed(model: str) -> None:
    findings = _check(f"await agent(`x`, {{ label: 'h', model: '{model}' }})")
    assert len(findings) == 1
    assert "not an allowed background model" in findings[0].reason
    assert "haiku is removed" in findings[0].reason
    assert "onex delegate" in findings[0].reason


def test_line_numbers_point_at_the_offending_call() -> None:
    source = "\n\n\nawait agent(`x`, { label: 'late' })\n"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 4
    assert "line 4" in findings[0].render()


# ---------------------------------------------------------------------------
# Real snippets from the 2026-09-01 corpus
# ---------------------------------------------------------------------------


#: Fixture census, pinned so a fixture that vanishes fails the suite rather
#: than silently shrinking its coverage. ``passing`` gained one in the
#: OMN-17499 follow-up: pr-backlog-drain carries ``.replace(/'/g, '')`` inside
#: a ``${}`` substitution -- a real regular-expression literal containing a
#: quote -- and the first shipped revision refused it as ``<unparsed>``. It is
#: the only script in the 1895-script live corpus whose verdict the regex
#: tokeniser changes.
_FIXTURE_COUNTS: Final[dict[str, int]] = {"offending": 3, "passing": 4}


def _fixtures(prefix: str) -> list[Path]:
    found = sorted(_FIXTURES.glob(f"{prefix}_*.js"))
    expected = _FIXTURE_COUNTS[prefix]
    assert len(found) == expected, (
        f"expected {expected} {prefix} fixtures from the real corpus, found "
        f"{len(found)}: {[p.name for p in found]!r}"
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


def test_agent_with_opus_passes() -> None:
    assert (
        _GUARD.check_agent_input(
            {"subagent_type": "general-purpose", "model": "opus"}, ALLOWLIST
        )
        == []
    )


@pytest.mark.parametrize("model", ["haiku", "claude-haiku-4-5-20251001"])
def test_agent_on_haiku_is_refused_and_says_it_is_removed(model: str) -> None:
    findings = _GUARD.check_agent_input(
        {"subagent_type": "general-purpose", "model": model}, ALLOWLIST
    )
    assert len(findings) == 1
    assert "haiku is removed" in findings[0].reason
    assert "onex delegate" in findings[0].reason


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
    return str(matching[0])


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


def test_the_borrowed_mask_bit_gates_only_this_guard() -> None:
    """`PRE_TOOL_AGENT_DISPATCH_GATE` must remain a one-control switch.

    This guard borrows that bit because a dedicated one is not mintable in this
    repo: `EnumHookBit` lives in omnibase_core, all 60 default-mask ordinals are
    allocated, 60-62 are the disabled-by-default trio, and
    knowledge-base-internal `reference/hook-bitmask-bit-governance.md` rule 7 forbids ordinal 63 (the sign bit of a
    signed 64-bit integer) outright.

    The borrow is only honest while the bit's namesake script stays
    unregistered. If someone re-registers `pre_tool_use_agent_dispatch_gate.sh`,
    then `onex hooks disable PRE_TOOL_AGENT_DISPATCH_GATE` -- documented in this
    guard's own block message as the way to turn *this* guard off -- would
    silently disable two controls at once. That is precisely the quiet
    switch-mismatch the OMN-17020 inventory exists to refuse, so it fails here
    rather than being discovered from a hook that stopped firing.
    """
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    registered = {
        hook["command"].rsplit("/", 1)[-1]
        for group in data["hooks"].get("PreToolUse", [])
        for hook in group["hooks"]
    }
    assert "pre_tool_use_agent_dispatch_gate.sh" not in registered, (
        "pre_tool_use_agent_dispatch_gate.sh has been registered, so "
        "PRE_TOOL_AGENT_DISPATCH_GATE now gates two controls. Either give the "
        "model guard its own EnumHookBit (an omnibase_core change plus an "
        "architecture review per knowledge-base-internal reference/hook-bitmask-bit-governance.md rule 7), or move one of the "
        "two to a different bit. Do not leave two guards behind one switch."
    )


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
    assert "opus" in combined and "sonnet" in combined
    assert "onex delegate" in combined


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
                "script": (
                    f"await agent(`{_ROUTE_B3}\\ndo a thing`, "
                    "{ label: 'ok', model: 'sonnet' })\n"
                )
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


# ---------------------------------------------------------------------------
# Scanner desynchronisation (OMN-17499 follow-up)
#
# Every case below was ALLOWED (exit 0) by the first shipped revision of this
# guard, verified against the live registered hook before the fix. They are the
# whole reason the module now tokenises regular-expression literals: a scanner
# that cannot see a pattern reads its bytes as code, and the constructs a
# pattern legitimately contains -- an escaped slash, a quote, a backtick -- are
# exactly the constructs that blank the rest of a line or the rest of a file.
#
# The shipped docstring claimed this residual "yields an unresolvable_call
# finding -- it fails closed". That was true only when the desynchronisation
# landed INSIDE an argument list. When it landed before the call, the call
# stopped existing and the dispatch passed in silence.
# ---------------------------------------------------------------------------


def test_url_scheme_regex_does_not_hide_the_call_that_follows_it() -> None:
    """`\\/\\/` inside a pattern is a literal slash pair, not a line comment.

    The shipped scanner read it as `//`, blanked the remainder of the line,
    and with it the `agent(` token -- so `_call_sites` returned [] and the
    dispatch was allowed.
    """
    findings = _check(
        "const norm = (u) => u.replace(/^https?:\\/\\//, ''); "
        "agent('t', { label: 'after-regex' });\n"
    )
    assert len(findings) == 1, [f.render() for f in findings]
    assert findings[0].label == "after-regex"
    assert "no model" in findings[0].reason


def test_url_scheme_regex_does_not_hide_a_banned_model_on_the_same_line() -> None:
    """The same shape with an explicitly banned model still has to be caught."""
    findings = _check(
        "const re = /a\\/\\//; agent('t', { label: 'x', model: 'fable' });\n"
    )
    assert len(findings) == 1, [f.render() for f in findings]
    assert "'fable'" in findings[0].reason


def test_quote_inside_a_character_class_does_not_swallow_later_calls() -> None:
    """A quote inside a pattern is not a string delimiter.

    The shipped scanner opened a string at the `'` in the character class and
    closed it at the opening quote of a later argument, blanking BOTH calls in
    between. This is the more severe variant: it is not bounded to one line.
    """
    findings = _check(
        "const tok = str.split(/[^'\"]+/);\n"
        "agent('a', { label: 'one' });\n"
        "agent('b', { label: 'two' });\n"
    )
    assert [f.label for f in findings] == ["one", "two"], [f.render() for f in findings]
    assert [f.line for f in findings] == [2, 3]


def test_apostrophe_inside_a_regex_does_not_swallow_the_next_call() -> None:
    findings = _check("const m = /don't/;\nagent('a', { label: 'one' });\n")
    assert [f.label for f in findings] == ["one"], [f.render() for f in findings]


def test_backtick_inside_a_regex_does_not_swallow_the_rest_of_the_file() -> None:
    """A backtick in a pattern pushed a template frame in the shipped scanner,
    which then ran to end of file."""
    findings = _check("const m = /`/;\nagent('a', { label: 'one' });\n")
    assert [f.label for f in findings] == ["one"], [f.render() for f in findings]


def test_escaped_slash_and_character_class_do_not_terminate_a_pattern() -> None:
    """The two lexer rules the fix turns on, asserted directly on the mask."""
    masked = _GUARD._mask("const a = /[a/b]\\//; agent('t', { label: 'x' });\n").text
    assert "agent(" in masked, masked
    assert "[a/b]" not in masked, "pattern body must be blanked, not preserved"


def test_regex_inside_the_argument_list_is_parsed_rather_than_refused() -> None:
    """The shipped revision refused this as `<unparsed>`. It names a model.

    Verbatim shape from the live corpus (`.replace(/'/g, '')` inside a `${}`
    substitution); see the fixture of the same name.
    """
    findings = _check("agent('t', { label: 'x', re: /a\\/\\//, model: 'sonnet' });\n")
    assert findings == [], [f.render() for f in findings]


def test_division_is_not_mistaken_for_a_pattern() -> None:
    """The classifier has to keep arithmetic working, or every script with a
    `/` in it becomes a false block."""
    findings = _check(
        "const half = total / 2;\n"
        "const rate = (a + b) / 2;\n"
        "const each = items[0] / count;\n"
        "agent('t', { label: 'after-division' });\n"
    )
    assert [f.label for f in findings] == ["after-division"], [
        f.render() for f in findings
    ]
    assert findings[0].line == 4


def test_regex_after_a_keyword_is_a_pattern_not_a_division() -> None:
    findings = _check(
        "function f(s) { return /a'b/.test(s); }\nagent('t', { label: 'x' });\n"
    )
    assert [f.label for f in findings] == ["x"], [f.render() for f in findings]


def test_ambiguous_slash_after_a_paren_is_refused_not_guessed() -> None:
    """`)` ends a value AND a control head, so `/` after it is genuinely
    ambiguous. When the two readings disagree about the rest of the file, the
    guard refuses instead of picking one."""
    findings = _check("if (ok) /a'b\\/c/.test(s);\nagent('t', { label: 'x' });\n")
    assert len(findings) == 1, [f.render() for f in findings]
    assert findings[0].label == "<unparsed source>"
    assert "refuses rather than pick one" in findings[0].reason


def test_unterminated_string_refuses_the_whole_script() -> None:
    """A single-quoted string cannot carry a raw newline. One that appears to
    is proof the scan desynchronised, and a desynchronised scan is void."""
    findings = _check(
        "const s = 'oops;\nagent('t', { label: 'x', model: 'sonnet' });\n"
    )
    assert len(findings) == 1, [f.render() for f in findings]
    assert findings[0].label == "<unparsed source>"
    assert findings[0].line == 1


def test_unterminated_template_refuses_the_whole_script() -> None:
    findings = _check(
        "const s = `oops;\nagent('t', { label: 'x', model: 'sonnet' });\n"
    )
    assert len(findings) == 1, [f.render() for f in findings]
    assert findings[0].label == "<unparsed source>"


def test_unterminated_block_comment_refuses_the_whole_script() -> None:
    findings = _check("/* oops\nagent('t', { label: 'x', model: 'sonnet' });\n")
    assert len(findings) == 1, [f.render() for f in findings]
    assert findings[0].label == "<unparsed source>"


def test_a_desync_refuses_even_when_every_visible_call_is_clean() -> None:
    """The refusal is of the SCAN, not of the calls it happened to see. A mask
    that desynchronised cannot prove the absence of a call it never saw."""
    findings = _check(
        "agent('a', { label: 'clean', model: 'sonnet' });\nconst s = 'unterminated;\n"
    )
    assert len(findings) == 1
    assert findings[0].label == "<unparsed source>"


# ---------------------------------------------------------------------------
# The helper referenced without being called (OMN-17499 follow-up)
# ---------------------------------------------------------------------------


def test_agent_bound_to_another_name_is_refused() -> None:
    """`const a = agent; a('t', {...})` dispatched past the shipped guard.

    `_call_sites` matched the literal token `agent(`, so any other binding of
    the helper was invisible. This is deliberate-evasion only -- it cannot
    arise from the accidental omission the guard targets -- but a control that
    holds only against accidents is not a control, and nothing in the shipped
    artifacts said so.
    """
    findings = _check("const a = agent;\na('t', { label: 'aliased' });\n")
    assert len(findings) == 1, [f.render() for f in findings]
    assert "referenced here without being called" in findings[0].reason
    assert findings[0].line == 1


def test_agent_passed_as_a_value_is_refused() -> None:
    findings = _check("dispatchAll([agent, agent]);\n")
    assert len(findings) == 2, [f.render() for f in findings]
    assert all("without being called" in f.reason for f in findings)


def test_agent_destructured_out_of_an_object_is_refused() -> None:
    findings = _check("const { agent } = helpers;\n")
    assert len(findings) == 1, [f.render() for f in findings]
    assert "without being called" in findings[0].reason


def test_the_word_agent_in_a_prompt_is_still_not_a_reference() -> None:
    """The new rule must not fire on prose. Measured on the live corpus of
    1895 workflow scripts, no real script carries a non-call reference."""
    findings = _check(
        "agent(`tell the agent that agent orchestration is hard`, "
        "{ label: 'x', model: 'sonnet' });\n"
        "// the agent helper is documented here\n"
    )
    assert findings == [], [f.render() for f in findings]


def test_subagent_and_property_access_are_not_the_global_helper() -> None:
    findings = _check(
        "subagent('t', { label: 'a' });\nrunner.agent('t', { label: 'b' });\n"
    )
    assert findings == [], [f.render() for f in findings]


# ---------------------------------------------------------------------------
# script + scriptPath (OMN-17499 follow-up)
# ---------------------------------------------------------------------------


def test_both_script_and_script_path_are_checked(tmp_path: Path) -> None:
    """The shipped guard preferred the inline `script` and never opened the
    path, so a clean inline body was a cover for a dirty one on disk.

    Which of the two the harness would actually run is not knowable from
    inside a PreToolUse hook, and does not need to be: every body the call
    carries is checked.
    """
    script = tmp_path / "on-disk.js"
    script.write_text("agent('t', { label: 'on-disk' });\n", encoding="utf-8")
    sources = _GUARD._resolve_script_sources(
        {
            "script": "agent('t', { label: 'inline', model: 'sonnet' });\n",
            "scriptPath": str(script),
        }
    )
    assert [name for name, _ in sources] == ["<inline script>", str(script)]
    findings = [
        finding
        for name, source in sources
        for finding in _GUARD.check_workflow_script(source, ALLOWLIST, filename=name)
    ]
    assert [f.label for f in findings] == ["on-disk"], [f.render() for f in findings]


def test_neither_script_nor_script_path_raises(tmp_path: Path) -> None:
    with pytest.raises(_GUARD.AllowlistError):
        _GUARD._resolve_script_sources({})


def test_registered_hook_blocks_a_regex_hidden_call(tmp_path: Path) -> None:
    """End to end, through the command the harness runs. The checker returning
    a finding is not the same fact as the hook exiting 2 (OMN-8928)."""
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {
                "script": (
                    "const norm = (u) => u.replace(/^https?:\\/\\//, ''); "
                    "agent('t', { label: 'after-regex' });\n"
                )
            },
        },
        tmp_path,
    )
    assert result.returncode == 2, (
        f"expected a block, got {result.returncode}.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert '"decision": "block"' in result.stdout
    assert "after-regex" in result.stdout


def test_registered_hook_blocks_a_quote_in_a_character_class(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {
                "script": (
                    "const tok = str.split(/[^'\"]+/);\n"
                    "agent('a', { label: 'one' });\n"
                    "agent('b', { label: 'two' });\n"
                )
            },
        },
        tmp_path,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "one" in result.stdout and "two" in result.stdout


def test_registered_hook_blocks_an_aliased_dispatch(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {
                "script": "const a = agent;\na('t', { label: 'aliased' });\n"
            },
        },
        tmp_path,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "without being called" in result.stdout


def test_registered_hook_blocks_a_dirty_script_path_behind_a_clean_script(
    tmp_path: Path,
) -> None:
    script = tmp_path / "on-disk.js"
    script.write_text("agent('t', { label: 'on-disk' });\n", encoding="utf-8")
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {
                "script": "agent('t', { label: 'inline', model: 'sonnet' });\n",
                "scriptPath": str(script),
            },
        },
        tmp_path,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "on-disk" in result.stdout


# ---------------------------------------------------------------------------
# Routing contract: bands, dimensions and the ROUTE line (OMN-17427 W1, W2)
# ---------------------------------------------------------------------------


def test_shipped_routing_declares_the_seven_dimensions_and_six_bands() -> None:
    assert [d.key for d in ROUTING.dimensions] == list("SARVNCJ")
    assert all(d.max_value == 3 for d in ROUTING.dimensions)
    assert set(ROUTING.bands) == {"B0", "B1", "B1c", "B2", "B3", "B4", "B5"}
    assert ROUTING.bands["B2"].models == frozenset({"sonnet"})
    assert ROUTING.bands["B3"].models == frozenset({"sonnet"})
    assert ROUTING.bands["B4"].models == frozenset({"opus"})
    assert ROUTING.bands["B5"].models == frozenset({"opus"})
    assert ROUTING.bands["B5"].efforts == frozenset({"xhigh"})
    assert ROUTING.bands["B4"].timeout_s == 7200
    assert ROUTING.bands["B4"].max_concurrent == 5


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("bands"),
        lambda d: d.pop("dimensions"),
        lambda d: d["bands"].pop("B4"),
        lambda d: d["dimensions"].pop(),
        lambda d: d["bands"]["B4"].update(models="opus"),
        lambda d: d["bands"]["B4"].update(timeout_s=0),
        lambda d: d["hard_floors"][0].update(min_band="B9"),
    ],
)
def test_malformed_routing_raises_rather_than_defaulting(
    tmp_path: Path, mutate: Any
) -> None:
    data = yaml.safe_load(
        _GUARD.DEFAULT_ROUTING_CONTRACT_PATH.read_text(encoding="utf-8")
    )
    mutate(data)
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(_GUARD.AllowlistError):
        _GUARD.load_routing(bad)


def test_contract_parser_agrees_with_pyyaml_on_the_shipped_contract() -> None:
    path = _GUARD.DEFAULT_ROUTING_CONTRACT_PATH
    text = path.read_text(encoding="utf-8")
    assert _GUARD._parse_contract_yaml(text, path) == yaml.safe_load(text)


def test_allowlist_holds_only_allowed_models() -> None:
    data = json.loads(_GUARD.DEFAULT_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert set(data) == {"$comment", "allowed_models"}


@pytest.mark.parametrize(
    "text",
    [
        "a:\n\tb: 1\n",
        "a: 1\na: 2\n",
        "a: {b: 1}\n",
        "a: 'x'\n",
        "a: &anchor 1\n",
        "a: 1 # trailing\n",
        "a: [1, 2\n",
        "a:\n   b: 1\n",
        "  a: 1\n",
        "- 1\nb: 2\n",
        "",
    ],
)
def test_contract_parser_refuses_yaml_outside_its_subset(text: str) -> None:
    with pytest.raises(_GUARD.AllowlistError):
        _GUARD._parse_contract_yaml(text, Path("x.yaml"))


@pytest.mark.parametrize(
    ("route", "model"),
    [
        (_ROUTE_B2, "sonnet"),
        (_ROUTE_B3, "sonnet"),
        (_ROUTE_B4, "opus"),
        (_ROUTE_B5, "opus"),
    ],
)
def test_matching_route_passes(route: str, model: str) -> None:
    assert _check_routed(_routed_call(route, model)) == []


def test_b4_route_with_sonnet_model_is_refused() -> None:
    findings = _check_routed(
        _routed_call(_ROUTE_B4.replace("model=opus", "model=sonnet"), "sonnet")
    )
    assert len(findings) == 1
    assert "band B4" in findings[0].reason
    assert "sonnet" in findings[0].reason


def test_route_model_must_match_the_declared_model() -> None:
    findings = _check_routed(_routed_call(_ROUTE_B4, "sonnet"))
    assert len(findings) == 1
    assert "model=opus" in findings[0].reason


def test_missing_route_is_refused() -> None:
    findings = _check_routed(_routed_call(None, "sonnet"))
    assert len(findings) == 1
    assert "ROUTE" in findings[0].reason
    assert "missing" in findings[0].reason


def test_unparsable_route_is_refused() -> None:
    findings = _check_routed(_routed_call("ROUTE: band=B3 model=sonnet", "sonnet"))
    assert len(findings) == 1
    assert "unparsable" in findings[0].reason


def test_interpolated_route_is_refused_as_missing() -> None:
    source = "await agent(`${route}\\nx`, { label: 'r', model: 'sonnet' })\n"
    findings = _check_routed(source)
    assert len(findings) == 1
    assert "ROUTE" in findings[0].reason


def test_route_in_label_is_accepted() -> None:
    source = f"await agent(`do a thing`, {{ label: '{_ROUTE_B3}', model: 'sonnet' }})\n"
    assert _check_routed(source) == []


@pytest.mark.parametrize(
    ("dims", "score"),
    [("S1A1R3V1N1C1J1", 9), ("S1A1R1V1N1C1J3", 9), ("S0A0R3V0N0C0J0", 3)],
)
def test_floor_triggered_band_below_b4_is_refused(dims: str, score: int) -> None:
    route = (
        f"ROUTE: band=B3 score={score} dims={dims} dest=lane model=sonnet effort=high"
    )
    findings = _check_routed(_routed_call(route, "sonnet"))
    assert len(findings) == 1
    assert "hard floor" in findings[0].reason


def test_floor_triggered_b4_with_low_score_passes() -> None:
    route = (
        "ROUTE: band=B4 score=3 dims=S0A0R3V0N0C0J0 dest=lane model=opus effort=high"
    )
    assert _check_routed(_routed_call(route, "opus")) == []


def test_score_must_equal_the_sum_of_dims() -> None:
    route = _ROUTE_B3.replace("score=9", "score=10")
    findings = _check_routed(_routed_call(route, "sonnet"))
    assert len(findings) == 1
    assert "score" in findings[0].reason


def test_band_below_the_score_band_is_refused() -> None:
    route = _ROUTE_B4.replace("band=B4", "band=B3").replace(
        "model=opus", "model=sonnet"
    )
    findings = _check_routed(_routed_call(route, "sonnet"))
    assert len(findings) == 1
    assert "below" in findings[0].reason


def test_effort_must_be_in_the_band_set() -> None:
    route = _ROUTE_B5.replace("effort=xhigh", "effort=low")
    findings = _check_routed(_routed_call(route, "opus"))
    assert len(findings) == 1
    assert "effort" in findings[0].reason


@pytest.mark.parametrize("band", ["B0", "B1", "B1c"])
def test_non_model_band_cannot_dispatch_an_agent(band: str) -> None:
    route = f"ROUTE: band={band} score=2 dims=S1A1R0V0N0C0J0 dest=x model=sonnet effort=high"
    findings = _check_routed(_routed_call(route, "sonnet"))
    assert len(findings) == 1
    assert f"band {band}" in findings[0].reason


def test_agent_tool_requires_a_route_in_the_prompt() -> None:
    base = {"subagent_type": "general-purpose", "model": "sonnet", "description": "d"}
    missing = _GUARD.check_agent_input(base, ALLOWLIST, routing=ROUTING)
    assert len(missing) == 1 and "ROUTE" in missing[0].reason
    ok = _GUARD.check_agent_input(
        {**base, "prompt": f"{_ROUTE_B3}\nwork"}, ALLOWLIST, routing=ROUTING
    )
    assert ok == []
    bad = _GUARD.check_agent_input(
        {**base, "model": "sonnet", "prompt": _ROUTE_B4}, ALLOWLIST, routing=ROUTING
    )
    assert len(bad) == 1 and "model=opus" in bad[0].reason


def test_registered_hook_blocks_b4_route_with_sonnet_model(tmp_path: Path) -> None:
    route = _ROUTE_B4.replace("model=opus", "model=sonnet")
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {"script": _routed_call(route, "sonnet")},
        },
        tmp_path,
    )
    assert result.returncode == 2
    assert "band B4" in result.stdout


def test_registered_hook_blocks_a_missing_route(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {"script": _routed_call(None, "sonnet")},
        },
        tmp_path,
    )
    assert result.returncode == 2
    assert "ROUTE" in result.stdout


def test_registered_hook_blocks_a_floor_triggered_b3(tmp_path: Path) -> None:
    route = _ROUTE_B3.replace("S2A1R1V2N1C1J1", "S2A1R3V2N1C1J1").replace(
        "score=9", "score=11"
    )
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {"script": _routed_call(route, "sonnet")},
        },
        tmp_path,
    )
    assert result.returncode == 2
    assert "hard floor" in result.stdout


def test_registered_hook_blocks_an_agent_without_route(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "general-purpose",
                "model": "sonnet",
                "description": "d",
                "prompt": "work",
            },
        },
        tmp_path,
    )
    assert result.returncode == 2
    assert "ROUTE" in result.stdout


def test_effort_is_read_from_the_agent_options_object() -> None:
    """OMN-17427 W9: the Workflow ``agent()`` helper accepts ``opts.effort``,
    observed as ``effort low`` in the subagent transcript.

    Read it the way a ROUTE parser does, with the guard's own scanner
    helpers: the top-level ``effort`` property of the options object is the
    per-call value, and the ``effort`` nested inside the ``schema`` property
    is NOT picked up. Effort is not the model gate's business, so the check
    stays clean.
    """
    source = (
        "await agent(`x`, { label: 'e', model: 'sonnet', effort: 'low', "
        "schema: { type: 'object', properties: { effort: { type: 'string' } } } })"
    )
    masked = _GUARD._mask(source).text
    open_paren = masked.find("agent(") + len("agent")
    spans = _GUARD._split_arguments(masked, open_paren)
    assert spans is not None and len(spans) >= 2
    opt_start, opt_end = spans[1]
    lead = len(masked[opt_start:opt_end]) - len(masked[opt_start:opt_end].lstrip())
    brace = opt_start + lead
    close = _GUARD._matching_brace(masked, brace, opt_end)
    assert close is not None
    props, _ = _GUARD._object_properties(masked, brace, close)
    assert [prop.key for prop in props].count("effort") == 1
    efforts = [
        _GUARD._string_literal(source, masked, prop.value_start, prop.value_end)
        for prop in props
        if prop.key == "effort"
    ]
    assert efforts == ["low"]
    assert _check(source) == []
