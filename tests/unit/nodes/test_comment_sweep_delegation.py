# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18512: exercise rendering through the comment-sweep bus adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml
from omnibase_core.runtime.golden_chain import (
    RecordedReplayInferenceTransport,
    load_fixture,
)
from omnibase_infra.backends.auto_configure import select_event_bus

from omniclaude.handlers.handler_contract_endpoint_resolver import (
    HandlerContractEndpointResolver,
)
from omniclaude.hooks.topics import TopicBase
from omniclaude.nodes.node_local_llm_inference_effect.backends.backend_vllm import (
    VllmInferenceBackend,
)
from omniclaude.nodes.node_skill_comment_sweep_orchestrator.handler_comment_sweep_skill import (
    HandlerCommentSweepSkill,
)
from omniclaude.runtime.wiring_dispatchers import SkillCommandDispatcher
from omniclaude.shared.models import ModelSkillRequest, SkillResultStatus
from omniclaude.shared.models.model_skill_node_contract import ModelSkillNodeContract

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[3]
NODE = ROOT / "src/omniclaude/nodes/node_skill_comment_sweep_orchestrator"
RENDER_TASK = "In one short sentence, greet the world."
RECORDED = load_fixture(ROOT / "tests/fixtures/golden_chain/vllm_chat_text.json")
FALLBACK = (
    RECORDED.raw_response["choices"][0]["message"]["content"]
    + "\n\nRESULT:\nstatus: success\nerror:\n"
)


class RecordedRenderer:
    """Caller-injected renderer using real inference parsing and recorded model bytes.

    The fallback notice and RESULT instruction belong to the skill protocol;
    this adapter extracts the actual rendering task and sends it through the
    existing backend. Canonical replay requires the exact recorded task, route,
    model and parameters. The RESULT block reports the backend's successful
    execution, rather than inventing model response bytes.
    """

    def __init__(self) -> None:
        self.backend = VllmInferenceBackend(endpoints=HandlerContractEndpointResolver())
        self.model = RECORDED.provenance.model_id.root
        self.calls: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        task = prompt.split("\n\nInclude a RESULT:", 1)[0].splitlines()[-1]
        assert task == RENDER_TASK
        transport = RecordedReplayInferenceTransport([RECORDED])
        with patch("httpx.Client", return_value=transport):
            result = self.backend.chat_completion_sync(
                messages=[{"role": "user", "content": task}],
                endpoint_url=RECORDED.provenance.endpoint.removesuffix(
                    "/v1/chat/completions"
                ),
                model=self.model,
                max_tokens=512,
                temperature=0.0,
            )
        assert result.error is None
        assert transport.calls
        return result.content + "\n\nRESULT:\nstatus: success\nerror:\n"

    async def session_query(self, *, prompt: str, **kwargs: object) -> object:
        return SimpleNamespace(output=await self(prompt))


@pytest.fixture
async def renderer():
    adapter = RecordedRenderer()
    try:
        yield adapter
    finally:
        await adapter.backend._client.aclose()


