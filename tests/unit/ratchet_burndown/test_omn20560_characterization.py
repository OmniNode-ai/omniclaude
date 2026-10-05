# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Characterization tests for the OMN-20560 ratchet burn-down.

Written and committed before any burn-down change, and proven green on the
unchanged code (dev 6b411a459). They pin the observable behaviour of every
module the burn-down touches, without naming any class or file the burn-down
renames or deletes, so the same file must pass unchanged at the PR head. That
is the idempotency proof the operator asked for on 2026-10-05.

Covered:

- the two plan lints (plan-verified-state, plan-canonical-scripts) on the real
  tree and on planted plans, with no allowlist file present;
- the five channel adapter contracts: every field except ``runtime_profiles``
  is byte-for-byte the same, and runtime-profile ownership is ``main`` only;
- the Slack outbound reply path, the correction generator's no-intelligence
  fallback, the agent trigger matcher, the PR watch registry, and the public
  functions of ``omniclaude.lib.kafka_producer_utils``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import pathlib
import textwrap
from types import ModuleType
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _load_script(name: str) -> ModuleType:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_omn20560_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_lint(module: ModuleType, argv: list[str]) -> tuple[int, str]:
    captured = io.StringIO()
    with patch("sys.stderr", captured):
        code = module.main(argv)
    return code, captured.getvalue()


def _write_plan(root: pathlib.Path, name: str, body: str) -> pathlib.Path:
    plan_dir = root / "docs" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / name
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Plan lints (rows 20 and 21 of the inventory)
# ---------------------------------------------------------------------------


def test_plan_verified_state_real_tree_is_clean() -> None:
    gate = _load_script("lint_plan_verified_state")
    code, stderr = _run_lint(
        gate,
        [
            "lint_plan_verified_state.py",
            "--repo-root",
            str(REPO_ROOT),
            "--today",
            "2026-10-05",
        ],
    )
    assert code == 0, stderr


def test_plan_canonical_scripts_real_tree_is_clean() -> None:
    gate = _load_script("lint_plan_canonical_scripts")
    code, stderr = _run_lint(
        gate, ["lint_plan_canonical_scripts.py", "--repo-root", str(REPO_ROOT)]
    )
    assert code == 0, stderr


def test_plan_verified_state_blocks_and_passes_without_allowlist(
    tmp_path: pathlib.Path,
) -> None:
    gate = _load_script("lint_plan_verified_state")
    bad = _write_plan(tmp_path, "bad.md", "# Bad\n\nNo section.\n")
    good = _write_plan(
        tmp_path,
        "good.md",
        """
        # Good

        ## Current Verified State

        verified: 2026-10-05 via gh pr checks 1 --repo OmniNode-ai/omniclaude
        """,
    )
    argv = [
        "lint_plan_verified_state.py",
        "--repo-root",
        str(tmp_path),
        "--today",
        "2026-10-05",
    ]
    code, stderr = _run_lint(gate, [*argv, str(bad)])
    assert code == 1
    assert "bad.md" in stderr
    code, stderr = _run_lint(gate, [*argv, str(good)])
    assert code == 0, stderr


def test_plan_canonical_scripts_blocks_and_passes_without_allowlist(
    tmp_path: pathlib.Path,
) -> None:
    gate = _load_script("lint_plan_canonical_scripts")
    bad = _write_plan(tmp_path, "bad.md", "# Bad\nWe will add scripts/x.py here.\n")
    good = _write_plan(tmp_path, "good.md", "# Good\nBuild node_bar.\n")
    argv = ["lint_plan_canonical_scripts.py", "--repo-root", str(tmp_path)]
    code, stderr = _run_lint(gate, [*argv, str(bad)])
    assert code == 1
    assert "scripts/x.py" in stderr
    code, stderr = _run_lint(gate, [*argv, str(good)])
    assert code == 0, stderr


