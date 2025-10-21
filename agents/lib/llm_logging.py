from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .db import get_pg_pool


async def _get_active_price_row(model: str, provider: str) -> Optional[Dict[str, Any]]:
    pool = await get_pg_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, input_per_1k, output_per_1k
            FROM model_price_catalog
            WHERE model=$1 AND provider=$2
              AND effective_from <= CURRENT_DATE
              AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
            ORDER BY effective_from DESC, input_per_1k ASC, output_per_1k ASC
            LIMIT 1
            """,
            model,
            provider,
        )
        return dict(row) if row else None


async def log_llm_call(
    *,
    run_id: Optional[str],
    model: str,
    provider: str,
    model_version: Optional[str] = None,
    provider_region: Optional[str] = None,
    system_prompt_hash: Optional[str] = None,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    request: Optional[Dict[str, Any]] = None,
    response: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist an entry in llm_calls with denormalized pricing if available.

    No-op if Postgres is not configured.
    """
    pool = await get_pg_pool()
    if pool is None:
        return

    # Fetch active price
    price_row = await _get_active_price_row(model, provider)
    # Values may come back as Decimal; convert to float for computation
    eff_in = (
        float(price_row.get("input_per_1k"))
        if price_row and price_row.get("input_per_1k") is not None
        else None
    )
    eff_out = (
        float(price_row.get("output_per_1k"))
        if price_row and price_row.get("output_per_1k") is not None
        else None
    )
    price_id = price_row.get("id") if price_row else None

    # Compute cost
    computed_cost = None
    if (
        eff_in is not None
        and eff_out is not None
        and input_tokens is not None
        and output_tokens is not None
    ):
        computed_cost = (eff_in * (input_tokens / 1000.0)) + (
            eff_out * (output_tokens / 1000.0)
        )

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO llm_calls (
                id, run_id, model, provider, model_version, provider_region,
                system_prompt_hash, temperature, seed, input_tokens, output_tokens,
                price_catalog_id, effective_input_usd_per_1k, effective_output_usd_per_1k, computed_cost_usd,
                request, response
            ) VALUES (
                gen_random_uuid(), $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13, $14,
                $15::jsonb, $16::jsonb
            )
            """,
            run_id,
            model,
            provider,
            model_version,
            provider_region,
            system_prompt_hash,
            temperature,
            seed,
            input_tokens,
            output_tokens,
            price_id,
            eff_in,
            eff_out,
            computed_cost,
            json.dumps(request or {}),
            json.dumps(response or {}),
        )