def request() -> ModelSkillRequest:
    return ModelSkillRequest(
        skill_name="comment-sweep",
        skill_path="plugins/onex/skills/comment_sweep/SKILL.md",
        args={
            "render-prompt": RENDER_TASK,
            "work-unit-id": "reply-1",
            "delegation-lane": "dev",
            "ticket": "OMN-18512",
        },
        correlation_id=uuid4(),
    )


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OMNI_HOME", str(tmp_path))
    monkeypatch.setenv("ONEX_DISPATCH_VENV", str(tmp_path / "dispatch"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    return tmp_path


def install_cli(
    root: Path,
    *,
    endpoint: str = "local",
    status: str = "success",
    mode: str = "valid",
) -> str:
    """A console-script fixture: records argv and writes an actual receipt."""
    run_id = str(uuid4())
    correlation_id = str(uuid4())
    script = f"""#!{sys.executable}
import json, pathlib, sys, os, time
root = pathlib.Path({str(root)!r})
(root / 'argv.json').write_text(json.dumps(sys.argv[1:]))
work_side = list((root / '.onex_state/comment-sweep').glob('*.json'))
assert len(work_side) == 1
assert json.loads(work_side[0].read_text())['render_delegation']['outcome'] == 'pending'
if {mode!r} == 'unbound' and 'kafka' in sys.argv:
    print('no bound consumer', file=sys.stderr)
    sys.exit(2)
if {mode!r} == 'exit':
    print('fixture chain refused', file=sys.stderr)
    sys.exit(2)
if {mode!r} == 'timeout':
    time.sleep(60)
state = pathlib.Path(sys.argv[sys.argv.index('--state-root') + 1])
run = state / 'runs' / {run_id!r}
run.mkdir(parents=True)
receipt = {{'run_id': {run_id!r}, 'status': {status!r},
           'endpoint': {endpoint!r}, 'model': 'fixture-model',
           'correlation_id': {correlation_id!r},
           'receipt': {{'correlation_id': {correlation_id!r}, 'exit_code': 0,
                       'run_id': {run_id!r}, 'status': {status!r},
                       'result': {{'terminal_payload': {{'payload':
                           {{'status': 'completed', 'response': 'Delegated reply.',
                             'correlation_id': {correlation_id!r}, 'prompt_text': sys.argv[2]}}}}}}}}}}
(run / 'receipt.json').write_text(json.dumps(receipt))
if {mode!r} == 'missing-receipt':
    (run / 'receipt.json').unlink()
if {mode!r} == 'stale-receipt':
    os.utime(run / 'receipt.json', (1, 1))
if {mode!r} == 'mismatched-receipt':
    receipt['correlation_id'] = 'mismatched'
    (run / 'receipt.json').write_text(json.dumps(receipt))
if {mode!r} == 'mismatched-terminal':
    receipt['receipt']['result']['terminal_payload']['payload']['prompt_text'] = 'another request'
    (run / 'receipt.json').write_text(json.dumps(receipt))
if {mode!r} == 'unbound':
    receipt['receipt']['result'] = receipt['receipt']['result']['terminal_payload']['payload']
    (run / 'receipt.json').write_text(json.dumps(receipt))
print(json.dumps({{'run_id': {run_id!r}, 'status': {status!r},
                  'correlation_id': {correlation_id!r},
                  'result': {{'status': 'completed', 'response': 'Delegated reply.'}}}}))
"""
    wrapper = root / "omnibase_infra/scripts/onex"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(script)
    wrapper.chmod(0o755)
    binary = root / "dispatch/bin/onex"
    binary.parent.mkdir(parents=True)
    binary.write_text(script)
    binary.chmod(0o755)
    return run_id


@pytest.mark.asyncio
async def test_missing_binary_keeps_work_and_reports_fallback(
    registry: Path, renderer: RecordedRenderer
) -> None:
    result = await HandlerCommentSweepSkill(task_dispatcher=renderer).handle(request())
    assert result.status == SkillResultStatus.SUCCESS
    assert result.output == FALLBACK
    record = result.render_delegation
    assert record is not None
    assert record.outcome == "fallback"
    assert record.work_unit_id == "reply-1"
    assert record.reason == "missing_binary"
    assert record.onex_binary == str(registry / "dispatch/bin/onex")
    assert record.searched_venv == str(registry / "dispatch")
    assert record.run_id is None
    assert "onex" in record.detail
    assert len(renderer.calls) == 1
    artifact = json.loads(Path(record.artifact_path).read_text())
    assert artifact["render_delegation"]["outcome"] == "fallback"
    assert artifact["output"] == FALLBACK


@pytest.mark.asyncio
async def test_declared_cli_works_without_ambient_path(
    registry: Path, renderer: RecordedRenderer
) -> None:
    run_id = install_cli(registry)
    result = await HandlerCommentSweepSkill(task_dispatcher=renderer).handle(request())
    assert result.status == SkillResultStatus.SUCCESS
    assert result.output == "Delegated reply."
    assert result.render_delegation.outcome == "delegated"
    assert str(result.render_delegation.run_id) == run_id
    assert result.render_delegation.endpoint == "local"
    assert not renderer.calls
    argv = json.loads((registry / "argv.json").read_text())
    assert argv[0] == "delegate"
    assert argv[argv.index("--task-type") + 1] == "document"
    assert argv[argv.index("--state-root") + 1] == str(registry / ".onex_state")
    assert "--backend-id" not in argv


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "exit",
        "missing-receipt",
        "stale-receipt",
        "mismatched-receipt",
        "mismatched-terminal",
        "timeout",
    ],
)
async def test_refused_or_unproven_delegation_keeps_the_fallback(
    registry: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    renderer: RecordedRenderer,
) -> None:
    install_cli(registry, mode=mode)
    if mode == "timeout":
        monkeypatch.setattr(
            "omniclaude.nodes.node_skill_comment_sweep_orchestrator.handler_comment_sweep_skill._DELEGATE_TIMEOUT_SECONDS",
            0.05,
        )
    result = await HandlerCommentSweepSkill(task_dispatcher=renderer).handle(request())
    assert result.status == SkillResultStatus.SUCCESS
    assert result.output == FALLBACK
    assert result.render_delegation.outcome == "fallback"
    assert result.render_delegation.reason == "delegate_failed"
    assert result.render_delegation.run_id is None
    if mode == "exit":
        assert "fixture chain refused" in result.render_delegation.detail
    assert len(renderer.calls) == 1


