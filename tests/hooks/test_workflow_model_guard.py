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
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

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
_ROUTE_B1_HAIKU = (
    "ROUTE: band=B1 score=3 dims=S1A1R0V1N0C0J0 dest=haiku-lane model=haiku effort=low"
)
_ROUTE_B5_FABLE = (
    "ROUTE: band=B5 score=16 dims=S3A3R3V3N2C2J0 dest=claude model=fable effort=high "
    "(complexity: operator ruling)"
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


def test_shipped_allowlist_is_exactly_the_four_background_models() -> None:
    """Fable joined 2026-11-10 (B5), haiku 2026-11-16 (B1) by operator ruling."""
    assert set(ALLOWLIST) == {"fable", "haiku", "opus", "sonnet"}


def test_shipped_allowlist_has_haiku() -> None:
    """RULING 2026-11-16T19:43:11Z: haiku may run low-score mechanical work."""
    assert "haiku" in ALLOWLIST


def test_shipped_allowlist_has_no_inherit_escape_hatch() -> None:
    """An inherited model is the defect, so no spelling of it may pass.

    The originating spec proposed ``model: 'inherit'`` as a visible-in-the-diff
    opt-out. It is deliberately absent: the incident was 41 agents running on
    an inherited model, and a sanctioned spelling for that is a sanctioned
    incident.
    """
    assert "inherit" not in ALLOWLIST


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


def test_unlisted_model_fails_and_the_message_quotes_the_offending_value() -> None:
    """The banned model, named in the refusal so the author sees what they wrote."""
    source = "await agent(`x`, { label: 'other-call', model: 'gpt-5' })"
    findings = _check(source)
    assert len(findings) == 1
    assert "'gpt-5'" in findings[0].reason
    assert "not an allowed background model" in findings[0].reason
    assert "fable, haiku, opus, sonnet" in findings[0].reason
    assert findings[0].label == "other-call"


def test_fable_passes_the_allowlist() -> None:
    """Operator ruling 2026-11-10: Fable may run as a background agent."""
    assert _check("await agent(`x`, { label: 'fable-call', model: 'fable' })") == []


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
        "const c = 'x'\n"
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


@pytest.mark.parametrize("model", ["sonnet", "opus", "haiku"])
def test_workflow_agent_on_an_allowed_model_passes(model: str) -> None:
    assert _check(f"await agent(`x`, {{ label: 'ok', model: '{model}' }})") == []


def test_workflow_agent_on_a_haiku_alias_is_allowed_and_a_pinned_id_is_not() -> None:
    """The alias is the allowlisted spelling; a dated id is not, and no longer
    carries a 'removed' note because haiku is not removed."""
    assert _check("await agent(`x`, { label: 'h', model: 'haiku' })") == []
    findings = _check(
        "await agent(`x`, { label: 'h', model: 'claude-haiku-4-5-20251001' })"
    )
    assert len(findings) == 1
    assert "not an allowed background model" in findings[0].reason
    assert "haiku is removed" not in findings[0].reason


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
    """The model check holds on a real excerpt. An excerpt is one call clipped from its script, so
    a const the prompt names (``COMMON``, ``counts``) sits outside it and the lab-host check
    reads that as an unresolved substitution; that finding is not a model finding."""
    findings = [
        f
        for f in _GUARD.check_workflow_script(
            path.read_text(encoding="utf-8"), ALLOWLIST, filename=path.name
        )
        if not _GUARD._lab().fix_lines([f.reason])
    ]
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


def test_agent_on_a_haiku_alias_is_allowed_and_a_pinned_id_is_not() -> None:
    allowed = _GUARD.check_agent_input(
        {"subagent_type": "general-purpose", "model": "haiku"}, ALLOWLIST
    )
    assert allowed == []
    findings = _GUARD.check_agent_input(
        {"subagent_type": "general-purpose", "model": "claude-haiku-4-5-20251001"},
        ALLOWLIST,
    )
    assert len(findings) == 1
    assert "not an allowed background model" in findings[0].reason
    assert "haiku is removed" not in findings[0].reason


def test_agent_with_no_model_fails() -> None:
    findings = _GUARD.check_agent_input(
        {"subagent_type": "general-purpose", "description": "do a thing"}, ALLOWLIST
    )
    assert len(findings) == 1
    assert "declares no model" in findings[0].reason
    assert findings[0].label == "do a thing"


def test_agent_with_disallowed_model_fails() -> None:
    findings = _GUARD.check_agent_input(
        {"subagent_type": "general-purpose", "model": "gpt-5"}, ALLOWLIST
    )
    assert len(findings) == 1
    assert "'gpt-5'" in findings[0].reason


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
    payload: dict[str, Any],
    tmp_path: Path,
    *,
    hook_script: Path = _HOOK_SCRIPT,
    registry_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(hook_script.parents[2]),
        "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        # Pinned, not inherited: mode.sh resolves "lite" for a CI runner's cwd,
        # and the question here is whether the hook enforces, not what mode the
        # host happens to be in.
        "OMNICLAUDE_MODE": "full",
    }
    if registry_root is not None:
        env["OMNI_HOME"] = str(registry_root)
    return subprocess.run(
        ["bash", str(hook_script)],
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
        "await agent(`x`, { label: 'from-disk', model: 'gpt-5' })\n", encoding="utf-8"
    )
    result = _run_hook(
        {"tool_name": "Workflow", "tool_input": {"scriptPath": str(script)}}, tmp_path
    )
    assert result.returncode == 2
    assert "from-disk" in result.stdout
    assert "gpt-5" in result.stdout


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
        "const re = /a\\/\\//; agent('t', { label: 'x', model: 'gpt-5' });\n"
    )
    assert len(findings) == 1, [f.render() for f in findings]
    assert "'gpt-5'" in findings[0].reason


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
    assert ROUTING.bands["B5"].models == frozenset({"opus", "fable"})
    assert ROUTING.bands["B5"].efforts == frozenset({"xhigh", "high"})
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


def test_fable_agent_with_a_valid_b5_route_passes() -> None:
    """Operator ruling 2026-11-10: a Fable agent at band B5 with effort high."""
    assert _check_routed(_routed_call(_ROUTE_B5_FABLE, "fable")) == []


def test_fable_is_refused_below_band_b5() -> None:
    route = _ROUTE_B4.replace("model=opus", "model=fable")
    findings = _check_routed(_routed_call(route, "fable"))
    assert len(findings) == 1
    assert "band B4" in findings[0].reason


def test_haiku_is_refused_at_b2_and_above_naming_the_bands_models() -> None:
    """Haiku is allowed in band B1 only (RULING 2026-11-16T19:43:11Z)."""
    for route in (_ROUTE_B2, _ROUTE_B3, _ROUTE_B4, _ROUTE_B5, _ROUTE_B5_FABLE):
        band = route.split("band=")[1].split()[0]
        swapped = re.sub(r"model=\w+", "model=haiku", route)
        findings = _check_routed(_routed_call(swapped, "haiku"))
        assert len(findings) == 1, band
        reason = findings[0].reason
        assert f"band {band} allows only:" in reason, band
        assert "'haiku' is not in that set" in reason, band
        assert "haiku is removed" not in reason, band


def test_haiku_route_in_the_haiku_band_passes() -> None:
    assert _check_routed(_routed_call(_ROUTE_B1_HAIKU, "haiku")) == []


@pytest.mark.parametrize("effort", ["low", "medium"])
def test_haiku_band_accepts_the_efforts_in_its_set(effort: str) -> None:
    route = _ROUTE_B1_HAIKU.replace("effort=low", f"effort={effort}")
    assert _check_routed(_routed_call(route, "haiku")) == []


@pytest.mark.parametrize("effort", ["high", "xhigh", "max", "ultra"])
def test_haiku_band_refuses_an_effort_outside_its_set(effort: str) -> None:
    route = _ROUTE_B1_HAIKU.replace("effort=low", f"effort={effort}")
    findings = _check_routed(_routed_call(route, "haiku"))
    assert len(findings) == 1
    assert findings[0].reason == (
        f"ROUTE effort={effort} is not allowed for band B1 (allowed: low, medium)"
    )


@pytest.mark.parametrize("model", ["sonnet", "opus", "fable"])
def test_haiku_band_refuses_any_other_model(model: str) -> None:
    route = _ROUTE_B1_HAIKU.replace("model=haiku", f"model={model}")
    findings = _check_routed(_routed_call(route, model))
    assert len(findings) == 1
    assert "band B1 allows only: haiku" in findings[0].reason


def test_haiku_route_whose_score_does_not_fit_the_haiku_band_is_refused() -> None:
    """Score 5 implies band B2; a haiku ROUTE claiming B1 sits below its score."""
    route = _ROUTE_B1_HAIKU.replace("score=3", "score=5").replace(
        "S1A1R0V1N0C0J0", "S1A1R1V1N1C0J0"
    )
    findings = _check_routed(_routed_call(route, "haiku"))
    assert len(findings) == 1
    assert "below the band score 5 implies" in findings[0].reason


