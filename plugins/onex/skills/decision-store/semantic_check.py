"""
semantic_check.py — LLM-assisted semantic conflict check for decision-store skill.

ONLY runs when structural_confidence >= 0.6.
NEVER runs when structural_confidence == 0.0 (cross-domain hard rule).
CANNOT escalate disjoint-service (structural_confidence == 0.3) conflicts beyond MEDIUM.

Non-blocking in MVP: results are delivered asynchronously and update the conflict
record when they arrive. The pipeline does not wait for semantic results before
continuing (unless the caller explicitly awaits).

LLM endpoint: DeepSeek-R1 at LLM_DEEPSEEK_R1_URL (see ~/.claude/CLAUDE.md for endpoint)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from detect_conflicts import DecisionEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEEPSEEK_DEFAULT = "http://192.168.86.200:8101"  # onex-allow-internal-ip
DEEPSEEK_R1_URL = os.environ.get("LLM_DEEPSEEK_R1_URL", _DEEPSEEK_DEFAULT)
SEMANTIC_CHECK_TIMEOUT_S = 30.0
SEMANTIC_CHECK_MODEL = "deepseek-r1"  # model tag served at the endpoint

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a technical decision conflict analyzer. You assess whether two architectural or
design decisions conflict with each other in meaning — not just in surface-level wording.

Respond with a JSON object only. No prose. No markdown fences. Schema:
{
  "conflicts": true | false,
  "severity_shift": -1 | 0 | 1,
  "rationale": "<one sentence>"
}

severity_shift rules:
  +1 = conflict is more severe than structural scoring suggested
   0 = structural scoring is accurate
  -1 = conflict is less severe than structural scoring suggested (e.g. compatible despite overlap)

Constraints you MUST respect:
- severity_shift cannot push result above HIGH or below LOW
- If structural_confidence == 0.3 (disjoint services), severity_shift MUST NOT be +1
"""

_USER_TEMPLATE = """\
Decision A:
  type: {type_a}
  domain: {domain_a}
  layer: {layer_a}
  services: {services_a}
  summary: {summary_a}

Decision B:
  type: {type_b}
  domain: {domain_b}
  layer: {layer_b}
  services: {services_b}
  summary: {summary_b}

Structural confidence: {structural_conf:.2f}
Base severity from structural scoring: {base_severity}

Do these decisions meaningfully conflict? Provide your assessment.
"""


# ---------------------------------------------------------------------------
# Core async function
# ---------------------------------------------------------------------------


async def semantic_check_async(
    a: DecisionEntry,
    b: DecisionEntry,
    structural_conf: float,
    base_severity: str,
    summary_a: str = "",
    summary_b: str = "",
) -> dict:
    """Perform async LLM-based semantic conflict check.

    Args:
        a: First decision entry.
        b: Second decision entry.
        structural_conf: Output of structural_confidence(a, b).
                         Must be >= 0.6 to call this function.
        base_severity: Output of compute_severity(a, b, structural_conf).
        summary_a: Human-readable summary/rationale of decision A.
        summary_b: Human-readable summary/rationale of decision B.

    Returns:
        Dict with keys:
            conflicts: bool
            severity_shift: int (-1, 0, or +1)
            rationale: str
            error: str | None  (set if LLM call failed; other fields default to no-shift)

    Raises:
        ValueError: If structural_conf < 0.6 (caller error) or == 0.0 (hard rule).
    """
    if structural_conf == 0.0:
        raise ValueError(
            "semantic_check must never run for cross-domain entries "
            "(structural_confidence == 0.0)"
        )
    if structural_conf < 0.6:
        raise ValueError(
            f"semantic_check should only run when structural_confidence >= 0.6, "
            f"got {structural_conf:.2f}"
        )

    user_prompt = _USER_TEMPLATE.format(
        type_a=a.decision_type,
        domain_a=a.scope_domain,
        layer_a=a.scope_layer,
        services_a=", ".join(a.scope_services) or "(platform-wide)",
        summary_a=summary_a or "(no summary provided)",
        type_b=b.decision_type,
        domain_b=b.scope_domain,
        layer_b=b.scope_layer,
        services_b=", ".join(b.scope_services) or "(platform-wide)",
        summary_b=summary_b or "(no summary provided)",
        structural_conf=structural_conf,
        base_severity=base_severity,
    )

    payload = {
        "model": SEMANTIC_CHECK_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 256,
    }

    try:
        async with httpx.AsyncClient(timeout=SEMANTIC_CHECK_TIMEOUT_S) as client:
            response = await client.post(
                f"{DEEPSEEK_R1_URL}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            # Strip markdown fences if present
            if content.startswith("```"):
                lines = content.splitlines()
                content = "\n".join(
                    line for line in lines if not line.startswith("```")
                ).strip()

            result = json.loads(content)

            # Enforce disjoint-service cap: structural_conf == 0.3 cannot escalate
            if structural_conf == 0.3 and result.get("severity_shift", 0) > 0:
                logger.warning(
                    "semantic_check: LLM returned severity_shift=+1 for disjoint-service "
                    "pair (structural_conf=0.3); capping to 0 per spec"
                )
                result["severity_shift"] = 0

            # Clamp to [-1, +1]
            result["severity_shift"] = max(-1, min(1, result.get("severity_shift", 0)))
            result.setdefault("conflicts", True)
            result.setdefault("rationale", "")
            result["error"] = None
            return result

    except httpx.TimeoutException:
        logger.warning(
            "semantic_check: timeout after %.1fs — returning no-shift",
            SEMANTIC_CHECK_TIMEOUT_S,
        )
        return {
            "conflicts": True,
            "severity_shift": 0,
            "rationale": "timeout",
            "error": "timeout",
        }

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "semantic_check: HTTP %s — returning no-shift", exc.response.status_code
        )
        return {
            "conflicts": True,
            "severity_shift": 0,
            "rationale": "http_error",
            "error": str(exc),
        }

    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("semantic_check: parse error (%s) — returning no-shift", exc)
        return {
            "conflicts": True,
            "severity_shift": 0,
            "rationale": "parse_error",
            "error": str(exc),
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "semantic_check: unexpected error (%s) — returning no-shift", exc
        )
        return {
            "conflicts": True,
            "severity_shift": 0,
            "rationale": "unexpected_error",
            "error": str(exc),
        }


def semantic_check_sync(
    a: DecisionEntry,
    b: DecisionEntry,
    structural_conf: float,
    base_severity: str,
    summary_a: str = "",
    summary_b: str = "",
) -> dict:
    """Synchronous wrapper around semantic_check_async for non-async callers."""
    return asyncio.run(
        semantic_check_async(a, b, structural_conf, base_severity, summary_a, summary_b)
    )
