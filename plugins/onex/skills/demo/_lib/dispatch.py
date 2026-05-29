# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Runtime dispatcher for the /onex:demo delegation skill."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from uuid import uuid4

SUPPORTED_SUBCOMMANDS = frozenset({"delegation"})
CURATED_TASKS = (
    "Write a pytest test for a function that adds two integers",
    "Which is cheaper: GPT-4o or Gemini Flash 2.0 for summarization tasks?",
    "Run the ONEX skill router for ticket triage",
)
MODEL_CONFIGS: tuple[dict[str, object], ...] = (
    {
        "model_id": "gemini/gemini-2.0-flash",
        "endpoint_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "provider": "openai_compatible",
        "api_key_env_var": "GEMINI_API_KEY",  # pragma: allowlist secret
    },
    {
        "model_id": "claude-opus-4-5",
        "endpoint_url": "claude-cli://local",
        "provider": "claude_cli",
    },
    {
        "model_id": "claude-sonnet-4-6",
        "endpoint_url": "claude-cli://local",
        "provider": "claude_cli",
    },
    {
        "model_id": "onex-deterministic",
        "endpoint_url": "fixture://onex-deterministic",
        "provider": "deterministic_fixture",
    },
)
PROVIDER_FIXTURES: dict[str, dict[str, object]] = {
    "gemini/gemini-2.0-flash": {
        "outputs": [
            "Gemini fixture: concise pytest coverage plan.",
            "Gemini fixture: Gemini Flash is cheaper for this summary workload.",
            "Gemini fixture: route triage through the deterministic ONEX skill path.",
        ],
        "prompt_tokens": 40,
        "completion_tokens": 20,
        "latency_ms": 11.0,
    },
    "claude-opus-4-5": {
        "outputs": [
            "Opus fixture: deeper test design with edge cases.",
            "Opus fixture: cost favors Gemini Flash for short summaries.",
            "Opus fixture: use ONEX typed skill routing with evidence capture.",
        ],
        "prompt_tokens": 50,
        "completion_tokens": 25,
        "latency_ms": 14.0,
    },
    "claude-sonnet-4-6": {
        "outputs": [
            "Sonnet fixture: practical pytest implementation outline.",
            "Sonnet fixture: Gemini Flash is the lower-cost summarizer.",
            "Sonnet fixture: dispatch ticket triage through the native node.",
        ],
        "prompt_tokens": 45,
        "completion_tokens": 22,
        "latency_ms": 13.0,
    },
    "onex-deterministic": {
        "outputs": [
            "Deterministic fixture: generated local test scaffold.",
            "Deterministic fixture: selected zero-spend routing proof.",
            "Deterministic fixture: emitted typed skill-routing decision.",
        ],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "latency_ms": 0.0,
    },
}
PRICING_TABLE: dict[str, dict[str, float]] = {
    "gemini/gemini-2.0-flash": {
        "prompt_cost_per_1k": 0.000075,
        "completion_cost_per_1k": 0.0003,
    },
    "claude-opus-4-5": {
        "prompt_cost_per_1k": 0.015,
        "completion_cost_per_1k": 0.075,
    },
    "claude-sonnet-4-6": {
        "prompt_cost_per_1k": 0.003,
        "completion_cost_per_1k": 0.015,
    },
    "onex-deterministic": {
        "prompt_cost_per_1k": 0.0,
        "completion_cost_per_1k": 0.0,
    },
}


