#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""
Golden Corpus Generator for Agent Routing Regression Testing.

Generates golden_corpus.json by running curated prompts through the
current AgentRouter implementation. The output serves as the ground
truth for regression testing after refactoring.

Approach: Hybrid (per OMN-1923 Q3 answer)
  - Manually curated prompts covering all agents, edge cases, and ambiguity
  - Auto-captured router output as expected values

Usage:
    cd /Volumes/PRO-G40/Code/omniclaude
    python -m tests.routing.generate_corpus

    # Or with custom registry/output:
    python -m tests.routing.generate_corpus \
        --registry plugins/onex/agents/configs/agent-registry.yaml \
        --output tests/routing/golden_corpus.json
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Ensure src is importable
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root / "src") not in sys.path:
    sys.path.insert(0, str(_project_root / "src"))

from omniclaude.lib.core.agent_router import AgentRouter
from tests.routing.conftest import (
    TOLERANCE_CONFIDENCE,
    TOLERANCE_ROUTING_POLICY,
    TOLERANCE_SELECTED_AGENT,
)

# --------------------------------------------------------------------------
# Curated prompt catalogue
# --------------------------------------------------------------------------
# Each entry: (prompt, category, notes)
# The generator runs each prompt through the router and records the full
# routing decision. This becomes the golden expected output.

