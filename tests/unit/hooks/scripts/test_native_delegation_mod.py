# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The native adapter must answer once or leave the original turn to Claude.

Failures: warning output, duplicate fallback, lost legacy context, accepting
truncated/invalid output, sending images, and intercepting subagent/tool steps.
The real Claude rendering/history proof is separate from these boundary cases.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[4] / "src/index.ts"


def run_adapter(case: dict) -> dict:
    script = r"""
import fs from 'node:fs';
const input = JSON.parse(process.argv[1]);
const callbacks = {};
if (fs.existsSync(input.module)) {
  const mod = await import(input.module);
  mod.register((name, callback) => { callbacks[name] = callback; });
}
const calls = [], appended = [], chunks = [], logs = [];
let fallbacks = 0;
const $ = {
  plugin: {root: '/isolated/plugin'},
  ui: {log: async (message, options) => {logs.push({message,options});}},
  fs: {read: async () => JSON.stringify({python:'/isolated/python'})},
  session: {
    id: async () => 'session-test',
    info: async () => ({transcriptPath: '/isolated/transcript.jsonl'}),
    messages: async () => [{role:'user',content:input.content ?? [{type:'text',text:'Explain mutex and semaphore.'}]}],
    append: async (row) => { appended.push(row); return {}; },
  },
  process: {
    hookEnv: async () => ({CLAUDE_PLUGIN_ROOT:'/isolated/plugin'}),
    run: async (argv, options) => {
      calls.push({argv,options});
      if (input.throws) throw Error('unavailable');
      return input.process ?? {exitCode:0,stdout:JSON.stringify({decision:'block',reason:'Delegated answer.'})};
    },
  },
};
const event = {turnId:'turn-test',index:input.index ?? 0,...(input.agentId ? {agentId:input.agentId}: {})};
if (callbacks['prompt.submit']) await callbacks['prompt.submit']($,{
  text:'Explain mutex and semaphore.', origin:{kind:input.origin ?? 'sdk'},
  ...(input.meta ? {isMeta:true}:{}), ...(input.attachments ? {attachments:input.attachments}:{})
}, async e=>({text:e.text}));
if (callbacks['turn.start']) await callbacks['turn.start']($,{...event,text:'Explain mutex and semaphore.'}, async e=>({turnId:e.turnId}));
async function* next(e) { fallbacks++; yield {kind:'text',index:0,text:'Claude fallback'}; return {turnId:e.turnId,answer:'Claude fallback'}; }
const stream = callbacks['turn.step'] ? callbacks['turn.step']($,event,next) : next(event);
let result;
while (true) { const item = await stream.next(); if (item.done) {result=item.value;break;} chunks.push(item.value); }
console.log(JSON.stringify({calls,appended,chunks,result,fallbacks,logs}));
"""
    runtime = shutil.which("node") or shutil.which("bun")
    assert runtime, "The adapter boundary checks require Node or Bun"
    flags = (
        ["--input-type=module", "-e"] if Path(runtime).name == "node" else ["--eval"]
    )
    process = subprocess.run(
        [runtime, *flags, script, json.dumps({"module": str(MODULE), **case})],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def test_accepted_answer_is_a_normal_assistant_turn():
    observed = run_adapter({})
    assert observed["result"]["answer"] == "Delegated answer."
    assert observed["fallbacks"] == 0
    assert observed["chunks"] == [
        {"kind": "text", "index": 0, "text": "Delegated answer."},
        {"kind": "stop", "stopReason": "end_turn", "usage": None},
    ]
    payload = json.loads(observed["calls"][0]["options"]["stdin"])
    assert payload["prompt"] == "Explain mutex and semaphore."
    assert payload["session_id"] == "session-test"
    assert payload["transcript_path"] == "/isolated/transcript.jsonl"
    assert (
        observed["calls"][0]["options"]["env"]["PLUGIN_PYTHON_BIN"]
        == "/isolated/python"
    )


@pytest.mark.parametrize(
    "case",
    [
        {"agentId": "worker"},
        {"index": 1},
        {"meta": True},
        {"origin": "peer"},
        {"origin": "plugin"},
        {"attachments": [{"id": "image-1", "kind": "image"}]},
        {"content": [{"type": "image", "source": {"type": "base64"}}]},
    ],
)
def test_ineligible_steps_make_no_delegation_call(case):
    observed = run_adapter(case)
    assert observed["calls"] == []
    assert observed["fallbacks"] == 1


@pytest.mark.parametrize(
    "case",
    [
        {"throws": True},
        {
            "process": {
                "exitCode": 1,
                "stdout": '{"decision":"block","reason":"partial"}',
            }
        },
        {"process": {"exitCode": 0, "stdout": "not json"}},
        {"process": {"exitCode": 0, "stdout": '{"decision":"block","reason":""}'}},
        {
            "process": {
                "exitCode": 0,
                "stdout": '{"decision":"block","reason":"partial"}',
                "isStdoutTruncated": True,
            }
        },
        {"process": {"exitCode": 0, "stdout": ""}},
    ],
)
def test_nonanswers_fall_back_exactly_once(case):
    observed = run_adapter(case)
    assert observed["result"]["answer"] == "Claude fallback"
    assert observed["fallbacks"] == 1


def test_legacy_history_reaches_claude_on_fallback():
    context = "Earlier delegated exchange"
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }
    observed = run_adapter({"process": {"exitCode": 0, "stdout": json.dumps(output)}})
    assert observed["appended"] == [
        {"message": {"type": "user", "content": [{"type": "text", "text": context}]}}
    ]
    assert observed["fallbacks"] == 1


def test_adapter_failure_is_diagnosable_without_logging_prompt_or_answer():
    observed = run_adapter({"throws": True})
    assert len(observed["logs"]) == 1
    assert observed["logs"][0]["options"] == {"to": "debug"}
    assert "delegation" in observed["logs"][0]["message"].lower()
    assert "Explain mutex" not in observed["logs"][0]["message"]
    assert observed["fallbacks"] == 1
