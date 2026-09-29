# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""One jq per payload reads exactly what one jq per field read (OMN-20114).

Three hooks that run on every tool call read their payload fields with one
``jq`` each: eleven in the bus mirror, six in skill-started, eleven in the
quality hook. OMN-20114 replaced each run with a single ``jq`` that prints
shell assignments. This test is the proof that nothing a hook decides on moved:
for every payload shape below it runs the per-field reads as they were written
before the change (transcribed here, verbatim, from the pre-change scripts) and
the consolidated block as it is written in the shipped script now, under the
macOS system bash (3.2, what ``#!/bin/bash`` runs on the operator Mac) and the
bash on PATH, and compares every variable byte for byte.

The payloads cover what a per-field read could see: a full object, missing and
fallback keys, non-string values including nested objects (``jq -r`` prints
those indented), trailing newlines, shell metacharacters, and inputs that are
null, false, empty, unparseable, an array, a string or a number.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "scripts"
)

_PAYLOADS = [
    '{"session_id":"s1","sessionId":"S","agent_id":"a","transcript_path":"/t p",'
    '"cwd":"/x/y/","turn_id":"t","tool_name":"Bash","duration_ms":12,'
    '"tool_response":{"interrupted":true,"error":"boom"},"tool_use_id":"tu",'
    '"tool_input":{"skill":"onex:x"},"usage":{"input_tokens":5,"output_tokens":"7"}}',
    '{"sessionId":"s2","agentId":"b\\n","transcriptPath":"x\'y","cwd":"/",'
    '"duration_ms":1.5,"tool_response":"str","tool_input":{"name":"nm"},'
    '"error":"top","durationMs":3.25}',
    '{"session_id":{"a":[1,{"b":null}],"c":{}},"cwd":["x",[]],'
    '"tool_name":{"k":"v\\u00e9"},"duration_ms":[5],"tool_use_id":1e3,'
    '"tool_input":{"skill":{"z":1}},"agent_id":true,'
    '"tool_response":{"interrupted":{"x":1},"error":{"code":1}},"usage":{"input_tokens":{"x":1}}}',
    '{"cwd":"a$(touch /nonexistent/pwn)b","session_id":"$HOME `id`","tool_use_id":"x;y"}',
    '{"session_id":"trail\\n\\n","cwd":"//","tool_input":{"skill":false,"name":null}}',
    '{"session_id":null,"sessionId":"fallback","tool_use_id":false,"turn_id":[[]]}',
    "null",
    "false",
    "",
    "not json",
    "[1,2]",
    '"str"',
    "7",
]

_BASHES = sorted(
    {b for b in ("/bin/bash", shutil.which("bash")) if b and Path(b).exists()}
)


def _block(script: str, start: str, end: str) -> str:
    text = (_SCRIPTS / script).read_text(encoding="utf-8")
    a = text.index(start)
    return text[a : text.index(end, a)]