CURATED_PROMPTS: list[tuple[str, str, str]] = [
    # ── Category 1: Direct trigger matches (one per agent) ────────────
    (
        "Help me design a REST API with OpenAPI specs",
        "direct_trigger",
        "api-architect via 'api design'/'openapi'",
    ),
    (
        "Debug this error in the authentication module",
        "direct_trigger",
        "debug-intelligence via 'debug'/'error'",
    ),
    (
        "Build a React dashboard component with TypeScript",
        "direct_trigger",
        "frontend-developer via 'react'/'typescript'",
    ),
    (
        "Create a semantic commit message for these changes",
        "direct_trigger",
        "commit via 'commit'/'semantic commit'",
    ),
    (
        "Write comprehensive unit tests for the parser module",
        "direct_trigger",
        "testing via 'test'",
    ),
    (
        "Optimize the database query performance",
        "direct_trigger",
        "performance via 'performance'/'optimization'",
    ),
    (
        "Run a security audit on the authentication system",
        "direct_trigger",
        "security-audit via 'security'/'audit'",
    ),
    (
        "Set up a Docker container for the new microservice",
        "direct_trigger",
        "devops-infrastructure via 'docker'",
    ),
    (
        "Monitor production system health and uptime",
        "direct_trigger",
        "production-monitor via 'production'/'monitor'",
    ),
    (
        "Check agent observability metrics and diagnostics",
        "direct_trigger",
        "agent-observability via 'observability'/'diagnostics'",
    ),
    (
        "Analyze code quality and detect anti-patterns",
        "direct_trigger",
        "code-quality-analyzer via 'code quality'/'anti-patterns'",
    ),
    (
        "Review this pull request for merge readiness",
        "direct_trigger",
        "pr-review via 'pull request'/'merge readiness'",
    ),
    (
        "Research the best approach for implementing caching",
        "direct_trigger",
        "research via 'research'",
    ),
    (
        "Manage the ticket lifecycle and dependencies",
        "direct_trigger",
        "ticket-manager via 'ticket'/'dependency analysis'",
    ),
    (
        "Collect parameters for the new workflow initialization",
        "direct_trigger",
        "parameter-collector via 'collect parameters'",
    ),
    (
        "Write Python FastAPI backend for user authentication",
        "direct_trigger",
        "python-fastapi-expert via 'python'/'fastapi'",
    ),
    (
        "Generate an AST-based code structure for the new tool",
        "direct_trigger",
        "ast-generator via 'ast'/'code generation'",
    ),
    (
        "Initialize a new repository with git and CI/CD",
        "direct_trigger",
        "repository-setup via 'repository setup'",
    ),
    (
        "Write technical documentation for the API endpoints",
        "direct_trigger",
        "documentation-architect via 'documentation'/'api docs'",
    ),
    (
        "Create a comprehensive PR workflow with validation",
        "direct_trigger",
        "pr-workflow via 'PR workflow'",
    ),
    (
        "Summarize this deployment log output",
        "direct_trigger",
        "content-summarizer via 'summarize'",
    ),
    # ── Category 2: Multi-word trigger matches ────────────────────────
    (
        "Run tests and validate the output",
        "multi_word_trigger",
        "testing via 'run tests'/'validate'",
    ),
    (
        "Execute a penetration test on the external API",
        "multi_word_trigger",
        "security-audit via 'penetration test'",
    ),
    (
        "Create a full PR process with commit prerequisites",
        "multi_word_trigger",
        "pr-workflow via 'full PR workflow'",
    ),
    (
        "Set up kubernetes cluster for staging environment",
        "multi_word_trigger",
        "devops-infrastructure via 'kubernetes'",
    ),
    (
        "Investigate the root cause of the memory leak",
        "multi_word_trigger",
        "debug-intelligence via 'investigate'/'root cause'",
    ),
    (
        "Build a UI component for the settings page",
        "multi_word_trigger",
        "frontend-developer via 'ui component'",
    ),
    (
        "Assess code quality and onex compliance",
        "multi_word_trigger",
        "code-quality-analyzer via 'code quality'/'onex compliance'",
    ),
    (
        "Design api documentation for the new endpoints",
        "multi_word_trigger",
        "documentation-architect via 'api documentation'",
    ),
    (
        "Check the system health of all running agents",
        "multi_word_trigger",
        "agent-observability or production-monitor via 'system health'",
    ),
    (
        "Orchestrate a multi-agent workflow for this task",
        "multi_word_trigger",
        "polymorphic-agent via 'multi-agent'/'workflow orchestration'",
    ),
    # ── Category 3: Explicit agent requests ───────────────────────────
    (
        "use agent-debug-intelligence to analyze this stack trace",
        "explicit_request",
        "Explicit @agent pattern",
    ),
    (
        "@agent-testing run the full test suite",
        "explicit_request",
        "Explicit @agent pattern",
    ),
    (
        "@agent-api-architect design the user service API",
        "explicit_request",
        "Explicit @agent pattern",
    ),
    (
        "use agent-performance to profile this function",
        "explicit_request",
        "Explicit 'use agent-X' pattern",
    ),
    (
        "use agent-pr-review to check this PR",
        "explicit_request",
        "Explicit 'use agent-X' pattern",
    ),
    (
        "use an agent to help me with this task",
        "explicit_request",
        "Generic agent request -> polymorphic-agent",
    ),
    (
        "spawn an agent to coordinate this workflow",
        "explicit_request",
        "Generic agent request -> polymorphic-agent",
    ),
    (
        "@agent-security-audit check for vulnerabilities",
        "explicit_request",
        "Explicit @agent pattern",
    ),
    # ── Category 4: Low confidence / fallback prompts ─────────────────
    (
        "What is the meaning of life?",
        "fallback",
        "No routing triggers - should fallback",
    ),
    (
        "Tell me a joke about programming",
        "fallback",
        "No routing triggers - should fallback",
    ),
    (
        "How do I make pasta carbonara?",
        "fallback",
        "Completely unrelated - should fallback",
    ),
    ("What is 2 + 2?", "fallback", "Math question - should fallback"),
    (
        "Explain quantum computing in simple terms",
        "fallback",
        "No dev triggers - should fallback",
    ),
    (
        "List the planets in the solar system",
        "fallback",
        "No dev triggers - should fallback",
    ),
    ("Write me a haiku about spring", "fallback", "Creative writing - should fallback"),
    ("Who won the 2024 World Series?", "fallback", "Trivia - should fallback"),
    (
        "Translate this to French: Hello world",
        "fallback",
        "Translation - should fallback",
    ),
    (
        "Summarize the plot of Hamlet",
        "fallback",
        "Note: 'summarize' may trigger content-summarizer",
    ),
    # ── Category 5: Ambiguity cases (multiple agents may match) ───────
    (
        "Review the code and fix any bugs",
        "ambiguity",
        "Could be pr-review, debug, or code-quality",
    ),
    (
        "Improve the API performance",
        "ambiguity",
        "Could be api-architect or performance",
    ),
    (
        "Troubleshoot the deployment pipeline failure",
        "ambiguity",
        "Could be debug or devops",
    ),
    (
        "Validate the security compliance of the infrastructure",
        "ambiguity",
        "Could be security-audit or devops",
    ),
    (
        "Analyze the test coverage and suggest improvements",
        "ambiguity",
        "Could be testing or code-quality",
    ),
    (
        "Set up monitoring for the API endpoints",
        "ambiguity",
        "Could be production-monitor, observability, or api-architect",
    ),
    (
        "Document the architecture decisions",
        "ambiguity",
        "Could be documentation-architect or research",
    ),
    (
        "Create a deployment script and run it",
        "ambiguity",
        "Could be devops-infrastructure or commit",
    ),
    (
        "Fix the failing test in the authentication module",
        "ambiguity",
        "Could be testing or debug",
    ),
    (
        "Optimize the frontend rendering performance",
        "ambiguity",
        "Could be frontend-developer or performance",
    ),
    # ── Category 6: Context filtering edge cases ──────────────────────
    (
        "We need a polymorphic architecture design",
        "context_filter",
        "Should NOT trigger polymorphic-agent (technical usage)",
    ),
    (
        "The code uses polymorphism for the strategy pattern",
        "context_filter",
        "Should NOT trigger polymorphic-agent (technical usage)",
    ),
    (
        "Use poly to coordinate the agents",
        "context_filter",
        "SHOULD trigger polymorphic-agent (action context: 'use poly')",
    ),
    (
        "Spawn polly to run multiple tasks",
        "context_filter",
        "SHOULD trigger polymorphic-agent (action context: 'spawn polly')",
    ),
    (
        "Polly suggested we use a different approach",
        "context_filter",
        "Should NOT trigger polymorphic-agent (casual reference)",
    ),
    (
        "Dispatch 4 pollys for parallel execution",
        "context_filter",
        "SHOULD trigger polymorphic-agent via 'dispatch 4 pollys'",
    ),
    (
        "The pollyanna approach won't work here",
        "context_filter",
        "Should NOT trigger polymorphic-agent (pollyanna rejection)",
    ),
    (
        "Coordinate the workflow using polymorphic patterns",
        "context_filter",
        "May partially match - tests boundary",
    ),
    (
        "Debug the polymorphic dispatch issue",
        "context_filter",
        "Should route to debug (not polymorphic)",
    ),
    (
        "Using polymorphism in the router design",
        "context_filter",
        "Should NOT trigger polymorphic-agent (technical usage)",
    ),
    # ── Category 7: Fuzzy match cases ─────────────────────────────────
    ("Write some tests for the new feature", "fuzzy_match", "Fuzzy 'tests' -> testing"),
    (
        "Help me troubleshoot this issue",
        "fuzzy_match",
        "'troubleshoot' exact match for debug-intelligence",
    ),
    (
        "I need to deploy this to staging",
        "fuzzy_match",
        "'deploy' -> devops-infrastructure",
    ),
    (
        "Can you review these code changes?",
        "fuzzy_match",
        "'review' + 'code changes' -> pr-review",
    ),
    (
        "Let's investigate why the build is slow",
        "fuzzy_match",
        "'investigate' -> research or debug",
    ),
    (
        "Help improve the documentation quality",
        "fuzzy_match",
        "'documentation' + 'quality' -> documentation-architect",
    ),
    (
        "Profile the memory usage of this service",
        "fuzzy_match",
        "'profile' -> performance (high confidence trigger)",
    ),
    (
        "Check for any vulnerabilities in dependencies",
        "fuzzy_match",
        "'vulnerabilities' -> security-audit",
    ),
    (
        "Speed up the frontend page load time",
        "fuzzy_match",
        "'speed' + 'frontend' -> performance or frontend",
    ),
    (
        "Create a scaffold for the new ONEX tool",
        "fuzzy_match",
        "'scaffold' -> ast-generator",
    ),
    # ── Category 8: Compound/complex prompts ──────────────────────────
    (
        "Debug the error, then write tests to prevent regression",
        "compound",
        "Primary: debug, secondary: testing",
    ),
    (
        "Review the PR and check for security issues",
        "compound",
        "Primary: pr-review, secondary: security",
    ),
    (
        "Deploy the new feature and monitor the rollout",
        "compound",
        "Primary: devops, secondary: monitoring",
    ),
    (
        "Research the best testing strategy for microservices",
        "compound",
        "Primary: research or testing",
    ),
    (
        "Optimize the API response time and document the changes",
        "compound",
        "Primary: performance or api-architect",
    ),
    # ── Category 9: Short/terse prompts ───────────────────────────────
    ("debug", "terse", "Single word - should match debug-intelligence"),
    ("test", "terse", "Single word - should match testing"),
    ("deploy", "terse", "Single word - should match devops-infrastructure"),
    ("security", "terse", "Single word - should match security-audit"),
    ("performance", "terse", "Single word - should match performance"),
    (
        "review",
        "terse",
        "Single word - may not match (no word boundary for 'review' alone)",
    ),
    ("api", "terse", "Single word - should match api-architect"),
    ("docs", "terse", "Single word - should match documentation-architect"),
    ("commit", "terse", "Single word - should match commit"),
    ("monitor", "terse", "Single word - should match production-monitor"),
    # ── Category 10: Integration-layer (route_via_events wrapper) ─────
    (
        "",
        "integration_edge",
        "Empty prompt -> wrapper returns fallback with 'Invalid input'",
    ),
    ("   ", "integration_edge", "Whitespace-only prompt -> wrapper returns fallback"),
    (
        "Help me fix this bug in production",
        "integration_edge",
        "Multiple triggers: 'fix'/'bug' + 'production'",
    ),
    (
        "What's the status of the system?",
        "integration_edge",
        "agent-observability via 'what's the status'",
    ),
    (
        "Create a new FastAPI endpoint with tests",
        "integration_edge",
        "Multiple agents: fastapi + tests",
    ),
    (
        "Help me write better commit messages",
        "integration_edge",
        "'commit' trigger match",
    ),
    # ── Category 11: Additional coverage for 100+ ─────────────────────
    (
        "Benchmark the new caching implementation",
        "additional",
        "'benchmark' -> performance",
    ),
    (
        "Automate the deployment pipeline",
        "additional",
        "'deployment' + 'pipeline' -> devops",
    ),
    (
        "Build responsive design for mobile users",
        "additional",
        "'responsive design' -> frontend-developer",
    ),
    (
        "Create an incident response runbook",
        "additional",
        "'incident response' -> production-monitor",
    ),
]