# ---------------------------------------------------------------------------
# Channel adapter contracts (row 16)
# ---------------------------------------------------------------------------

# sha256 of the contract with the runtime_profiles key removed, JSON with
# sorted keys. Captured at dev 6b411a459.
_CHANNEL_CONTRACT_DIGESTS = {
    "discord": "9e0e44ac35d0f0d4c845383283fb838cbc8d466fb6597901f8877dbe0ed79f8f",
    "email": "cb6dd1df66c77af2ea3434c2a1a6b517af5c6793ac9313a59ed77cb57646bae4",
    "slack": "48646c2aae3eef1bfaf3100989385db3176c92c634b69ef945e330b3a7fb0849",
    "sms": "fa3559a4e217020d2afd41c3e371542d2d050689746ad5f9ce643aa487dc7172",
    "telegram": "61dce57f5b6c03db7ada515c8c6609027bfb6fc4ec525181833693a9a4a94017",
}


def _channel_contract(platform: str) -> dict[str, Any]:
    path = (
        REPO_ROOT
        / "src"
        / "omniclaude"
        / "nodes"
        / f"node_channel_{platform}_adapter"
        / "contract.yaml"
    )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


@pytest.mark.parametrize("platform", sorted(_CHANNEL_CONTRACT_DIGESTS))
def test_channel_contract_is_unchanged_apart_from_runtime_profiles(
    platform: str,
) -> None:
    raw = dict(_channel_contract(platform))
    raw.pop("runtime_profiles", None)
    digest = hashlib.sha256(
        json.dumps(raw, sort_keys=True, default=str).encode()
    ).hexdigest()
    assert digest == _CHANNEL_CONTRACT_DIGESTS[platform]


@pytest.mark.parametrize("platform", sorted(_CHANNEL_CONTRACT_DIGESTS))
def test_channel_contract_is_owned_by_the_main_profile_only(platform: str) -> None:
    from omnibase_core.constants.constants_runtime_profiles import (
        REGISTERED_RUNTIME_PROFILES,
    )
    from omnibase_infra.runtime.auto_wiring.profile_ownership import (
        runtime_profile_owns_contract,
    )

    raw = _channel_contract(platform)
    owners = sorted(
        profile
        for profile in REGISTERED_RUNTIME_PROFILES
        if runtime_profile_owns_contract(raw, profile, environ={})
    )
    assert owners == ["main"]


# ---------------------------------------------------------------------------
# Lifecycle-class modules (row 3)
# ---------------------------------------------------------------------------


class _RecordingSlackClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def chat_postMessage(
        self, *, channel: str, text: str, thread_ts: str | None = None
    ) -> object:
        self.calls.append({"channel": channel, "text": text, "thread_ts": thread_ts})
        return {"ok": True}