def dispatch(
    subcommand: str,
    *,
    count: int = 3,
    prompts: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run /onex:demo through native OmniMarket runtime-dispatched nodes."""
    if subcommand not in SUPPORTED_SUBCOMMANDS:
        return {
            "success": False,
            "error": (
                f"Unknown subcommand '{subcommand}'. "
                f"Supported: {sorted(SUPPORTED_SUBCOMMANDS)}."
            ),
        }

    effective_dry_run = dry_run or os.environ.get("ONEX_DEMO_DRY_RUN") == "1"
    selected_tasks = _select_tasks(count=count, prompts=prompts)
    run_id = uuid4()
    correlation_id = uuid4()

    try:
        fanout = _dispatch_runtime(
            command_name="demo_fanout_orchestrator",
            payload={
                "run_id": str(run_id),
                "correlation_id": str(correlation_id),
                "tasks": selected_tasks,
                "model_configs": list(MODEL_CONFIGS),
                "dry_run": effective_dry_run,
                "provider_fixtures": PROVIDER_FIXTURES,
            },
            response_topic="onex.evt.omnibase-infra.demo-fanout-skill.v1",  # arch-topic-naming: ignore
        )
        inference_results = fanout["results"]
        cost = _dispatch_runtime(
            command_name="demo_cost_compute",
            payload={
                "inference_results": inference_results,
                "pricing_table": PRICING_TABLE,
            },
            response_topic="onex.evt.omnibase-infra.demo-cost-skill.v1",  # arch-topic-naming: ignore
        )
        render = _dispatch_runtime(
            command_name="demo_renderer_effect",
            payload={
                "cost_result": {
                    "costs": cost["costs"],
                    "cheapest_model_id": cost["cheapest_model_id"],
                },
                "bar_width": 40,
                "title": "ONEX Demo Delegation Cost Comparison",
            },
            response_topic="onex.evt.omnibase-infra.demo-render-skill.v1",  # arch-topic-naming: ignore
        )
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "dry_run": effective_dry_run,
            "runtime_path": "omnimarket.native_nodes",
        }

    cheapest_llm = _cheapest_model(
        costs=cost["costs"],
        excluded_model_ids={"onex-deterministic"},
    )
    return {
        "success": True,
        "dry_run": effective_dry_run,
        "run_id": str(run_id),
        "correlation_id": str(correlation_id),
        "runtime_path": "omnimarket.native_nodes",
        "nodes": [
            "node_demo_fanout_orchestrator",
            "node_demo_cost_compute",
            "node_demo_renderer_effect",
        ],
        "tasks": selected_tasks,
        "inference_results": inference_results,
        "costs": cost["costs"],
        "cheapest_llm_model": cheapest_llm,
        "cheapest_overall_path": cost["cheapest_model_id"],
        "chart_lines": render["chart_lines"],
    }


def _select_tasks(*, count: int, prompts: list[str] | None) -> list[str]:
    if prompts:
        return [item.strip() for item in prompts if item.strip()]
    bounded_count = max(1, min(count, len(CURATED_TASKS)))
    return list(CURATED_TASKS[:bounded_count])


def _dispatch_runtime(
    *,
    command_name: str,
    payload: dict[str, object],
    response_topic: str,
) -> dict[str, object]:
    from omnimarket.adapters.codex.runtime_client import CodexRuntimeRequestAdapter

    result = CodexRuntimeRequestAdapter(requester="onex-demo-skill").dispatch_sync(
        command_name=command_name,
        payload=payload,
        timeout_ms=120_000,
        response_topic=response_topic,
        runtime_selection="local",
    )
    if not result.ok:
        message = result.error.message if result.error else "runtime dispatch failed"
        raise RuntimeError(f"{command_name} failed: {message}")
    if not result.output_payloads:
        raise RuntimeError(f"{command_name} returned no output payload")
    return result.output_payloads[0]


def _cheapest_model(
    *,
    costs: object,
    excluded_model_ids: set[str],
) -> str | None:
    if not isinstance(costs, list):
        return None
    entries = [
        item
        for item in costs
        if isinstance(item, dict) and item.get("model_id") not in excluded_model_ids
    ]
    if not entries:
        return None
    cheapest = min(entries, key=lambda item: float(item.get("total_cost_usd", 0.0)))
    model_id = cheapest.get("model_id")
    return str(model_id) if model_id is not None else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="/onex:demo")
    parser.add_argument("subcommand", nargs="?", default="delegation")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--prompts", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])

    prompts = (
        [item.strip() for item in ns.prompts.split(",") if item.strip()]
        if ns.prompts
        else None
    )
    result = dispatch(
        ns.subcommand,
        count=ns.count,
        prompts=prompts,
        dry_run=ns.dry_run,
    )
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