@pytest.mark.asyncio
async def test_hooks_cli_cannot_replace_a_missing_declared_cli(
    registry: Path, monkeypatch: pytest.MonkeyPatch, renderer: RecordedRenderer
) -> None:
    install_cli(registry)
    monkeypatch.setenv("PATH", str(registry / "dispatch/bin"))
    monkeypatch.setenv("ONEX_DISPATCH_VENV", str(registry / "missing-cli"))
    result = await HandlerCommentSweepSkill(task_dispatcher=renderer).handle(request())
    assert result.render_delegation.outcome == "fallback"
    assert result.render_delegation.reason == "missing_binary"
    assert result.render_delegation.searched_venv == str(registry / "missing-cli")
    assert not (registry / "argv.json").exists()


@pytest.mark.asyncio
async def test_work_side_write_failure_is_not_success(
    registry: Path, renderer: RecordedRenderer
) -> None:
    (registry / ".onex_state").write_text("unreadable work-side source")
    result = await HandlerCommentSweepSkill(task_dispatcher=renderer).handle(request())
    assert result.status == SkillResultStatus.FAILED
    assert result.error == "work-side render evidence could not be written"
    assert result.render_delegation.artifact_path is None


@pytest.mark.asyncio
async def test_fallback_error_retains_route_evidence(
    registry: Path, renderer: RecordedRenderer
) -> None:
    renderer.model = "not-the-recorded-model"
    result = await HandlerCommentSweepSkill(task_dispatcher=renderer).handle(request())
    assert result.status == SkillResultStatus.FAILED
    assert result.render_delegation.outcome == "fallback"
    assert result.render_delegation.reason == "missing_binary"
    assert result.output is None