def test_haiku_route_with_a_hard_floor_dimension_is_refused() -> None:
    route = _ROUTE_B1_HAIKU.replace("S1A1R0V1N0C0J0", "S0A0R3V0N0C0J0")
    findings = _check_routed(_routed_call(route, "haiku"))
    assert len(findings) == 1
    assert "hard floor" in findings[0].reason


def test_haiku_band_is_data_only_b1c_and_b0_still_dispatch_no_agent() -> None:
    assert ROUTING.bands["B1"].models == frozenset({"haiku"})
    assert ROUTING.bands["B1"].efforts == frozenset({"low", "medium"})
    assert ROUTING.bands["B0"].models == frozenset()
    assert ROUTING.bands["B1c"].models == frozenset()
    # Every other band is exactly as before the haiku ruling.
    assert ROUTING.bands["B2"].models == frozenset({"sonnet"})
    assert ROUTING.bands["B2"].efforts == frozenset({"medium", "high"})
    assert ROUTING.bands["B3"].models == frozenset({"sonnet"})
    assert ROUTING.bands["B3"].efforts == frozenset({"high"})
    assert ROUTING.bands["B4"].models == frozenset({"opus"})
    assert ROUTING.bands["B5"].models == frozenset({"opus", "fable"})


def test_haiku_agent_tool_dispatch_in_b1_passes_and_in_b3_is_refused() -> None:
    base = {"subagent_type": "general-purpose", "model": "haiku", "description": "d"}
    ok = _GUARD.check_agent_input(
        {**base, "prompt": f"{_ROUTE_B1_HAIKU}\nwork"}, ALLOWLIST, routing=ROUTING
    )
    assert ok == []
    b3 = _ROUTE_B3.replace("model=sonnet", "model=haiku")
    bad = _GUARD.check_agent_input(
        {**base, "prompt": f"{b3}\nwork"}, ALLOWLIST, routing=ROUTING
    )
    assert len(bad) == 1
    assert "band B3 allows only: sonnet" in bad[0].reason


def test_a_missing_model_is_still_refused_with_a_fable_route() -> None:
    source = f"await agent(`{_ROUTE_B5_FABLE}\\ndo a thing`, {{ label: 'r' }})\n"
    findings = _check_routed(source)
    assert len(findings) == 1
    assert "no model" in findings[0].reason


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


@pytest.mark.parametrize("band", ["B0", "B1c"])
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


def test_registered_hook_passes_a_haiku_route_in_the_haiku_band(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {"script": _routed_call(_ROUTE_B1_HAIKU, "haiku")},
        },
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


def test_registered_hook_blocks_a_haiku_route_in_b3(tmp_path: Path) -> None:
    route = _ROUTE_B3.replace("model=sonnet", "model=haiku")
    result = _run_hook(
        {
            "tool_name": "Workflow",
            "tool_input": {"script": _routed_call(route, "haiku")},
        },
        tmp_path,
    )
    assert result.returncode == 2
    assert "band B3 allows only: sonnet" in result.stdout


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


# ---------------------------------------------------------------------------
# Lab-host work (OMN-24618, OMN-24710)
# ---------------------------------------------------------------------------


def _lab() -> Any:
    """The lab-host check module the guard loads by path."""
    return _GUARD._lab()


@pytest.fixture(autouse=True)
def _dispatching_host_is_not_a_lab_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check skips a lab host; a test runner may be one, so it never reads its own name."""
    monkeypatch.setattr(_lab().socket, "gethostname", lambda: "dev-laptop")


@pytest.fixture
def lab_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lab hosts: h201 and h202 from the pool table, labbox from the ssh config."""
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Host labbox\nHost *\nHost github.com\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(
        "LANDING_POOL_HOSTS", json.dumps([{"name": "h201"}, {"name": "h202"}])
    )


def _lab_check(prompt: str, label: str = "r") -> list[Any]:
    source = f"await agent(`{prompt}`, {{ label: '{label}', model: 'sonnet' }})\n"
    return list(_GUARD.check_workflow_script(source, ALLOWLIST, filename="case.js"))


def _refused(findings: list[Any], phrase: str = "no declared placement") -> bool:
    return len(findings) == 1 and phrase in findings[0].reason


@pytest.mark.parametrize(
    "prompt",
    [
        "run ssh h201 docker ps and report",
        "ssh -o BatchMode=yes me@labbox uptime",
        "run docker ps on h202 and list the containers",
        "systemctl restart onex on h201",
        "first do a thing\\nthen ssh h201 ls",
    ],
)
def test_lab_host_work_refused_without_declaration(
    lab_table: None, prompt: str
) -> None:
    assert _refused(_lab_check(prompt))


@pytest.mark.parametrize(
    "prompt",
    [
        "scp h201:/tmp/report.txt . and read it",
        "rsync -a h202:/data/out ./out then summarise",
        "sftp me@labbox and fetch the log",
        "first a thing\\nthen scp ./x h201:/tmp/x",
    ],
)
def test_lab_host_work_copy_commands_to_a_lab_host_refused_and_declaration_admits(
    lab_table: None, prompt: str
) -> None:
    """scp, sftp and rsync reach a lab host the way ssh does: no declared placement, no pass (OMN-24618)."""
    assert _refused(_lab_check(prompt))
    assert _lab_check(f"{prompt}\\nPLACEMENT: remote-lane") == []


@pytest.mark.parametrize(
    "prompt",
    [
        "scp ./a me@example.org:/tmp/a",
        "rsync -a ./src/ ./dst/",
        "the scp and rsync man pages describe copies",
    ],
)
def test_lab_host_work_copy_commands_not_naming_a_lab_host_untouched(
    lab_table: None, prompt: str
) -> None:
    assert _lab_check(prompt) == []


@pytest.mark.parametrize(
    "prompt",
    [
        "ssh h201 ls LOCAL-ONLY:",
        "ssh h201 ls LOCAL-ONLY:   \\nmore",
        "ssh h201 ls LOCAL-ONLY: .",
    ],
)
def test_lab_host_work_refused_with_empty_local_only_reason(
    lab_table: None, prompt: str
) -> None:
    assert len(_lab_check(prompt)) == 1


_DECLARATIONS = [
    "PLACEMENT: remote-lane",
    "PLACEMENT: fable-review",
    "LOCAL-ONLY: reading a mac-local file the lab cannot reach",
]


@pytest.mark.parametrize("declaration", _DECLARATIONS)
def test_lab_host_work_allowed_with_declaration_in_prompt(
    lab_table: None, declaration: str
) -> None:
    assert _lab_check(f"{declaration}\\nssh h201 docker ps") == []


@pytest.mark.parametrize("declaration", _DECLARATIONS)
def test_lab_host_work_allowed_with_declaration_in_label(
    lab_table: None, declaration: str
) -> None:
    assert _lab_check("ssh h201 docker ps", label=declaration) == []


@pytest.mark.parametrize(
    "prompt",
    [
        "ssh buildbox.example.com uptime",
        "the docker image is rebuilt nightly; explain how docker layers work",
        "summarise the h201 design note",
        "systemctl --user status mything",
    ],
)
def test_lab_host_work_unrelated_prompt_untouched(lab_table: None, prompt: str) -> None:
    assert _lab_check(prompt) == []


@pytest.fixture
def lab_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No pool variable, no table variable, an empty ssh config: nothing is a lab host yet."""
    for var in (
        "LANDING_POOL_HOSTS",
        "ONEX_LAB_RUN_HOSTS",
        "ONEX_SKILL_OVERLAY_ROOTS",
        "OMNI_HOME",
    ):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Host *\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_lab_host_work_no_table_means_nothing_to_refuse(lab_env: Path) -> None:
    """With no pool, no table and an empty ssh config nothing is a lab host, whatever the
    host's own ONEX_LAB_RUN_HOSTS says (lab_env clears every table variable)."""
    assert _lab_check("ssh h201 ls") == []


def test_lab_host_work_agent_tool_refused_and_admitted(lab_table: None) -> None:
    refused = _GUARD.check_agent_input(
        {"model": "sonnet", "prompt": "ssh h201 docker ps"}, ALLOWLIST
    )
    assert len(refused) == 1
    admitted = _GUARD.check_agent_input(
        {
            "model": "sonnet",
            "prompt": "ssh h201 docker ps",
            "description": "PLACEMENT: remote-lane",
        },
        ALLOWLIST,
    )
    assert admitted == []


def _ip(*octets: int) -> str:
    return ".".join(str(o) for o in octets)


_TABLE = """\
hosts:
  - name: h301
    target: ops@tablehost
    fallback_targets: [spare1, ops@spare2]
    cap: 4
  - name: h302
    target: ops@other
    available: false
"""