async def test_slack_reply_posts_threaded_message() -> None:
    from omniclaude.enums.enum_channel_type import EnumChannelType
    from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
        ModelChannelReply,
    )
    from omniclaude.nodes.node_channel_slack_adapter.handlers.handler_outbound import (
        send_slack_reply,
    )

    client = _RecordingSlackClient()
    reply = ModelChannelReply(
        reply_text="hello",
        channel_id="C123",
        channel_type=EnumChannelType.SLACK,
        reply_to="1700000000.000100",
        correlation_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    await send_slack_reply(reply, client=client)
    assert client.calls == [
        {"channel": "C123", "text": "hello", "thread_ts": "1700000000.000100"}
    ]


async def test_correction_generator_falls_back_without_intelligence() -> None:
    from omniclaude.lib.utils.correction import generator

    with patch.object(generator, "_get_intelligence_client_class", return_value=None):
        gen = generator.CorrectionGenerator(intelligence_url=None, timeout=1.0)
    client = gen.intelligence_client
    assert isinstance(client, generator.IntelligenceClientProtocol)
    result = await client.gather_domain_standards("python", {"k": "v"})
    assert result == {
        "fallback": True,
        "results": [],
        "error": "intelligence client not available",
    }


def test_trigger_matcher_golden() -> None:
    from omniclaude.nodes.node_agent_routing_compute._internal.trigger_matching import (
        TriggerMatcher,
    )

    registry: Any = {
        "agents": {
            "agent-debug": {
                "activation_triggers": ["debug", "fix bug", "error"],
                "capabilities": ["debugging", "tracing"],
                "domain_context": "debugging",
            },
            "agent-frontend": {
                "activation_triggers": ["react", "css", "frontend"],
                "capabilities": ["ui"],
                "domain_context": "frontend",
            },
            "agent-db": {
                "activation_triggers": ["postgres", "sql query", "database"],
                "capabilities": ["sql"],
                "domain_context": "database",
            },
        }
    }
    matcher = TriggerMatcher(registry)
    assert matcher.match("please debug this error in my react app") == [
        ("agent-debug", 1.0, "Exact match: 'debug'"),
        ("agent-frontend", 1.0, "Exact match: 'react'"),
    ]
    assert matcher.match("write a sql query for postgres") == [
        ("agent-db", 1.0, "Exact match: 'sql query'")
    ]
    assert matcher.match("hello") == []


def test_agent_routing_internal_exports_are_stable() -> None:
    from omniclaude.nodes.node_agent_routing_compute import _internal

    exported = set(_internal.__all__)
    assert {"AgentData", "HistoricalRecord", "RoutingContext"} <= exported
    for name in exported:
        assert hasattr(_internal, name), name


class _DictValkey:
    def __init__(self) -> None:
        self.store: dict[str, set[str]] = {}
        self.ttls: dict[str, int] = {}

    async def sadd(self, key: str, *members: str) -> int:
        bucket = self.store.setdefault(key, set())
        before = len(bucket)
        bucket.update(members)
        return len(bucket) - before

    async def srem(self, key: str, *members: str) -> int:
        bucket = self.store.get(key, set())
        removed = len(bucket & set(members))
        bucket.difference_update(members)
        if not bucket:
            self.store.pop(key, None)
        return removed

    async def smembers(self, key: str) -> set[str]:
        return set(self.store.get(key, set()))

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return key in self.store

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                count += 1
        return count


async def test_watch_registry_round_trip() -> None:
    from omniclaude.nodes.node_github_pr_watcher_effect.handlers import (
        watch_registry,
    )

    client = _DictValkey()
    registry = watch_registry.WatchRegistry(client, ttl_seconds=60)
    assert await registry.register_watch("agent-1", "OmniNode-ai/omniclaude", 7)
    assert await registry.get_watchers("OmniNode-ai/omniclaude", 7) == {"agent-1"}
    assert await registry.get_agent_watches("agent-1") == {"OmniNode-ai/omniclaude:7"}
    assert await registry.unregister_all_for_agent("agent-1") == 1
    assert await registry.get_watchers("OmniNode-ai/omniclaude", 7) == set()


def test_kafka_producer_utils_public_functions() -> None:
    from omniclaude.lib import kafka_producer_utils as kpu

    assert kpu.KAFKA_PUBLISH_TIMEOUT_SECONDS == 10.0
    with patch.dict("os.environ", {}, clear=True):
        assert kpu.get_kafka_bootstrap_servers() is None
    envelope = kpu.create_event_envelope(
        "omninode.test.v1",
        "started",
        {"a": 1},
        "cid",
        "agent",
        timestamp="2026-10-05T00:00:00+00:00",
    )
    envelope.pop("event_id")
    assert envelope == {
        "causation_id": None,
        "correlation_id": "cid",
        "event_type": "omninode.test.v1",
        "namespace": "onex",
        "payload": {"a": 1},
        "schema_ref": "registry://onex/agent/started/v1",
        "source": "omniclaude",
        "tenant_id": "default",
        "timestamp": "2026-10-05T00:00:00+00:00",
    }