@pytest.mark.asyncio
@pytest.mark.parametrize("delegated", [False, True])
async def test_bus_dispatch_publishes_work_side_route(
    registry: Path, delegated: bool, renderer: RecordedRenderer
) -> None:
    if delegated:
        install_cli(registry)
    contract = ModelSkillNodeContract.model_validate(
        yaml.safe_load((NODE / "contract.yaml").read_text())
    )
    bus = select_event_bus(bus_type="inmemory")
    await bus.start()
    events = []

    async def capture(message):
        events.append((message.topic, json.loads(message.value)))

    for topic in (
        TopicBase.SKILL_COMPLETED,
        "onex.evt.omniclaude.comment_sweep-completed.v1",
    ):
        await bus.subscribe(topic, on_message=capture, group_id="comment-render-test")
    dispatcher = SkillCommandDispatcher(
        contracts={"comment-sweep": contract},
        claude_code_backend=renderer,
        vllm_backend=None,
        event_bus=bus,
    )
    req = request()
    results = []

    async def consume(message):
        results.append(await dispatcher.handle(json.loads(message.value)))

    command_topic = "onex.cmd.omniclaude.comment_sweep.v1"
    await bus.subscribe(
        command_topic, on_message=consume, group_id="comment-render-command"
    )
    try:
        await bus.publish(
            command_topic,
            key=None,
            value=json.dumps(
                {
                    "payload": {"args": req.args},
                    "__debug_trace": {
                        "topic": command_topic,
                        "correlation_id": str(req.correlation_id),
                    },
                }
            ).encode("utf-8"),
        )
    finally:
        await bus.close()
    assert results == ["dispatched:comment-sweep:success"]
    terminal = next(
        payload for _, payload in events if payload.get("render_delegation")
    )
    assert terminal["render_delegation"]["outcome"] == (
        "delegated" if delegated else "fallback"
    )
    assert terminal["render_delegation"]["work_unit_id"] == "reply-1"
    if delegated:
        assert terminal["backend_selected"] == "onex_delegate"
        assert terminal["render_delegation"]["endpoint"] == "local"
        assert not renderer.calls
    else:
        assert terminal["render_delegation"]["reason"] == "missing_binary"
        assert len(renderer.calls) == 1
    assert terminal["artifact_path"] == terminal["render_delegation"]["artifact_path"]
    assert any(
        topic == "onex.evt.omniclaude.comment_sweep-completed.v1" for topic, _ in events
    )


@pytest.mark.asyncio
async def test_unbound_consumer_retries_once_in_process(
    registry: Path, renderer: RecordedRenderer
) -> None:
    install_cli(registry, mode="unbound")
    result = await HandlerCommentSweepSkill(task_dispatcher=renderer).handle(request())
    assert result.render_delegation.outcome == "delegated"
    argv = json.loads((registry / "argv.json").read_text())
    assert argv[argv.index("--bus") + 1] == "inmemory"
    assert argv[argv.index("--locus") + 1] == "in-process"
    assert "--lane" not in argv
    assert not renderer.calls


def test_contract_exposes_typed_work_side_output() -> None:
    contract = yaml.safe_load((NODE / "contract.yaml").read_text())
    assert contract["output_model"]["name"] == "ModelCommentSweepResult"
    assert contract["render_delegation"]["output_field"] == "render_delegation"
    assert (
        "onex.cmd.omniclaude.comment_sweep.v1"
        in contract["event_bus"]["subscribe_topics"]
    )


def test_regression_check_is_wired_to_ci_and_precommit() -> None:
    from scripts.ci.ci_summary_gate import GATE_JOBS, STRICT_SUCCESS_JOBS

    assert "Comment Render Delegation (OMN-18512)" in GATE_JOBS
    assert "Comment Render Delegation (OMN-18512)" in STRICT_SUCCESS_JOBS
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["comment-render-delegation"]
    assert "if" not in job
    assert any(
        "tests/unit/nodes/test_comment_sweep_delegation.py" in step.get("run", "")
        for step in job["steps"]
    )
    hooks = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(
        hook
        for repo in hooks["repos"]
        for hook in repo["hooks"]
        if hook["id"] == "comment-render-delegation"
    )
    assert "tests/unit/nodes/test_comment_sweep_delegation.py" in hook["entry"]
    assert hook["pass_filenames"] is False
