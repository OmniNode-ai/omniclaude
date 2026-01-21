from __future__ import annotations

import json
from typing import Any

from .db import get_pg_pool


async def _get_active_price_row(model: str, provider: str) -> dict[str, Any] | None:
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
    run_id: str | None,
    model: str,
    provider: str,
    model_version: str | None = None,
    provider_region: str | None = None,
    system_prompt_hash: str | None = None,
    temperature: float | None = None,
    seed: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    request: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
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
    input_per_1k = price_row.get("input_per_1k") if price_row else None
    output_per_1k = price_row.get("output_per_1k") if price_row else None
    eff_in = float(input_per_1k) if input_per_1k is not None else None
    eff_out = float(output_per_1k) if output_per_1k is not None else None
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
        result = await conn.execute(
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
        # Check if INSERT succeeded
        rows_inserted = int(result.split()[2])
        if rows_inserted == 0:
            raise Exception(
                f"Failed to insert LLM call log: run_id={run_id}, model={model}"
            )