def test_lab_host_work_names_load_from_ssh_config_and_pool_rows(
    lab_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (lab_env / ".ssh" / "config").write_text(
        f"Host alpha beta\n  HostName {_ip(10, 9, 9, 9)}\nHost *\nHost github.com\n"
    )
    monkeypatch.setenv(
        "LANDING_POOL_HOSTS", json.dumps([{"name": "h201", "target": "me@gamma"}])
    )
    assert _lab().hostnames() == {
        "alpha",
        "beta",
        _ip(10, 9, 9, 9),
        "h201",
        "gamma",
    }


def test_lab_host_work_table_names_seen_with_pool_variable_unset(
    lab_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = lab_env / "lab_hosts.yaml"
    table.write_text(_TABLE)
    monkeypatch.setenv("ONEX_LAB_RUN_HOSTS", str(table))
    for prompt in (
        "ssh h301 uptime",
        "ssh tablehost docker ps",
        "docker ps on spare1",
        "systemctl restart x on spare2",
    ):
        assert _refused(_lab_check(prompt))


def test_lab_host_work_table_from_overlay_store_snapshot(
    lab_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The table is found the way the placement code finds it: the store reader's snapshot_root."""
    root = lab_env / "overlays"
    (root / "node_overlay_store_read_effect").mkdir(parents=True)
    (root / "node_overlay_store_read_effect" / "overlay.yaml").write_text(
        f"snapshot_root: {lab_env}/snap\n"
    )
    (lab_env / "snap" / "lab_hosts").mkdir(parents=True)
    (lab_env / "snap" / "lab_hosts" / "overlay.yaml").write_text(_TABLE)
    monkeypatch.setenv("ONEX_SKILL_OVERLAY_ROOTS", str(root))
    assert len(_lab_check("ssh h301 uptime")) == 1


_REAL_TABLE = """\
hosts:
  - name: h105
    target: ops@box-a
    available: false
  - name: h200
    target: ops@box-b
  - name: h201
    target: ops@box-c
"""


_CLONE_ROOT = "overlays/overlays"
_READER_ROOT = "overlay-store-reader/overlays/overlays"


@pytest.mark.parametrize("store_root", [_CLONE_ROOT, _READER_ROOT])
def test_lab_table_real_layout_with_only_the_registry_variable_set(
    lab_env: Path, monkeypatch: pytest.MonkeyPatch, store_root: str
) -> None:
    """A tree laid out like the real one: the overlays clone (or the store reader checkout) sits
    beside the registry root, the store reader's overlay names a snapshot_root under HOME, and
    OMNI_HOME is the only variable set. The ssh config is empty, so every name comes from the table."""
    registry = lab_env / "work" / "registry"
    registry.mkdir(parents=True)
    reader = lab_env / "work" / store_root
    (reader / "node_overlay_store_read_effect").mkdir(parents=True)
    (reader / "node_overlay_store_read_effect" / "overlay.yaml").write_text(
        "snapshot_root: ~/snap  # where the reader writes\n"
    )
    (lab_env / "snap" / "lab_hosts").mkdir(parents=True)
    (lab_env / "snap" / "lab_hosts" / "overlay.yaml").write_text(_REAL_TABLE)
    monkeypatch.setenv("OMNI_HOME", str(registry))
    for prompt in (
        "ssh h201 docker ps",
        "ssh h200 uptime",
        "docker ps on h105",
        "ssh box-c uptime",
    ):
        assert _refused(_lab_check(prompt)), prompt
    assert _lab_check("ssh buildbox.example.com uptime") == []


def test_lab_table_real_layout_first_store_reader_overlay_decides(
    lab_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first store reader overlay found decides, as handler_host_capability.snapshot_root does:
    one with no snapshot_root line yields no table and a later root is not tried."""
    registry = lab_env / "work" / "registry"
    registry.mkdir(parents=True)
    for root, text in ((_CLONE_ROOT, "other: 1\n"), (_READER_ROOT, None)):
        reader = lab_env / "work" / root
        (reader / "node_overlay_store_read_effect").mkdir(parents=True)
        (reader / "node_overlay_store_read_effect" / "overlay.yaml").write_text(
            text or "snapshot_root: ~/snap\n"
        )
    (lab_env / "snap" / "lab_hosts").mkdir(parents=True)
    (lab_env / "snap" / "lab_hosts" / "overlay.yaml").write_text(_REAL_TABLE)
    monkeypatch.setenv("OMNI_HOME", str(registry))
    assert _lab_check("ssh h201 docker ps") == []


def test_lab_host_work_ssh_config_alias_seen_with_pool_variable_unset(
    lab_env: Path,
) -> None:
    lab_ip = _ip(10, 1, 2, 3)
    (lab_env / ".ssh" / "config").write_text(f"Host labalias\n  HostName {lab_ip}\n")
    assert len(_lab_check("ssh labalias uptime")) == 1
    assert len(_lab_check(f"ssh {lab_ip} uptime")) == 1
    # The /24 of a configured lab address is the lab subnet.
    assert len(_lab_check(f"ssh root@{_ip(10, 1, 2, 77)} docker ps")) == 1
    assert _lab_check(f"ssh {_ip(10, 1, 3, 3)} uptime") == []


@pytest.mark.parametrize(
    "prompt",
    [
        f"ssh {_ip(192, 168, 86, 201)} docker ps",
        f"ssh root@{_ip(192, 168, 1, 45)} uptime",
        f"ssh {_ip(10, 0, 0, 5)} uptime",
        f"ssh {_ip(203, 0, 113, 5)} uptime",
        f"release {_ip(192, 168, 86, 1)} notes mention a router",
    ],
)
def test_lab_host_work_unconfigured_address_untouched(
    lab_env: Path, prompt: str
) -> None:
    """No address range is built in: an address nothing configures is not a lab address."""
    assert _lab_check(prompt) == []


@pytest.mark.parametrize(
    "reason",
    ["<reason>", "TBD", "todo", "n/a", "none", "reason", "needed", "because", ".."],
)
def test_lab_host_work_local_only_placeholder_reason_refused(
    lab_table: None, reason: str
) -> None:
    assert len(_lab_check(f"LOCAL-ONLY: {reason}\\nssh h201 ls")) == 1


@pytest.mark.parametrize(
    "reason",
    [
        "reading a mac-local file the lab cannot reach",
        "the keychain only unlocks on the operator Mac",
    ],
)
def test_lab_host_work_local_only_real_reason_allowed(
    lab_table: None, reason: str
) -> None:
    assert _lab_check(f"LOCAL-ONLY: {reason}\\nssh h201 ls") == []


@pytest.mark.parametrize("host", ["h201", "h201.example.org"])
def test_lab_host_work_skipped_when_the_dispatching_host_is_a_lab_host(
    lab_table: None, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    """Lab work belongs on a lab host, so a dispatch made there is not checked; the Mac is."""
    assert _refused(_lab_check("ssh h202 docker ps"))
    monkeypatch.setattr(_lab().socket, "gethostname", lambda: host)
    assert _lab_check("ssh h202 docker ps") == []


def _lab_script(prompt_expr: str, setup: str = "", label: str = "r") -> list[Any]:
    source = f"{setup}\nawait agent({prompt_expr}, {{ label: '{label}', model: 'sonnet' }})\n"
    return list(_GUARD.check_workflow_script(source, ALLOWLIST, filename="case.js"))


def test_lab_host_work_const_held_prompt_read_by_name(lab_table: None) -> None:
    assert _refused(_lab_script("PROMPT", "const PROMPT = 'ssh h201 docker ps'"))
    assert len(_lab_script("PROMPT", "const PROMPT = `run\nssh h201 ls`;")) == 1


def test_lab_host_work_const_chain_template_and_concat_read(lab_table: None) -> None:
    setup = "const CMD = 'ssh h201 docker ps'\nconst BODY = `do: ${CMD}`\n"
    assert len(_lab_script("BODY", setup)) == 1
    assert len(_lab_script("'prefix ' + CMD", setup)) == 1
    assert len(_lab_script("`pre ${BODY}`", setup)) == 1


def test_lab_host_work_function_built_prompt_read(lab_table: None) -> None:
    setup = "function build(x) { return `ssh h201 uptime ${x}` }\n"
    assert _refused(_lab_script("build(1)", setup))


def test_lab_host_work_function_parameter_is_what_the_call_passes(
    lab_table: None,
) -> None:
    """A parameter is resolved by the call's argument, which sits in the scanned span."""
    setup = "function build(x) { return `explain ${x}` }\n"
    assert _lab_script("build('docker layers')", setup) == []
    assert _lab_script("build(args.topic)", setup) == []
    assert _refused(_lab_script("build('ssh h201 ls')", setup))
    with_command = "function build(x) { return `docker ${x}` }\n"
    assert _refused(_lab_script("build(args.topic)", with_command), "cannot be read")


def test_lab_host_work_const_held_prompt_with_declaration_admitted(
    lab_table: None,
) -> None:
    setup = "const PROMPT = 'PLACEMENT: remote-lane\\nssh h201 docker ps'"
    assert _lab_script("PROMPT", setup) == []
    assert (
        _lab_script(
            "PROMPT",
            "const PROMPT = 'ssh h201 ls'",
            label="LOCAL-ONLY: the keychain lives on this Mac",
        )
        == []
    )


def test_lab_host_work_const_held_clean_prompt_untouched(lab_table: None) -> None:
    assert _lab_script("PROMPT", "const PROMPT = 'summarise the design note'") == []
    assert _lab_script("`explain ${TOPIC}`", "const TOPIC = 'docker layers'") == []


@pytest.mark.parametrize(
    ("expr", "setup"),
    [
        ("args.prompt", ""),
        ("PROMPT", "const PROMPT = args.prompt"),
        ("pick(items)", ""),
        ("`${x}`", "const x = readIt()"),
    ],
)
def test_lab_host_work_unreadable_prompt_refused(
    lab_table: None, expr: str, setup: str
) -> None:
    assert _refused(_lab_script(expr, setup), "cannot be read")


def test_lab_host_work_unreadable_prompt_with_declaration_admitted(
    lab_table: None,
) -> None:
    assert _lab_script("args.prompt", label="PLACEMENT: remote-lane") == []


# --- variable host (OMN-24710 finding 3) -----------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "setup"),
    [
        # A host from the script's args, in a template, in a concatenation, in a loop.
        ("`ssh ${args.host} uptime`", ""),
        ("`ssh ${h} uptime`", "for (const h of ['h201', 'h202']) { void h }"),
        ("`ssh ${HOST} uptime`", "const HOST = args.host"),
    ],
)
def test_lab_host_work_variable_host_substitution_makes_the_prompt_unreadable(
    lab_table: None, expr: str, setup: str
) -> None:
    findings = _lab_script(expr, setup)
    assert _refused(findings, "cannot be read")
    declared = _lab_script(expr, setup, label="PLACEMENT: remote-lane")
    assert declared == []


@pytest.mark.parametrize(
    "prompt",
    [
        "ssh $HOST uptime",
        "ssh ${HOST} uptime",
        "ssh -o BatchMode=yes me@$HOST ls",
        "ssh me@${HOST}.lan ls",
        "scp ./x $DEST",
        'rsync -a ./out "$TARGET":/tmp',
        "ssh $(cat hosts.txt) uptime",
        "docker -H $DOCKER_HOST ps",
        "run docker ps on $HOST",
    ],
)
def test_lab_host_work_variable_host_shell_variable_refused_unless_declared(
    lab_table: None, prompt: str
) -> None:
    """No name matches: the host is a shell variable and cannot be read."""
    source = f"await agent('{prompt}', {{ label: 'r', model: 'sonnet' }})\n"
    findings = list(_GUARD.check_workflow_script(source, ALLOWLIST, filename="c.js"))
    assert _refused(findings), prompt
    assert "variable" in findings[0].reason
    declared = source.replace("'r'", "'PLACEMENT: remote-lane'")
    assert _GUARD.check_workflow_script(declared, ALLOWLIST, filename="c.js") == []


def test_lab_host_work_variable_host_resolved_const_is_read_not_refused(
    lab_table: None,
) -> None:
    """A const the script defines is read: a non-lab host passes, a lab host is refused."""
    prompt = "`ssh ${HOST} uptime`"
    assert _lab_script(prompt, "const HOST = 'buildbox.example.com'") == []
    assert _refused(_lab_script(prompt, "const HOST = 'h201'"))


def test_lab_host_work_variable_host_in_a_prompt_naming_no_command_untouched(
    lab_env: Path,
) -> None:
    assert _lab_check("the value $HOST is a shell variable; explain it") == []
    assert _lab_check("price is $5 per hour") == []


# --- host on a later line, dotted host (OMN-24710 finding 4) ----------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "On h201 run:\\ndocker ps -a",
        "docker ps -a\\nand do it on h202",
        "systemctl restart onex\\n\\nthe host is labbox",
        "run this:\\n\\n    docker ps\\n\\nagainst h201 please",
    ],
)
def test_lab_host_work_multiline_host_refused(lab_table: None, prompt: str) -> None:
    assert _refused(_lab_check(prompt))
    assert _lab_check(f"{prompt}\\nPLACEMENT: remote-lane") == []


@pytest.mark.parametrize(
    "prompt",
    [
        "ssh h201.lan uptime",
        "ssh h202.example.org docker ps",
        "scp ./x labbox.example:/tmp/x",
    ],
)
def test_lab_host_work_dotted_host_refused(lab_table: None, prompt: str) -> None:
    assert _refused(_lab_check(prompt))
    assert _lab_check(f"{prompt}\\nPLACEMENT: remote-lane") == []


@pytest.mark.parametrize(
    "prompt",
    ["ssh buildbox.h201.example uptime", "ssh x-h201 uptime", "ssh h2011 uptime"],
)
def test_lab_host_work_name_inside_another_name_untouched(
    lab_table: None, prompt: str
) -> None:
    assert _lab_check(prompt) == []


# --- ROUTE reads what dev reads (OMN-24710 finding 1) -----------------------------------------


def _route(model: str, band: str, score: int, dims: str) -> str:
    return (
        f"ROUTE: band={band} score={score} dims={dims} dest=lane "
        f"model={model} effort=high"
    )


def test_route_expansion_second_call_interpolating_the_first_result_is_accepted(
    lab_table: None,
) -> None:
    """A const the prompt names is read by the lab check only: the ROUTE check reads the prompt
    span and the label, as the base branch does. Reading the first call's text here put the first
    call's ROUTE (sonnet) ahead of the second call's own (opus) and refused it on ROUTE alone."""
    first = _route("sonnet", "B3", 9, "S2A1R1V2N1C1J1")
    second = _route("opus", "B4", 14, "S2A2R2V2N2C2J2")
    source = (
        f"const first = await agent('{first}\\nwork', {{ label: 'a', model: 'sonnet' }})\n"
        f"await agent(first + ' go', {{ label: '{second}', model: 'opus' }})\n"
    )
    findings = _GUARD.check_workflow_script(
        source, ALLOWLIST, filename="c.js", routing=ROUTING
    )
    assert findings == []


def test_route_expansion_a_real_route_mismatch_is_still_refused(
    lab_table: None,
) -> None:
    """Control: the call's own ROUTE line still has to match its declared model."""
    first = _route("sonnet", "B3", 9, "S2A1R1V2N1C1J1")
    source = f"await agent('{first}\\nwork', {{ label: 'a', model: 'opus' }})\n"
    findings = _GUARD.check_workflow_script(
        source, ALLOWLIST, filename="c.js", routing=ROUTING
    )
    assert len(findings) == 1 and "does not match" in findings[0].reason


def test_lab_host_work_real_hook_refuses_then_admits(lab_table: None) -> None:
    """The registered shell hook, end to end: refused undeclared, silent when declared."""
    bash = shutil.which("bash")
    assert bash is not None

    def run(prompt: str) -> subprocess.CompletedProcess[str]:
        script = (
            f"await agent(`{_ROUTE_B3}\\n{prompt}`, {{ label: 'r', model: 'sonnet' }})"
        )
        payload = json.dumps(
            {"tool_name": "Workflow", "tool_input": {"script": script}}
        )
        return subprocess.run(
            [bash, str(_HOOK_SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_PLUGIN_ROOT": str(_REPO_ROOT / "plugins" / "onex"),
                "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
            },
            cwd=_REPO_ROOT,
            timeout=_TIMEOUT_S,
            check=False,
        )

    refused = run("ssh h201 docker ps")
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "no declared placement" in refused.stdout
    assert "PLACEMENT: remote-lane" in refused.stdout
    admitted = run("PLACEMENT: remote-lane\\nssh h201 docker ps")
    assert admitted.returncode == 0 and admitted.stdout == ""


# ---------------------------------------------------------------------------
# OMN-24738: the installed shape, the local row, the unresolved substitution
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def installed_plugin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of ``plugins/onex`` laid out as the plugin cache lays it out: the plugin
    directory and nothing of the repository (no ``src/``) around it."""
    root = (
        tmp_path_factory.mktemp("cache")
        / "plugins"
        / "cache"
        / "omninode-tools-dev"
        / "onex"
        / "9.9.9"
    )
    shutil.copytree(
        _REPO_ROOT / "plugins" / "onex",
        root,
        ignore=shutil.ignore_patterns("__pycache__", ".venv", "*.pyc"),
    )
    return root


def _installed_hook(plugin: Path, tool_name: str, tool_input: dict[str, Any]) -> Any:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(
        [bash, str(plugin / "hooks" / "scripts" / _HOOK_SCRIPT.name)],
        input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CLAUDE_PLUGIN_ROOT": str(plugin),
            "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        },
        cwd=_REPO_ROOT,
        timeout=_TIMEOUT_S,
        check=False,
    )


def test_lab_host_work_installed_layout_admits_a_benign_agent_call(
    installed_plugin: Path,
) -> None:
    """In the cache layout the lab check has no ``src/`` to load from. That must switch the
    check off, never refuse every dispatch: a benign call exits 0 and prints nothing."""
    own = installed_plugin.parents[1] / "src" / "omniclaude" / "handlers"
    assert not (own / "lab_host_work.py").exists(), "the layout must hold no src/"
    benign = _installed_hook(
        installed_plugin,
        "Agent",
        {"model": "sonnet", "prompt": f"{_ROUTE_B3}\nsummarise the design note"},
    )
    assert benign.returncode == 0, benign.stdout + benign.stderr
    assert benign.stdout == ""
    script = (
        f"await agent(`{_ROUTE_B3}\nsummarise it`, {{ label: 'r', model: 'sonnet' }})"
    )
    workflow = _installed_hook(installed_plugin, "Workflow", {"script": script})
    assert workflow.returncode == 0, workflow.stdout + workflow.stderr
    assert workflow.stdout == ""


def test_lab_host_work_installed_layout_still_refuses_an_unnamed_model(
    installed_plugin: Path,
) -> None:
    """Control: the rest of the guard still runs in the cache layout."""
    refused = _installed_hook(
        installed_plugin, "Agent", {"prompt": f"{_ROUTE_B3}\nsummarise it"}
    )
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "model" in refused.stdout


def test_lab_host_work_installed_layout_repository_layout_still_checks_the_lab(
    lab_table: None,
) -> None:
    """Control: with ``src/`` beside the guard the lab check is loaded and refuses."""
    assert _GUARD._lab() is not None
    assert _refused(_lab_check("ssh h201 docker ps"))


_LOCAL_TABLE = """\
hosts:
  - name: macbox
    target: dev-mac
    local: true
  - name: h201
    target: lab201
  - name: parked
    target: parked-host
    available: false
"""


def _own_host_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hostname: str, rows: str
) -> None:
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Host *\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LANDING_POOL_HOSTS", raising=False)
    table = tmp_path / "lab_hosts.yaml"
    table.write_text(rows)
    monkeypatch.setenv("ONEX_LAB_RUN_HOSTS", str(table))
    monkeypatch.setattr(_lab().socket, "gethostname", lambda: hostname)


def test_lab_host_work_local_row_own_host_is_checked_like_any_mac(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The operator Mac is a ``local: true`` row of the table. The own-host skip never applies to
    it, whatever its hostname is, or the check is off on the one host it exists for."""
    _own_host_env(monkeypatch, tmp_path, "dev-mac", _LOCAL_TABLE)
    assert _refused(_lab_check("ssh h201 docker ps"))
    assert _refused(_lab_check("docker ps on lab201"))
    assert _lab_check("PLACEMENT: remote-lane\\nssh h201 docker ps") == []


def test_lab_host_work_local_row_own_host_in_the_pool_variable_is_checked(
    monkeypatch: pytest.MonkeyPatch, lab_env: Path
) -> None:
    rows = [{"name": "macbox", "target": "dev-mac", "local": True}, {"name": "h201"}]
    monkeypatch.setenv("LANDING_POOL_HOSTS", json.dumps(rows))
    monkeypatch.setattr(_lab().socket, "gethostname", lambda: "dev-mac")
    assert _refused(_lab_check("ssh h201 docker ps"))


@pytest.mark.parametrize(
    ("hostname", "skipped"),
    [("lab201", True), ("h201", True), ("dev-mac", False), ("parked-host", False)],
)
def test_lab_host_work_local_row_own_host_skip_only_on_a_placeable_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hostname: str,
    skipped: bool,
) -> None:
    """Control: a row where lab work may be placed still skips; a local row and an
    ``available: false`` row do not."""
    _own_host_env(monkeypatch, tmp_path, hostname, _LOCAL_TABLE)
    assert (_lab_check("ssh h201 docker ps") == []) is skipped


@pytest.mark.parametrize(
    ("expr", "setup"),
    [
        ("`Summarise ${args.path}`", ""),
        ("`Summarise ${f}`", "for (const f of files) { void f }"),
        ("`Summarise ${items.map(i => i.name).join(',')}`", ""),
        ("fmt('layers')", "const fmt = (n) => `explain docker ${n}`"),
        ("fmt('layers')", "const fmt = n => `explain docker ${n}`"),
        (
            "`Review: ${first}`",
            "const first = await agent('plan it', { label: 'a', model: 'sonnet' })",
        ),
        (
            "`Review: ${v}`",
            "const v = pick ? await agent('a', { label: 'x', model: 'sonnet' }) : "
            "await agent('b', { label: 'y', model: 'sonnet' })",
        ),
        ("args.prompt + ' go'", ""),
    ],
)
def test_lab_host_work_unresolved_substitution_with_no_command_word_admitted(
    lab_table: None, expr: str, setup: str
) -> None:
    assert _lab_script(expr, setup) == []


@pytest.mark.parametrize(
    ("expr", "setup"),
    [
        ("`ssh ${args.host} uptime`", ""),
        ("`docker ps ${args.flags}`", ""),
        ("args.prompt", ""),
        ("`${v}`", "const v = await agent('a', { label: 'x', model: 'sonnet' })"),
    ],
)
def test_lab_host_work_unresolved_substitution_refused_when_unreadable(
    lab_table: None, expr: str, setup: str
) -> None:
    """A command word with no readable host, or no literal text at all, is still refused."""
    assert _refused(_lab_script(expr, setup), "cannot be read")
    assert _lab_script(expr, setup + "\n// x", label="PLACEMENT: remote-lane") == []


def test_lab_host_work_unresolved_substitution_admitted_when_no_lab_host_is_known(
    lab_env: Path,
) -> None:
    """An empty name set means no table, no pool and no ssh config: there is nothing to refuse."""
    assert _lab()._tables(os.environ)[0] == frozenset()
    assert _lab_script("`Summarise ${args.path}`") == []
    assert _lab_script("args.prompt") == []
    assert _lab_check("ssh $HOST ls") == []


@pytest.mark.parametrize(
    "prompt",
    [
        "read ~/.ssh/config and say what h201 is",
        "open ./.ssh/config then describe h202",
        "list /opt/bin/docker and h201",
    ],
)
def test_lab_host_work_ssh_config_path_is_not_a_command(
    lab_table: None, prompt: str
) -> None:
    assert _lab_check(prompt) == []
    assert _refused(_lab_check(f"{prompt}\\nthen ssh h201 uptime"))


def test_lab_host_work_table_read_once_per_hook_run(
    lab_table: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ssh config and the table are read when the first agent() call is checked, not again
    for each of the following calls."""
    reads: list[Path] = []
    real = _lab()._read

    def counting(path: Path) -> str | None:
        reads.append(path)
        return real(path)

    monkeypatch.setattr(_lab(), "_read", counting)
    calls = "".join(
        f"await agent(`summarise part {i}`, {{ label: 'c{i}', model: 'sonnet' }})\n"
        for i in range(25)
    )
    assert _GUARD.check_workflow_script(calls, ALLOWLIST, filename="many.js") == []
    assert len(reads) == 1, reads


def _copied_hook(tmp_path: Path) -> Path:
    """An installed-tree shape independent of the canonical clone and test module."""
    hooks = tmp_path / "installed" / "hooks"
    shutil.copytree(_HOOKS_DIR, hooks, ignore=shutil.ignore_patterns("__pycache__"))
    return hooks / "scripts" / _HOOK_SCRIPT.name


def _haiku_payload(tool_name: str, route: str | None) -> dict[str, Any]:
    if tool_name == "Workflow":
        tool_input = {"script": _routed_call(route, "haiku")}
    else:
        tool_input = {
            "model": "haiku",
            "subagent_type": "general-purpose",
            "description": "mechanical readback",
            "prompt": f"{route}\nReturn the supplied text" if route else "Return text",
        }
    return {"tool_name": tool_name, "tool_input": tool_input}


def _stale_clone(tmp_path: Path, *, allowlist_has_haiku: bool = False) -> Path:
    """A registry root whose omniclaude clone is a full hooks tree without haiku.

    ``allowlist_has_haiku`` keeps haiku in the clone's allowlist, so only its
    routing contract is stale: a run that consults the clone's contract is then
    refused by the band table alone, never by the allowlist.

    The layout is the one the hook looks up: ``scripts/`` beside ``lib/`` and
    ``config/`` under ``plugins/onex/hooks/``, inside a git checkout (``.git``).
    The allowlist and the routing contract both lack haiku, so any run that
    consults this clone for its policy, its guard module or its script refuses a
    haiku call.
    """
    registry_root = tmp_path / "stale-registry"
    clone = registry_root / "omniclaude"
    hooks = clone / "plugins" / "onex" / "hooks"
    shutil.copytree(_HOOKS_DIR, hooks, ignore=shutil.ignore_patterns("__pycache__"))
    # A bare-minimum .git skeleton: the hook never runs git on the clone, and a
    # git subprocess here would inherit a hook's GIT_DIR (OMN-18434).
    git_dir = clone / ".git"
    for sub in ("objects", "refs/heads"):
        (git_dir / sub).mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    assert (clone / ".git").exists()
    config = hooks / "config"
    if not allowlist_has_haiku:
        (config / "agent_model_allowlist.json").write_text(
            json.dumps({"allowed_models": ["sonnet", "opus", "fable"]}),
            encoding="utf-8",
        )
    contract = config / "contract_agent_routing.yaml"
    original = contract.read_text(encoding="utf-8")
    stale = original.replace('models: ["haiku"]', "models: []")
    assert stale != original, "the stale clone must differ from the shipped contract"
    contract.write_text(stale, encoding="utf-8")
    for part in ("lib", "scripts", "config"):
        assert (hooks / part).is_dir(), part
    return registry_root


def _clone_hook(registry_root: Path) -> Path:
    return (
        registry_root
        / "omniclaude"
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / _HOOK_SCRIPT.name
    )


def _replace_once(path: Path, old: str, new: str) -> None:
    """Rewrite one line of a copied file, failing when the text is not there."""
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not found in {path.name}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_registered_hook_uses_installed_policy_with_stale_clone(tmp_path: Path) -> None:
    hook = _copied_hook(tmp_path)
    registry_root = _stale_clone(tmp_path)
    payload = _haiku_payload("Workflow", _ROUTE_B1_HAIKU)
    result = _run_hook(payload, tmp_path, hook_script=hook, registry_root=registry_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    # Control 1: the same payload through the clone's own full hooks tree is
    # refused, so the clone really is stale and a hook that ran from it would
    # exit 2 here instead of 0.
    from_clone = _run_hook(
        payload,
        tmp_path,
        hook_script=_clone_hook(registry_root),
        registry_root=registry_root,
    )
    assert from_clone.returncode == 2, from_clone.stdout + from_clone.stderr
    assert (
        "model: 'haiku' is not an allowed background model"
        in json.loads(from_clone.stdout)["reason"]
    )
    # Control 2: this exact loaded tree's policy decides, even with the same
    # stale clone and the same payload. A disabled hook cannot pass it.
    installed_allowlist = hook.parents[1] / "config" / "agent_model_allowlist.json"
    installed_allowlist.write_text(
        json.dumps({"allowed_models": ["sonnet", "opus", "fable"]}), encoding="utf-8"
    )
    refused = _run_hook(
        payload, tmp_path, hook_script=hook, registry_root=registry_root
    )
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert (
        "model: 'haiku' is not an allowed background model"
        in json.loads(refused.stdout)["reason"]
    )


def _consult_clone_for(guard: Path, names: tuple[str, ...]) -> None:
    """Point the named config files of an installed guard module at OMNI_HOME."""
    for name in names:
        _replace_once(
            guard,
            f'Path(__file__).resolve().parent.parent / "config" / "{name}"',
            'Path(__import__("os").environ["OMNI_HOME"]) / "omniclaude" '
            f'/ "plugins" / "onex" / "hooks" / "config" / "{name}"',
        )


@pytest.mark.parametrize(
    ("consulted", "reason_text"),
    [
        ("guard_module", "is not an allowed background model"),
        ("config_files", "is not an allowed background model"),
        # The clone's allowlist keeps haiku, so only the stale routing contract
        # (band B1 with ``models: []``) can refuse this call. A hook that read
        # the allowlist from its own tree and the contract from the clone is
        # the one lookup the two allowlist mutants cannot see.
        ("routing_contract_only", "band B1 dispatches no Claude agent"),
    ],
)
def test_stale_clone_test_goes_red_when_the_clone_is_consulted(
    consulted: str, reason_text: str, tmp_path: Path
) -> None:
    """Each way a hook could read the clone makes the stale-clone payload refuse.

    The installed tree is rewritten so the named lookup goes through
    ``OMNI_HOME``; the payload that the real hook passes is then refused. This
    is the red half of ``..._with_stale_clone``: a regression that reads the
    clone, by any route, fails that test with exit 2 instead of 0.
    """
    hook = _copied_hook(tmp_path)
    registry_root = _stale_clone(
        tmp_path, allowlist_has_haiku=consulted == "routing_contract_only"
    )
    clone_hooks = "${OMNI_HOME}/omniclaude/plugins/onex/hooks"
    guard = hook.parents[1] / "lib" / "workflow_model_guard.py"
    if consulted == "guard_module":
        _replace_once(
            hook,
            'GUARD_PY="${SCRIPT_DIR}/../lib/workflow_model_guard.py"',
            f'GUARD_PY="{clone_hooks}/lib/workflow_model_guard.py"',
        )
    elif consulted == "config_files":
        _consult_clone_for(
            guard, ("agent_model_allowlist.json", "contract_agent_routing.yaml")
        )
    else:
        _consult_clone_for(guard, ("contract_agent_routing.yaml",))
    result = _run_hook(
        _haiku_payload("Workflow", _ROUTE_B1_HAIKU),
        tmp_path,
        hook_script=hook,
        registry_root=registry_root,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    reason = json.loads(result.stdout)["reason"]
    assert reason_text in reason, reason
    if consulted == "routing_contract_only":
        # The allowlist is not what refused it.
        assert "is not an allowed background model" not in reason, reason


_SCRIPTS_DIR = _HOOKS_DIR / "scripts"
_LIB_DIR = _HOOKS_DIR / "lib"
#: A shell file the hook script loads: ``source``/``. "<dir var>/<name>.sh"`` or the
#: ``_PATH="<dir var>/../lib/<name>.sh"`` assignment hook-gate.sh makes for its bit table.
_SOURCED_SH = re.compile(
    r'(?:^\s*(?:source|\.)\s+|_BITS_PATH=)"[^"\n]*?/([A-Za-z0-9_.-]+\.sh)"',
    re.MULTILINE,
)
#: The only sourced files that read OMNI_HOME, and the one thing each reads it for.
#: Neither reads lib/ or config/ policy: onex-paths.sh derives ONEX_STATE_DIR (log
#: and state), hook_refusal.sh lists interpreters the refusal recorder may run
#: under, after the decision has been made.
_OMNI_HOME_READERS: Final[frozenset[str]] = frozenset(
    {"onex-paths.sh", "hook_refusal.sh"}
)


def _sourced_closure(entry: Path) -> dict[str, Path]:
    """Every shell file ``entry`` loads, directly or through a file it loads."""
    found: dict[str, Path] = {}
    pending = [entry]
    while pending:
        text = pending.pop().read_text(encoding="utf-8")
        for name in _SOURCED_SH.findall(text):
            if name in found:
                continue
            matches = [
                d / name for d in (_SCRIPTS_DIR, _LIB_DIR) if (d / name).is_file()
            ]
            assert len(matches) == 1, f"{name} did not resolve to one file: {matches}"
            found[name] = matches[0]
            pending.append(matches[0])
    return found


#: Words that make a shell line a lookup of policy (config/, the guard module, the
#: allowlist, the routing contract) rather than of state or a log path.
_POLICY_WORDS: Final[tuple[str, ...]] = (
    "config",
    "workflow_model_guard",
    "allowlist",
    "routing",
)
_SHELL_ASSIGN = re.compile(
    r"^(?:export\s+|local\s+|readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$"
)


def _code_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _mentions(line: str, names: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", line) for name in names)


def _omni_home_policy_reads(text: str, *, follow_variables: bool = True) -> list[str]:
    """Code lines that put a policy path on ``OMNI_HOME``.

    With ``follow_variables`` a variable assigned from ``OMNI_HOME`` (or from such
    a variable) is followed to a fixed point, so ``root="${OMNI_HOME}/x"`` then
    ``. "$root/config/y"`` is found; the single-line scan misses that join.
    """
    lines = _code_lines(text)
    tainted = {"OMNI_HOME"}
    while follow_variables:
        grew = False
        for line in lines:
            match = _SHELL_ASSIGN.match(line)
            if match and match[1] not in tainted and _mentions(match[2], tainted):
                tainted.add(match[1])
                grew = True
        if not grew:
            break
    return [
        line
        for line in lines
        if _mentions(line, tainted) and any(word in line for word in _POLICY_WORDS)
    ]


def test_omni_home_policy_scan_follows_a_variable_joined_to_config() -> None:
    """The single-line scan misses a path built from OMNI_HOME over two lines."""
    joined = (
        'root="${OMNI_HOME}/omniclaude"\n'
        'hooks="$root/plugins/onex/hooks"\n'
        '# comment: "$hooks/config" is only prose\n'
        '. "${hooks}/config/agent_model_allowlist.json"\n'
    )
    assert _omni_home_policy_reads(joined, follow_variables=False) == []
    assert _omni_home_policy_reads(joined) == [
        '. "${hooks}/config/agent_model_allowlist.json"'
    ]
    state_only = (
        'state="${OMNI_HOME}/.onex_state"\n'
        'log="$state/hooks.log"\n'
        'interp="${OMNI_HOME}/omniclaude/.venv/bin/python"\n'
    )
    assert _omni_home_policy_reads(state_only) == []


def test_hook_policy_lookups_never_read_the_registry_clone() -> None:
    """OMN-25166 AC1: no lookup of lib/ or config/ goes through OMNI_HOME.

    The hook script, the guard module and the registered hooks.json command carry
    no OMNI_HOME at all. Of the files the script sources, exactly two read it, one
    for the ONEX_STATE_DIR path and one for a refusal-recorder interpreter; a
    third reader, or either of those two reading a config/lib path, fails here.
    """
    assert "OMNI_HOME" not in _HOOK_SCRIPT.read_text(encoding="utf-8")
    assert "OMNI_HOME" not in (_LIB_DIR / "workflow_model_guard.py").read_text(
        encoding="utf-8"
    )
    hooks_json = _HOOKS_JSON.read_text(encoding="utf-8")
    assert "OMNI_HOME" not in hooks_json
    assert _registered_command().startswith("${CLAUDE_PLUGIN_ROOT}/hooks/scripts/")
    closure = _sourced_closure(_HOOK_SCRIPT)
    # Positive control: the walk reaches the files the hook really loads.
    assert {
        "error-guard.sh",
        "hook-gate.sh",
        "alert-channel.sh",
        "hook_refusal.sh",
        "onex-paths.sh",
        "repo_guard.sh",
        "hook_bits.sh",
    } <= set(closure)
    readers = {
        name for name, path in closure.items() if "OMNI_HOME" in path.read_text("utf-8")
    }
    assert readers == _OMNI_HOME_READERS, readers
    for name in sorted(readers):
        assert _omni_home_policy_reads(closure[name].read_text("utf-8")) == [], name


_CONTRACT_FILES: Final[tuple[str, ...]] = (
    "OMN-24977",
    "OMN-25097",
    "OMN-25166",
    "OMN-25193",
    "OMN-25213",
)


def _dod_entries(ticket: str) -> list[dict[str, Any]]:
    contract = yaml.safe_load(
        (_REPO_ROOT / "contracts" / f"{ticket}.yaml").read_text(encoding="utf-8")
    )
    return list(contract["dod_evidence"])


@pytest.mark.parametrize("ticket", _CONTRACT_FILES)
def test_install_proof_checks_name_no_closed_lane(ticket: str) -> None:
    """A check that only a lane that has ended could satisfy can never pass.

    The installed= row is read for any lane that records the proof, host-bound by
    the ``installed=<host>:<head>`` cell, not by the name of the lane that wrote it.
    """
    commands = [
        check["check_value"]
        for entry in _dod_entries(ticket)
        for check in entry["checks"]
        if check["check_type"] == "command" and "installed=" in check["check_value"]
    ]
    assert commands, ticket
    for command in commands:
        # No lane= cell and no lane-shaped name of any kind: the row is read for
        # whoever installs, not for one lane that has ended.
        assert not re.search(r"\blane=", command), ticket
        assert not re.search(r"\bfix\d{3,}", command), ticket
        assert "installed=[A-Za-z0-9._-]+:[0-9a-f]{40}" in command, ticket


def test_omn25166_ac1_is_bound_to_the_omni_home_comment() -> None:
    """The AC1 entry is bound to the pull request comment, not to pytest alone.

    It greps the files the comment names and then reads the comment at the head.
    """
    entry = next(e for e in _dod_entries("OMN-25166") if e["binds_ac"] == ["AC1"])
    kinds = [check["check_type"] for check in entry["checks"]]
    assert kinds.count("test_passes") == 1
    commands = [
        c["check_value"] for c in entry["checks"] if c["check_type"] == "command"
    ]
    assert len(commands) == 1, entry["id"]
    command = commands[0]
    for named in (
        "pre_tool_use_agent_model_guard.sh",
        "workflow_model_guard.py",
        "hooks.json",
    ):
        assert named in command, named
    assert "issues/3287/comments" in command
    _assert_comment_is_bound(command, "OMNI_HOME: head=", _OMNI_HOME_COMMENT_TOKENS)


#: What a pull request comment must show before the check reads it as the proof,
#: beyond its first line: the grep, the two sourced readers, the refusal explained.
_OMNI_HOME_COMMENT_TOKENS: Final[tuple[str, ...]] = (
    "grep -n OMNI_HOME",
    "onex-paths.sh",
    "hook_refusal.sh",
    "is not an allowed background model",
)
_LAB_COMMENT_TOKENS: Final[tuple[str, ...]] = (
    "tests/hooks/test_workflow_model_guard.py",
)
_BRANCH_TIP_CHECK: Final[str] = (
    'test "$(git rev-parse origin/omn-24977-haiku-band-routing-contract)" = "$head"'
)


def _commands(ticket: str, needle: str) -> list[str]:
    return [
        check["check_value"]
        for entry in _dod_entries(ticket)
        for check in entry["checks"]
        if check["check_type"] == "command" and needle in check["check_value"]
    ]


def _assert_comment_is_bound(
    command: str, prefix: str, tokens: tuple[str, ...]
) -> None:
    """The jq filter selects a comment by its first line AND by what it shows."""
    assert f'startswith(\\"{prefix}${{head}}\\")' in command, command
    for token in tokens:
        assert f'contains(\\"{token}\\")' in command, (token, command)


@pytest.mark.parametrize("ticket", _CONTRACT_FILES)
def test_omni_home_and_lab_comment_checks_read_what_the_comment_shows(
    ticket: str,
) -> None:
    """A prefix match alone accepts an empty comment; the check also reads its body.

    The OMNI_HOME comment must show the grep, name the two sourced readers and
    explain the refusal; the Lab comment must name the suite that ran, and every
    Lab check also requires the branch tip to be the head the comment names.
    """
    omni = _commands(ticket, "OMNI_HOME: head=")
    lab = _commands(ticket, "Lab: head=")
    for command in omni:
        _assert_comment_is_bound(command, "OMNI_HOME: head=", _OMNI_HOME_COMMENT_TOKENS)
    for command in lab:
        _assert_comment_is_bound(command, "Lab: head=", _LAB_COMMENT_TOKENS)
        assert _BRANCH_TIP_CHECK in command, ticket
    if ticket != "OMN-24977":
        assert lab, ticket


def _grep_prefix(command: str) -> str:
    """The part of a contract check that greps OMNI_HOME, before it reads comments."""
    lines = command.splitlines()
    cut = next(i for i, line in enumerate(lines) if line.lstrip().startswith("gh api"))
    return "\n".join(lines[:cut])


_OMNI_HOME_GREP_FILES: Final[tuple[str, ...]] = (
    "plugins/onex/hooks/scripts/pre_tool_use_agent_model_guard.sh",
    "plugins/onex/hooks/lib/workflow_model_guard.py",
    "plugins/onex/hooks/hooks.json",
)


def _run_bash(command: str, cwd: Path, env: dict[str, str] | None = None) -> int:
    return subprocess.run(
        ["bash", "-c", command],
        cwd=cwd,
        env={**scrub_git_location_env(os.environ), **(env or {})},
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    ).returncode


@pytest.mark.parametrize(
    ("ticket", "entry_ac"), [("OMN-25166", "AC1"), ("OMN-25193", "AC2")]
)
def test_omni_home_grep_check_requires_exit_one_not_exit_two(
    ticket: str, entry_ac: str, tmp_path: Path
) -> None:
    """grep exits 1 for no match and 2 for a missing file; only 1 is clean.

    Run the grep half of the real contract command four ways: on this tree (clean,
    exit 0), on a tree whose three files are clean, on a tree whose files hold
    OMNI_HOME, and on an empty tree where grep itself fails with 2.
    """
    entry = next(e for e in _dod_entries(ticket) if e["binds_ac"] == [entry_ac])
    command = next(
        c["check_value"]
        for c in entry["checks"]
        if c["check_type"] == "command" and "grep -n OMNI_HOME" in c["check_value"]
    )
    prefix = _grep_prefix(command)
    assert _run_bash(prefix, _REPO_ROOT) == 0, "positive control: this tree is clean"

    def tree(root: Path, body: str | None) -> Path:
        for rel in _OMNI_HOME_GREP_FILES:
            if body is not None:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(body, encoding="utf-8")
        root.mkdir(parents=True, exist_ok=True)
        return root

    assert _run_bash(prefix, tree(tmp_path / "clean", "no home here\n")) == 0
    assert _run_bash(prefix, tree(tmp_path / "reads", 'x="$OMNI_HOME"\n')) != 0
    # grep exits 2 here (no such file); a check that only asks "did grep match"
    # reads that as clean.
    assert _run_bash(prefix, tree(tmp_path / "missing", None)) != 0


_INSTALL_ROW = (
    "ROLLING_WORK_LEDGER.md:1:2026-11-17T05:02:15Z | STATUS | lane=any-lane | "
    "ticket=OMN-24977 | pr=omniclaude#3287 | installed={host}:{sha} | "
    "proof=any-b1-haiku-stale-clone | observed={observed} | text"
)
_INSTALL_OBSERVED = "Workflow B1 model=haiku effort=low exit=0 stdout=empty stale_clone_without_haiku=true"
_STUB_LANE_BRIEF = (
    # The real lane_brief.py grep is a fixed-string search that takes PATTERN and
    # --tail only; it has no -E, and argparse refuses one with exit 2.
    "import os, sys\n"
    "args = sys.argv[1:]\n"
    "if args[:1] != ['grep'] or '-E' in args:\n"
    "    sys.exit(2)\n"
    "needle = args[-1]\n"
    "for line in open(os.environ['STUB_ROWS'], encoding='utf-8'):\n"
    "    if needle in line:\n"
    "        print(line, end='')\n"
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=scrub_git_location_env(os.environ),
        capture_output=True,
        text=True,
        check=True,
        timeout=_TIMEOUT_S,
    ).stdout.strip()


def _install_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A repo with installed commit A, a plugin change C, and contract-only HEAD."""
    repo = tmp_path / "repo"
    (repo / "plugins" / "onex").mkdir(parents=True)
    (repo / "contracts").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "plugins" / "onex" / "hook.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "installed tree")
    shas = {"installed": _git(repo, "rev-parse", "HEAD")}
    (repo / "contracts" / "c.yaml").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "contracts only")
    shas["contracts_only"] = _git(repo, "rev-parse", "HEAD")
    (repo / "plugins" / "onex" / "hook.txt").write_text("v2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "plugin change")
    shas["plugin_changed"] = _git(repo, "rev-parse", "HEAD")
    return repo, shas


@pytest.mark.parametrize("ticket", _CONTRACT_FILES)
def test_install_proof_check_follows_the_head_through_contract_only_commits(
    ticket: str, tmp_path: Path
) -> None:
    """The row names the head that was installed; a later commit must not void it.

    A check that needs ``installed=<host>:<current HEAD>`` can never pass: the row is
    written after the push, and dropping ``pending`` is another commit. The check
    accepts a 40-hex installed sha that is an ancestor of HEAD with no change under
    ``plugins/onex`` since, and nothing else.
    """
    commands = _commands(ticket, "installed=")
    assert len(commands) == 1, ticket
    command = commands[0]
    repo, shas = _install_repo(tmp_path)
    plugin_root = tmp_path / "plugin"
    script = plugin_root / "skills" / "lane-brief" / "scripts" / "lane_brief.py"
    script.parent.mkdir(parents=True)
    script.write_text(_STUB_LANE_BRIEF, encoding="utf-8")
    rows = tmp_path / "rows.txt"
    env = {"OMNI_PLUGIN_ROOT": str(plugin_root), "STUB_ROWS": str(rows)}

    def verdict(head: str, row: str | None) -> int:
        _git(repo, "checkout", "-q", head)
        rows.write_text("" if row is None else row + "\n", encoding="utf-8")
        return _run_bash(command, repo, env)

    good = _INSTALL_ROW.format(
        host="Host-1.lab", sha=shas["installed"], observed=_INSTALL_OBSERVED
    )
    assert verdict(shas["installed"], good) == 0, "positive control: same head"
    assert verdict(shas["contracts_only"], good) == 0, "contract-only commit after"
    assert verdict(shas["plugin_changed"], good) != 0, "plugin tree changed since"
    assert verdict(shas["contracts_only"], None) != 0, "no row"
    abbreviated = _INSTALL_ROW.format(
        host="h1", sha=shas["installed"][:12], observed=_INSTALL_OBSERVED
    )
    assert verdict(shas["contracts_only"], abbreviated) != 0, "abbreviated sha"
    wrong_text = _INSTALL_ROW.format(
        host="h1", sha=shas["installed"], observed="config read back only"
    )
    assert verdict(shas["contracts_only"], wrong_text) != 0, "observed text differs"
    unknown = _INSTALL_ROW.format(host="h1", sha="0" * 40, observed=_INSTALL_OBSERVED)
    assert verdict(shas["contracts_only"], unknown) != 0, "sha not in this repo"


_BASE_RUN_HAIKU_IDS: Final[tuple[str, ...]] = (
    "test_haiku_route_in_the_haiku_band_passes",
    "test_haiku_band_accepts_the_efforts_in_its_set",
)


def test_base_run_needs_named_haiku_tests_to_fail() -> None:
    """The base run of OMN-24977 AC3 is red on haiku behaviour, not on file layout.

    Run unfiltered, the base tree already fails the tests that read contracts/ files
    the base does not have, so "at least one failure" proves nothing about haiku.
    The check selects ``-k haiku`` and requires the two named band tests to fail.
    """
    entry = next(e for e in _dod_entries("OMN-24977") if e["binds_ac"] == ["AC3"])
    command = next(
        c["check_value"] for c in entry["checks"] if c["check_type"] == "command"
    )
    assert "-k haiku" in command
    assert not re.search(r"\d+ failed", command)
    source = Path(__file__).read_text(encoding="utf-8")
    for test_id in _BASE_RUN_HAIKU_IDS:
        assert test_id in command, test_id
        assert f"def {test_id}(" in source, test_id


@pytest.mark.parametrize("ticket", _CONTRACT_FILES)
def test_no_contract_entry_is_left_pending(ticket: str) -> None:
    """No entry of these contracts is ``status: pending``, the install proof included.

    A pending entry is skipped by the done gate, so a suite that exempted the
    ``installed=`` entries stayed green with no install proof at all. The proof is
    the STATUS row the install check reads; while it is absent the entry fails
    instead of waiting.
    """
    pending = [e["id"] for e in _dod_entries(ticket) if e.get("status") == "pending"]
    assert pending == [], ticket


@pytest.mark.parametrize("tool_name", ["Workflow", "Agent"])
def test_registered_hook_route_model_mismatch(tool_name: str, tmp_path: Path) -> None:
    result = _run_hook(_haiku_payload(tool_name, _ROUTE_B3), tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert (
        "ROUTE model=sonnet does not match declared model 'haiku'"
        in json.loads(result.stdout)["reason"]
    )


@pytest.mark.parametrize("tool_name", ["Workflow", "Agent"])
@pytest.mark.parametrize("state", ["missing", "unparsable"])
def test_haiku_routing_contract_unreadable(
    tool_name: str, state: str, tmp_path: Path
) -> None:
    hook = _copied_hook(tmp_path)
    payload = _haiku_payload(tool_name, _ROUTE_B1_HAIKU)
    control = _run_hook(payload, tmp_path, hook_script=hook)
    assert control.returncode == 0, control.stdout + control.stderr
    contract = hook.parents[1] / "config" / "contract_agent_routing.yaml"
    if state == "missing":
        contract.unlink()
    else:
        contract.write_text("bands: [invalid\n", encoding="utf-8")
    # Even a call without a ROUTE must not bypass an unreadable policy.
    for route in (_ROUTE_B1_HAIKU, None):
        result = _run_hook(_haiku_payload(tool_name, route), tmp_path, hook_script=hook)
        assert result.returncode == 2, result.stdout + result.stderr
        reason = json.loads(result.stdout)["reason"]
        assert "guard could not evaluate" in reason
        assert "routing contract" in reason


def test_band_table_pinned() -> None:
    data = yaml.safe_load(
        _GUARD.DEFAULT_ROUTING_CONTRACT_PATH.read_text(encoding="utf-8")
    )
    expected = {
        "B0": ([], [], None, None, 300, None),
        "B1": (["haiku"], ["low", "medium"], 0, 4, 240, None),
        "B1c": ([], [], 0, 4, 240, None),
        "B2": (["sonnet"], ["medium", "high"], 5, 8, 1800, 4),
        "B3": (["sonnet"], ["high"], 9, 13, 3600, 15),
        "B4": (["opus"], ["high"], 14, 17, 7200, 5),
        "B5": (["opus", "fable"], ["xhigh", "high"], 18, 21, 10800, 5),
    }
    keys = (
        "models",
        "efforts",
        "score_min",
        "score_max",
        "timeout_s",
        "max_concurrent",
    )
    assert {
        band: tuple(row[key] for key in keys) for band, row in data["bands"].items()
    } == expected
    assert (
        data["bands"]["B1"]["destination"]
        == "Haiku lane, or onex delegate for pure text"
    )
    # The guard decides from its own parser, not PyYAML, so pin what that parser
    # reads: score ranges, timeouts, max_concurrent and destination, per band.
    parsed = _GUARD.load_routing()
    expected_parsed = {
        "B0": (None, None, 300, None, "landing controller / deterministic node"),
        "B1": (0, 4, 240, None, "Haiku lane, or onex delegate for pure text"),
        "B1c": (0, 4, 240, None, "Jev (node_typed_decision_effect)"),
        "B2": (5, 8, 1800, 4, "Codex drafts, Sonnet lane verifies"),
        "B3": (9, 13, 3600, 15, "Sonnet lane"),
        "B4": (14, 17, 7200, 5, "Opus lane"),
        "B5": (18, 21, 10800, 5, "Opus lane plus adversarial verify lane"),
    }
    assert {
        name: (
            band.score_min,
            band.score_max,
            band.timeout_s,
            band.max_concurrent,
            band.destination,
        )
        for name, band in parsed.bands.items()
    } == expected_parsed
    assert {
        name: (band.models, band.efforts) for name, band in parsed.bands.items()
    } == {
        name: (frozenset(models), frozenset(efforts))
        for name, (models, efforts, *_rest) in expected.items()
    }
    # Floors and caps: B1 has no concurrency cap and R and J are the only floor
    # dimensions. The V=3 floor stays a lane-brief rule (the contract header says
    # so); a change to either is a decision, so it fails here until re-pinned.
    assert parsed.bands["B1"].max_concurrent is None
    assert [
        (floor.dimension, floor.value, floor.min_band) for floor in parsed.hard_floors
    ] == [("R", 3, "B4"), ("J", 3, "B4")]
    no_agent_route = (
        "ROUTE: band=B1c score=0 dims=S0A0R0V0N0C0J0 dest=node model=haiku effort=low"
    )
    findings = _check_routed(_routed_call(no_agent_route, "haiku"))
    assert len(findings) == 1
    assert "an agent() or Agent call needs band B1 to B5" in findings[0].reason