def _run(bash: str, body: str, variables: list[str], payload: str) -> str:
    script = (
        "set -uo pipefail\n"
        'INPUT="$1"\nTOOL_INFO="$1"\nHOOK_ACTOR_ARG="$2"\ncd /\n'
        + body
        + "\nfor v in "
        + " ".join(variables)
        + '; do printf "%s=[%s]\\n" "$v" "${!v-UNSET}"; done\n'
    )
    done = subprocess.run(  # noqa: S603
        [bash, "-c", script, "probe", payload, ""],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return f"{done.stdout}{done.stderr}rc={done.returncode}"


def _per_field(reads: list[tuple[str, str, str]], printer: str = "echo") -> str:
    return "".join(
        f'{var}=$({printer} "$INPUT" | jq -r \'{expr}\' 2>/dev/null) || {var}="{default}"\n'
        for var, expr, default in reads
    )


_BUS_MIRROR_VARS = ["SESSION_ID", "AGENT_ID", "TRANSCRIPT_PATH", "CWD", "TURN_ID",
                    "TOOL_NAME", "_BM_DURATION_MS", "_BM_INTERRUPTED", "TOOL_USE_ID"]  # fmt: skip
_BUS_MIRROR_READS = [
    ("SESSION_ID", '.session_id // .sessionId // ""', ""),
    ("AGENT_ID", '.agent_id // .agentId // ""', ""),
    ("TRANSCRIPT_PATH", '.transcript_path // .transcriptPath // ""', ""),
    ("CWD", '.cwd // ""', ""),
    ("TURN_ID", '.turn_id // ""', ""),
    ("TOOL_NAME", '.tool_name // "unknown"', "unknown"),
    ("_BM_DURATION_MS", ".duration_ms // 0", "0"),
    ("_BM_INTERRUPTED", ".tool_response.interrupted // false", "false"),
    ("TOOL_USE_ID", '.tool_use_id // ""', ""),
]

_SKILL_READS = [
    ("RUN_ID", '.tool_use_id // ""', ""),
    ("SESSION_ID", '.session_id // .sessionId // ""', ""),
    ("AGENT_ID", '.agent_id // .agentId // ""', ""),
    ("TRANSCRIPT_PATH", '.transcript_path // .transcriptPath // ""', ""),
    ("SKILL_NAME", '.tool_input.skill // .tool_input.name // ""', ""),
]

_QUALITY_READS = [
    ("_Q_TOOL_NAME", '.tool_name // "unknown"', "unknown"),
    ("_Q_SESSION_ID", '.sessionId // .session_id // ""', ""),
    ("_Q_AGENT_ID", '.agent_id // .agentId // ""', ""),
    ("_Q_TRANSCRIPT_PATH", '.transcript_path // .transcriptPath // ""', ""),
    ("_Q_SKILL_NAME", '.tool_input.skill // .tool_input.name // "unknown"', "unknown"),
    ("_Q_SKILL_ERROR", '.tool_response.error // ""', ""),
    ("_Q_SKILL_RUN_ID", '.tool_use_id // ""', ""),
    ("_Q_SKILL_SESSION_ID", '.session_id // .sessionId // ""', ""),
    ("_Q_TOOL_ERROR", ".tool_response.error // .error // empty", ""),
    ("_Q_DURATION_MS", '.duration_ms // .durationMs // ""', ""),
    ("_Q_INPUT_TOKENS", ".usage.input_tokens // 0", "0"),
    ("_Q_OUTPUT_TOKENS", ".usage.output_tokens // 0", "0"),
]


@pytest.mark.skipif(
    shutil.which("jq") is None, reason="the hooks exit before any read without jq"
)
@pytest.mark.parametrize("bash", _BASHES)
@pytest.mark.parametrize("payload", _PAYLOADS)
def test_bus_mirror_reads_match_the_per_field_reads(bash: str, payload: str) -> None:
    before = (
        "if ! echo \"$INPUT\" | jq -e . >/dev/null 2>&1; then\n    INPUT='{}'\nfi\n"
        + _per_field(_BUS_MIRROR_READS)
    )
    after = _block(
        "post_tool_use_bus_mirror.sh", "_BM_FIELDS=$(echo", "unset _BM_FIELDS _BM_VALID"
    )
    variables = ["INPUT", *_BUS_MIRROR_VARS]
    assert _run(bash, after, variables, payload) == _run(
        bash, before, variables, payload
    )


@pytest.mark.skipif(
    shutil.which("jq") is None, reason="the hooks exit before any read without jq"
)
@pytest.mark.parametrize("bash", _BASHES)
@pytest.mark.parametrize("payload", _PAYLOADS)
def test_skill_started_reads_match_the_per_field_reads(bash: str, payload: str) -> None:
    before = (
        "if ! printf '%s' \"$INPUT\" | jq -e . >/dev/null 2>&1; then\n    exit 0\nfi\n"
        + _per_field(_SKILL_READS, printer="printf '%s'")
    )
    after = _block(
        "pre_tool_use_skill_started.sh",
        '_SS_FIELDS="$(printf',
        "unset _SS_FIELDS _SS_VALID",
    )
    variables = [var for var, _, _ in _SKILL_READS]
    assert _run(bash, after, variables, payload) == _run(
        bash, before, variables, payload
    )


@pytest.mark.skipif(
    shutil.which("jq") is None, reason="the hooks exit before any read without jq"
)
@pytest.mark.parametrize("bash", _BASHES)
@pytest.mark.parametrize("payload", _PAYLOADS)
def test_quality_reads_match_the_per_field_reads(bash: str, payload: str) -> None:
    # The quality hook reads only after its own `jq -e .` test passed, so a
    # payload that test refuses never reaches either version.
    probe = subprocess.run(  # noqa: S603
        ["jq", "-e", "."],
        input=payload + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("the quality hook exits before its reads on this payload")
    before = _per_field(_QUALITY_READS).replace('"$INPUT"', '"$TOOL_INFO"')
    after = _block("post-tool-use-quality.sh", "_Q_FIELDS=$(echo", "unset _Q_FIELDS")
    variables = [var for var, _, _ in _QUALITY_READS]
    assert _run(bash, after, variables, payload) == _run(
        bash, before, variables, payload
    )


def test_the_consolidated_blocks_are_where_this_test_reads_them() -> None:
    """A renamed marker would make every comparison above read the wrong text."""
    for script, marker in (
        ("post_tool_use_bus_mirror.sh", "_BM_FIELDS=$(echo"),
        ("pre_tool_use_skill_started.sh", '_SS_FIELDS="$(printf'),
        ("post-tool-use-quality.sh", "_Q_FIELDS=$(echo"),
    ):
        text = (_SCRIPTS / script).read_text(encoding="utf-8")
        assert text.count(marker) == 1, (script, marker)
        assert "jq -r '.session_id" not in text.split(marker, 1)[1].split("\n\n", 1)[0]
