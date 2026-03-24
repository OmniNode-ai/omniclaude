#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Multi-model hostile reviewer aggregator.

Runs Gemini CLI, Codex CLI, Qwen3-Coder, and DeepSeek-R1 as independent
reviewers in parallel. Writes aggregated JSON to stdout; all errors to stderr.
Exit code: 0 on success, 1 on total failure (no models ran).

Token budget contract:
    stdout: compact aggregated JSON (~500 tokens) — Claude Code sees this
    stderr: all model verbose output — silenced by `2>/dev/null` in prompt.md,
            never enters Claude's context window
    event bus: full per-model raw findings — captured here for observability

The `2>/dev/null` redirect in prompt.md is MANDATORY. Each model emits hundreds
to thousands of tokens of chain-of-thought before producing its JSON finding.
Without it, multi-model review costs ~5,000-15,000 tokens per invocation.
See SKILL.md "Token Budget" section for full rationale.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# Stop-words: ONLY grammatical/structural noise. Security domain terms (injection,
# exception, validation, null, error) are intentionally excluded — they are the
# discriminators that distinguish SQL injection from command injection, etc.
_STOP_WORDS = frozenset(
    {
        "in",
        "the",
        "a",
        "an",
        "of",
        "to",
        "and",
        "or",
        "is",
        "are",
        "on",
        "at",
        "with",
        "for",
        "that",
        "this",
        "it",
        "was",
        "be",
        "by",
        "as",
        "from",
        "new",
        "via",
        "when",
        "if",
        "not",
        "its",
        "their",
    }
)
_SIMILARITY_THRESHOLD = 0.65
_PUNCT = str.maketrans("", "", ".,;:!?\"'()[]{}\\/-")


def _content_words(text: str) -> frozenset[str]:
    # Strip punctuation first so "injection," matches "injection" in stop-word check
    return frozenset(
        w for w in text.lower().translate(_PUNCT).split() if w not in _STOP_WORDS
    )


class EnumReviewConfidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class EnumReviewVerdict(str, Enum):
    clean = "clean"
    risks_noted = "risks_noted"
    blocking_issue = "blocking_issue"


class ModelReviewFinding(BaseModel):
    """A single code risk finding from one or more reviewers."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    id: int = Field(..., ge=1)
    description: str = Field(..., min_length=1)
    confidence: EnumReviewConfidence
    sources: list[str] = Field(default_factory=list)
    detection: str = Field(default="")


class ModelAggregateResult(BaseModel):
    """Aggregated result from the multi-model hostile reviewer run."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    success: bool
    findings: list[ModelReviewFinding] = Field(default_factory=list)
    models_run: list[str] = Field(default_factory=list)
    models_failed: list[str] = Field(default_factory=list)
    verdict: EnumReviewVerdict
    errors: list[str] = Field(default_factory=list)
    # Per-model raw findings before deduplication.
    # Not written to stdout (token savings) but emitted on the event bus
    # so full model output is observable even though Claude Code only sees
    # the compact aggregated JSON (~500 tokens).
    per_model_raw: dict[str, list[dict[str, str]]] = Field(default_factory=dict)

    def to_json(self) -> str:
        # NOTE: `per_model_raw` is intentionally excluded from stdout JSON.
        # It is emitted to the Kafka event bus via emit_result() for observability,
        # but must not appear in stdout — stdout is the ~500-token compact result
        # consumed by Claude Code. Including per_model_raw would negate token savings.
        return json.dumps(
            self.model_dump(exclude={"per_model_raw"}),
            indent=2,
            default=str,  # handles Enum serialization
        )


def _similarity(a: str, b: str) -> float:
    words_a = _content_words(a)
    words_b = _content_words(b)
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))


def merge_findings(
    per_model: list[list[dict[str, str]]],
) -> list[dict[str, object]]:
    """Weighted union: deduplicate by similarity, tag sources."""
    merged: list[dict[str, object]] = []
    for model_findings in per_model:
        for finding in model_findings:
            matched = next(
                (
                    m
                    for m in merged
                    if _similarity(str(m["description"]), finding["description"])
                    >= _SIMILARITY_THRESHOLD
                ),
                None,
            )
            if matched:
                sources = matched["sources"]
                assert isinstance(sources, list)
                if finding["source"] not in sources:
                    sources.append(finding["source"])
            else:
                merged.append(
                    {
                        "description": finding["description"],
                        "confidence": finding.get("confidence", "medium"),
                        "sources": [finding["source"]],
                        "detection": finding.get("detection", ""),
                    }
                )
    return merged