def generate_corpus(
    registry_path: str,
    output_path: str,
) -> dict[str, Any]:
    """
    Run all curated prompts through the router and capture results.

    Args:
        registry_path: Path to agent-registry.yaml
        output_path: Path to write golden_corpus.json

    Returns:
        The corpus dict (also written to output_path)
    """
    # Initialize router with caching disabled for deterministic results
    router = AgentRouter(registry_path=registry_path, cache_ttl=0)
    agent_count = len(router.registry.get("agents", {}))
    print(f"Loaded registry with {agent_count} agents")

    corpus: dict[str, Any] = {
        "version": "1.0.0",
        "generator": "tests/routing/generate_corpus.py",
        "agent_count": agent_count,
        "tolerance": {
            "confidence": TOLERANCE_CONFIDENCE,
            "selected_agent": TOLERANCE_SELECTED_AGENT,
            "routing_policy": TOLERANCE_ROUTING_POLICY,
        },
        "entries": [],
    }

    for i, (prompt, category, notes) in enumerate(CURATED_PROMPTS, 1):
        if not prompt or not prompt.strip():
            print(f"  [{i:3d}/{len(CURATED_PROMPTS)}] SKIP     → (blank prompt)")
            continue

        # Clear cache between runs (already ttl=0 but be explicit)
        router.invalidate_cache()

        start = time.perf_counter()
        recommendations = router.route(prompt, max_recommendations=5)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Build entry mirroring what route_via_events would produce
        if recommendations:
            top = recommendations[0]
            selected_agent = top.agent_name
            confidence = top.confidence.total
            reason = top.reason
            explanation = top.confidence.explanation

            # Build candidates
            candidates = []
            for rec in recommendations:
                agents_registry = router.registry.get("agents", {})
                rec_data = agents_registry.get(rec.agent_name, {})
                candidates.append(
                    {
                        "name": rec.agent_name,
                        "score": round(rec.confidence.total, 6),
                        "reason": rec.reason,
                    }
                )
        else:
            selected_agent = ""
            confidence = 0.5
            reason = "No trigger matches found"
            explanation = ""
            candidates = []

        # Determine routing_policy by mirroring route_via_events wrapper logic.
        # The wrapper never returns 'explicit_request' because
        # AgentRecommendation lacks is_explicit (getattr always returns False).
        # Cross-validated by TestCrossValidation in the harness.
        if confidence >= 0.5 and recommendations:
            routing_policy = "trigger_match"
        else:
            routing_policy = "fallback_default"
            selected_agent = ""
            confidence = 0.5

        entry = {
            "id": i,
            "prompt": prompt,
            "category": category,
            "notes": notes,
            "expected": {
                "selected_agent": selected_agent,
                "confidence": round(confidence, 6),
                "routing_policy": routing_policy,
                "routing_path": "local",
                "reasoning_contains": reason if reason else None,
            },
            "candidates": candidates[:5],
            "router_layer": {
                "top_agent": recommendations[0].agent_name if recommendations else None,
                "top_confidence": round(recommendations[0].confidence.total, 6)
                if recommendations
                else None,
                "top_trigger_score": round(
                    recommendations[0].confidence.trigger_score, 6
                )
                if recommendations
                else None,
                "top_context_score": round(
                    recommendations[0].confidence.context_score, 6
                )
                if recommendations
                else None,
                "top_capability_score": round(
                    recommendations[0].confidence.capability_score, 6
                )
                if recommendations
                else None,
                "top_historical_score": round(
                    recommendations[0].confidence.historical_score, 6
                )
                if recommendations
                else None,
                "match_count": len(recommendations),
            },
            "generation_latency_ms": round(elapsed_ms, 2),
        }

        corpus["entries"].append(entry)

        # Progress indicator
        status = "OK" if routing_policy != "fallback_default" else "FALLBACK"
        print(
            f"  [{i:3d}/{len(CURATED_PROMPTS)}] {status:8s} → {selected_agent:40s} ({confidence:.2f}) | {prompt[:60]}"
        )

    # Write corpus
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)

    # Summary
    total = len(corpus["entries"])
    fallbacks = sum(
        1
        for e in corpus["entries"]
        if e["expected"]["routing_policy"] == "fallback_default"
    )
    explicit = sum(
        1
        for e in corpus["entries"]
        if e["expected"]["routing_policy"] == "explicit_request"
    )
    triggers = sum(
        1
        for e in corpus["entries"]
        if e["expected"]["routing_policy"] == "trigger_match"
    )

    print(f"\n{'=' * 60}")
    print(f"Golden corpus generated: {total} entries")
    print(f"  Trigger matches:    {triggers}")
    print(f"  Explicit requests:  {explicit}")
    print(f"  Fallbacks:          {fallbacks}")
    print(f"Written to: {output_path}")
    print(f"{'=' * 60}")

    return corpus


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate golden corpus for routing regression"
    )
    parser.add_argument(
        "--registry",
        default=str(
            _project_root
            / "plugins"
            / "onex"
            / "agents"
            / "configs"
            / "agent-registry.yaml"
        ),
        help="Path to agent-registry.yaml",
    )
    parser.add_argument(
        "--output",
        default=str(_project_root / "tests" / "routing" / "golden_corpus.json"),
        help="Path to write golden_corpus.json",
    )
    args = parser.parse_args()

    print(f"Registry: {args.registry}")
    print(f"Output:   {args.output}")
    print()

    generate_corpus(args.registry, args.output)


if __name__ == "__main__":
    main()
