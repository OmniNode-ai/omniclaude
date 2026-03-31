# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Route verification (B) to local Qwen3-14B via HTTP.

Sends contract checks as a structured prompt to LLM_CODER_FAST_URL and parses
the JSON response into a typed ModelLocalVerifierResult.  Self-check status is
treated as advisory only -- the local verifier prefers explicit evidence.

Fallback: if the local LLM is unreachable, the caller should escalate to the
Claude Code verifier.  Both the attempted route and the actual route are recorded
in the result so routing analysis can distinguish preferred vs executed route.
"""

from __future__ import annotations

import json
import logging
import os
from enum import StrEnum

import httpx
from pydantic import BaseModel, ConfigDict, Field

from omniclaude.verification.self_check import ModelTaskContract

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EnumVerdict(StrEnum):
    """Tri-state verification outcome."""

    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EnumDispatchSurface(StrEnum):
    """Where the verification was executed."""

    LOCAL_LLM = "local_llm"
    CLAUDE_CODE = "claude_code"


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class ModelLocalVerifierCheckResult(BaseModel):
    """Single check outcome from local LLM verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: str
    status: str = Field(description="PASS or FAIL")


class ModelLocalVerifierResult(BaseModel):
    """Typed result from local LLM verification (B).

    Never use dict[str, Any] -- ONEX validation requires typed models.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    verifier_model: str = Field(default="qwen3-14b")
    verdict: EnumVerdict
    passed: bool
    checks: list[ModelLocalVerifierCheckResult] = Field(default_factory=list)
    dispatch_surface: EnumDispatchSurface = Field(default=EnumDispatchSurface.LOCAL_LLM)
    attempted_route: EnumDispatchSurface = Field(
        default=EnumDispatchSurface.LOCAL_LLM,
        description="Route that was attempted (always local_llm for this verifier)",
    )
    actual_route: EnumDispatchSurface = Field(
        default=EnumDispatchSurface.LOCAL_LLM,
        description="Route that was actually used (differs on fallback)",
    )
    is_fallback: bool = Field(
        default=False, description="True if fell back to Claude Code verifier"
    )
    raw_response: str = Field(default="", description="Raw LLM response for debugging")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_local_verification_prompt(
    contract: ModelTaskContract, self_check_passed: bool
) -> str:
    """Build a structured verification prompt from contract checks.

    Args:
        contract: The task contract containing definition_of_done checks.
        self_check_passed: Whether self-check (A) reported PASS.  Treated as
            advisory only -- the verifier should prefer explicit evidence.

    Returns:
        A structured prompt string for the local LLM.
    """
    checks_text = "\n".join(
        f"- {c.criterion}: `{c.check}` (type: {c.check_type.value})"
        for c in contract.definition_of_done
    )
    return (
        f"Verify task {contract.task_id} completion.\n"
        f"\n"
        f"Self-check reported: {'PASS' if self_check_passed else 'FAIL'}\n"
        f"NOTE: Self-check status is advisory only. Prefer explicit evidence.\n"
        f"\n"
        f"Contract definition of done:\n"
        f"{checks_text}\n"
        f"\n"
        f"For each check, determine if the criterion is satisfied.\n"
        f'Respond with JSON only: {{"passed": bool, "checks": '
        f'[{{"criterion": str, "status": "PASS"|"FAIL"}}]}}\n'
        f"\n"
        f"Use PASS or FAIL for each check status."
    )


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def parse_verification_response(raw: str, task_id: str) -> ModelLocalVerifierResult:
    """Parse local LLM JSON response into typed verification result.

    Returns a typed ModelLocalVerifierResult, NOT a plain dict.
    Tri-state: PASS / FAIL / INSUFFICIENT_EVIDENCE.

    Args:
        raw: Raw JSON string from LLM response.
        task_id: Task identifier for the result.

    Returns:
        ModelLocalVerifierResult with verdict and per-check results.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ModelLocalVerifierResult(
            task_id=task_id,
            verdict=EnumVerdict.INSUFFICIENT_EVIDENCE,
            passed=False,
            checks=[],
            raw_response=raw if isinstance(raw, str) else "",
        )

    passed = bool(data.get("passed", False))
    raw_checks = data.get("checks", [])

    if not raw_checks:
        verdict = EnumVerdict.INSUFFICIENT_EVIDENCE
    elif passed:
        verdict = EnumVerdict.PASS
    else:
        verdict = EnumVerdict.FAIL

    typed_checks = [
        ModelLocalVerifierCheckResult(
            criterion=str(c.get("criterion", "")),
            status=str(c.get("status", "FAIL")),
        )
        for c in raw_checks
        if isinstance(c, dict)
    ]

    return ModelLocalVerifierResult(
        task_id=task_id,
        verdict=verdict,
        passed=passed,
        checks=typed_checks,
        raw_response=raw,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_local_verification(
    contract: ModelTaskContract,
    self_check_passed: bool,
    endpoint_url: str | None = None,
) -> ModelLocalVerifierResult:
    """Send verification request to local Qwen3-14B via HTTP.

    Args:
        contract: Task contract to verify.
        self_check_passed: Whether self-check (A) reported PASS.
        endpoint_url: Override for LLM endpoint (default: LLM_CODER_FAST_URL).

    Returns:
        ModelLocalVerifierResult with verdict.  On connection failure, returns
        a result with is_fallback=True indicating the caller should escalate
        to the Claude Code verifier.
    """
    url = endpoint_url or os.environ["LLM_CODER_FAST_URL"]
    prompt = build_local_verification_prompt(contract, self_check_passed)

    try:
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        ) as client:
            response = await client.post(
                f"{url}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.0,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return parse_verification_response(content, contract.task_id)
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        logger.warning(
            "Local LLM unreachable at %s, marking for fallback: %s", url, exc
        )
        return ModelLocalVerifierResult(
            task_id=contract.task_id,
            verdict=EnumVerdict.INSUFFICIENT_EVIDENCE,
            passed=False,
            checks=[],
            is_fallback=True,
            attempted_route=EnumDispatchSurface.LOCAL_LLM,
            actual_route=EnumDispatchSurface.CLAUDE_CODE,
            raw_response=str(exc),
        )