def compute_verdict(findings: list[dict[str, object]]) -> EnumReviewVerdict:
    """blocking_issue if any high-confidence finding flagged by 2+ models."""
    for f in findings:
        sources = f.get("sources", [])
        assert isinstance(sources, list)
        if f.get("confidence") == "high" and len(sources) >= 2:
            return EnumReviewVerdict.blocking_issue
    return EnumReviewVerdict.risks_noted if findings else EnumReviewVerdict.clean


# =============================================================================
# GeminiDriver
# =============================================================================

_GEMINI_PROMPT = (
    "You are an adversarial code reviewer. Find exactly 2 risks in this PR diff. "
    "Output ONLY valid JSON with no markdown fencing: "
    '{"findings": [{"description": "...", "confidence": "high|medium|low", "detection": "..."}]}'
)


def run_gemini(diff: str) -> list[dict[str, str]]:
    """Pipe PR diff to gemini CLI. All output suppressed except JSON.

    CLI interface: gemini v0.8.2 accepts positional prompt + stdin context.
    Verified: echo "..." | gemini "prompt" works (see Task 3 Step 1 pre-condition gate).
    If gemini CLI version changes interface, switch to: ["gemini", "-p", _GEMINI_PROMPT].
    """
    try:
        result = subprocess.run(  # noqa: PLW1510
            ["gemini", _GEMINI_PROMPT],
            input=diff,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        data = json.loads(result.stdout.strip())
        findings = data.get("findings", [])
        for f in findings:
            f["source"] = "gemini"
        return findings
    except Exception as e:
        print(f"[gemini] failed: {e}", file=sys.stderr)
        return []


# =============================================================================
# CodexDriver
# =============================================================================

_CODEX_PROMPT = (
    "Hostile adversarial code review. Find exactly 2 risks. "
    "Output ONLY valid JSON with no markdown fencing: "
    '{"findings": [{"description": "...", "confidence": "high|medium|low", "detection": "..."}]}'
)


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first complete JSON object from text using brace counting.

    Safer than first-`{`/last-`}` scan: handles models that emit multiple JSON
    blocks or append prose after the closing brace (e.g., 'Feel free to ask').
    Returns the first complete `{...}` span, or None if no valid object found.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def run_codex(pr_head_sha: str) -> list[dict[str, str]]:
    """Run codex review --commit <sha>. Extracts first complete JSON object from prose output.

    Uses brace-counting extraction (not first-{/last-}) to handle models that emit
    multiple JSON blocks or append trailing prose after the findings object.
    """
    if not pr_head_sha:
        print("[codex] no head SHA provided, skipping", file=sys.stderr)
        return []
    try:
        result = subprocess.run(  # noqa: PLW1510
            ["codex", "review", "--commit", pr_head_sha, _CODEX_PROMPT],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        stdout = result.stdout.strip()
        json_str = _extract_first_json_object(stdout)
        if json_str is None:
            print("[codex] no JSON block in output", file=sys.stderr)
            return []
        data = json.loads(json_str)
        findings = data.get("findings", [])
        for f in findings:
            f["source"] = "codex"
        return findings
    except Exception as e:
        print(f"[codex] failed: {e}", file=sys.stderr)
        return []


# =============================================================================
# HttpDriver (Qwen3-Coder, DeepSeek-R1)
# =============================================================================

_HTTP_PROMPT_TEMPLATE = (
    "You are an adversarial code reviewer. Review this PR diff. "
    "Find exactly 2 risks. Output ONLY valid JSON with no markdown fencing: "
    '{{"findings": [{{"description": "...", "confidence": "high|medium|low", "detection": "..."}}]}}\n\n'
    "PR diff:\n{diff}"
)


def run_http_model(
    name: str, base_url: str, model_id: str, diff: str
) -> list[dict[str, str]]:
    """Call OpenAI-compat endpoint. Uses stdlib urllib — no extra deps."""
    try:
        payload = json.dumps(
            {
                "model": model_id,
                # Head+tail strategy: keep first 4000 and last 4000 chars so
                # vulnerabilities at the end of large diffs are not silently dropped.
                "messages": [
                    {
                        "role": "user",
                        "content": _HTTP_PROMPT_TEMPLATE.format(
                            diff=diff[:4000]
                            + (
                                "\n...[truncated]...\n" + diff[-4000:]
                                if len(diff) > 8000
                                else diff[4000:]
                            ),
                        ),
                    }
                ],
                "max_tokens": 1024,
                "temperature": 0.2,
            }
        ).encode()
        req = urllib.request.Request(  # noqa: S310
            f"{base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"].strip()
        # Use brace-counting extraction (same as run_codex) to handle models that
        # emit multiple JSON blocks or append trailing prose after the findings object.
        json_str = _extract_first_json_object(content)
        if json_str is None:
            print(f"[{name}] no JSON block in response content", file=sys.stderr)
            return []
        parsed = json.loads(json_str)
        findings = parsed.get("findings", [])
        for f in findings:
            f["source"] = name
        return findings
    except Exception as e:
        print(f"[{name}] failed: {e}", file=sys.stderr)
        return []


# =============================================================================
# Parallel runner
# =============================================================================


def run_all_models(pr_number: str, repo: str) -> ModelAggregateResult:
    """Fetch diff + SHA, run all available models in parallel, aggregate."""
    try:
        diff_proc = subprocess.run(  # noqa: PLW1510
            ["gh", "pr", "diff", pr_number, "--repo", repo],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        diff = diff_proc.stdout
        if not diff.strip():
            return ModelAggregateResult(
                success=False,
                findings=[],
                models_run=[],
                models_failed=["all"],
                verdict=EnumReviewVerdict.clean,
                errors=[
                    f"gh pr diff returned empty output (rc={diff_proc.returncode}): "
                    f"{diff_proc.stderr.strip()[:200]}"
                ],
            )
    except Exception as e:
        return ModelAggregateResult(
            success=False,
            findings=[],
            models_run=[],
            models_failed=["all"],
            verdict=EnumReviewVerdict.clean,
            errors=[str(e)],
        )

    try:
        sha_proc = subprocess.run(  # noqa: PLW1510
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--repo",
                repo,
                "--json",
                "headRefOid",
                "-q",
                ".headRefOid",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        head_sha = sha_proc.stdout.strip()
    except Exception:
        head_sha = ""

    coder_url = os.environ.get("LLM_CODER_URL", "")
    deepseek_url = os.environ.get("LLM_DEEPSEEK_R1_URL", "")

    drivers: list[tuple[str, Callable[[], list[dict[str, str]]]]] = [
        ("gemini", lambda: run_gemini(diff)),
        ("codex", lambda: run_codex(head_sha)),
    ]
    if coder_url:
        _url = coder_url
        drivers.append(
            (
                "qwen3-coder",
                lambda: run_http_model(
                    "qwen3-coder", _url, "Qwen3-Coder-30B-A3B-Instruct", diff
                ),
            )
        )
    if deepseek_url:
        _ds_url = deepseek_url
        drivers.append(
            (
                "deepseek-r1",
                lambda: run_http_model(
                    "deepseek-r1", _ds_url, "DeepSeek-R1-Distill", diff
                ),
            )
        )

    per_model: list[list[dict[str, str]]] = []
    per_model_raw: dict[str, list[dict[str, str]]] = {}  # preserved for event bus
    models_run: list[str] = []
    models_failed: list[str] = []

    # Per-model timeouts: gemini=60s, codex=120s, http=90s — use 210s coordinator cap
    # future.result(timeout=5) gives the completed future 5s to unpack (it's already done)
    # TimeoutError from as_completed() must be caught: it fires when the 210s cap expires
    # before all futures complete. Without the catch, run_all_models() crashes and
    # merge_findings/compute_verdict are never called.
    with ThreadPoolExecutor(max_workers=len(drivers)) as pool:
        futures = {pool.submit(fn): name for name, fn in drivers}
        try:
            completed_futures = list(as_completed(futures, timeout=210))
        except TimeoutError:
            completed_futures = [f for f in futures if f.done()]
            timed_out = [name for f, name in futures.items() if not f.done()]
            for name in timed_out:
                print(f"[{name}] timed out after 210s coordinator cap", file=sys.stderr)
                models_failed.append(name)
        for future in completed_futures:
            name = futures[future]
            try:
                findings = future.result(timeout=5)
                per_model.append(findings)
                per_model_raw[name] = findings  # raw, pre-dedup — for bus emission only
                models_run.append(name)
            except Exception as e:
                print(f"[{name}] exception: {e}", file=sys.stderr)
                models_failed.append(name)

    merged = merge_findings(per_model)
    verdict = compute_verdict(merged)
    review_findings = [
        ModelReviewFinding(
            id=i + 1,
            description=str(f["description"]),
            confidence=EnumReviewConfidence(f.get("confidence", "medium")),
            sources=[str(s) for s in f.get("sources", [])],
            detection=str(f.get("detection", "")),
        )
        for i, f in enumerate(merged)
    ]
    return ModelAggregateResult(
        success=True,
        findings=review_findings,
        models_run=models_run,
        models_failed=models_failed,
        verdict=EnumReviewVerdict(verdict),
        per_model_raw=per_model_raw,  # not in stdout; emitted to bus for observability
    )


# =============================================================================
# Kafka event bus emission (Task 10)
# =============================================================================

EmitFn = Callable[[str, dict[str, object]], bool]


def _load_emit_fn() -> EmitFn | None:
    """Load emit_event from hooks lib. Returns None with a loud warning on import failure.

    Import failure = misconfigured deployment (warn loudly).
    Connection failure = daemon down (non-fatal, handled in emit_result).
    The two cases are intentionally distinguished.
    """
    hooks_lib = Path(__file__).parents[3] / "hooks" / "lib"
    try:
        if str(hooks_lib) not in sys.path:
            sys.path.insert(0, str(hooks_lib))
        from emit_client_wrapper import emit_event  # type: ignore[import]

        return emit_event  # type: ignore[return-value]
    except ImportError as e:
        print(
            f"[emit] CONFIGURATION ERROR: cannot import emit_client_wrapper "
            f"from {hooks_lib}: {e}",
            file=sys.stderr,
        )
        return None


def emit_result(
    result: ModelAggregateResult,
    pr_number: str,
    repo: str,
    emit_fn: EmitFn | None = None,
) -> None:
    """Emit findings to Kafka. emit_fn injected for testability; defaults to hooks lib.

    ConnectionRefusedError (daemon down) is non-fatal and logged to stderr.
    ImportError (missing hooks lib) is caught in _load_emit_fn and warned loudly.
    """
    if emit_fn is None:
        emit_fn = _load_emit_fn()
    if emit_fn is None:
        return
    try:
        event_type = (
            "hostile.reviewer.completed"
            if result.success
            else "hostile.reviewer.failed"
        )
        # Event bus payload is intentionally richer than stdout.
        # Claude Code only receives the compact aggregated JSON (~500 tokens via stdout).
        # The bus captures per-model raw findings so full model output is observable
        # without entering Claude's context window — token savings maintained.
        emit_fn(
            event_type,
            {
                "pr_number": pr_number,
                "repo": repo,
                "verdict": result.verdict,
                "models_run": result.models_run,
                "models_failed": result.models_failed,
                "finding_count": len(result.findings),
                "findings_aggregated": [
                    {
                        "id": f.id,
                        "confidence": f.confidence,
                        "sources": f.sources,
                        "description": f.description,
                    }
                    for f in result.findings
                ],
                # Per-model raw: each model's unmerged findings before deduplication.
                # This is what gets silenced by 2>/dev/null in prompt.md — now preserved on bus.
                "per_model_raw": result.per_model_raw,
            },
        )
    except Exception as e:
        print(f"[emit] failed (non-fatal): {e}", file=sys.stderr)


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Multi-model hostile reviewer aggregator"
    )
    parser.add_argument("--pr", required=True, help="PR number")
    parser.add_argument("--repo", required=True, help="GitHub repo (org/name)")
    args = parser.parse_args()
    result = run_all_models(args.pr, args.repo)
    emit_result(result, args.pr, args.repo)  # emit_fn defaults to hooks lib
    print(result.to_json())  # Only JSON to stdout; model output went to stderr
    sys.exit(0 if result.success else 1)
