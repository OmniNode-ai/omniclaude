import os
import asyncio
from dataclasses import dataclass
import json
from typing import Dict, Optional

from .db import get_pg_pool


@dataclass
class LineageEdge:
    edge_type: str  # e.g., APPLIED_TF, USED_MODEL, PHASE_EXECUTED, FIXED_BY
    src_type: str  # e.g., run, step, error
    src_id: str
    dst_type: str  # e.g., tf, model, phase
    dst_id: str
    attributes: Optional[Dict] = None


class PostgresLineageStore:
    async def write_edge(self, edge: LineageEdge) -> None:
        pool = await get_pg_pool()
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO lineage_edges (edge_type, src_type, src_id, dst_type, dst_id, attributes)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                edge.edge_type,
                edge.src_type,
                edge.src_id,
                edge.dst_type,
                edge.dst_id,
                json.dumps(edge.attributes or {}),
            )


class MemgraphLineageStore:
    def __init__(self) -> None:
        self._enabled = False
        self._driver = None

        # Support both MEMGRAPH_* and NEO4J_* style envs
        uri = os.getenv("MEMGRAPH_URI") or os.getenv("NEO4J_URI")  # bolt://localhost:7687
        user = os.getenv("MEMGRAPH_USER")
        password = os.getenv("MEMGRAPH_PASSWORD")
        if not user and not password:
            user = os.getenv("NEO4J_USER")
            password = os.getenv("NEO4J_PASSWORD")
        if not uri:
            return
        try:
            from neo4j import GraphDatabase  # type: ignore

            auth = (user, password) if user or password else None
            self._driver = GraphDatabase.driver(uri, auth=auth)
            self._enabled = True
        except Exception:
            # neo4j driver not installed or cannot connect; ignore for MVP
            self._enabled = False

    async def write_edge(self, edge: LineageEdge) -> None:
        if not self._enabled or self._driver is None:
            return

        def _write(tx):
            tx.run(
                """
                MERGE (s:Entity {type:$src_type, id:$src_id})
                MERGE (d:Entity {type:$dst_type, id:$dst_id})
                MERGE (s)-[r:%s]->(d)
                SET r += $attrs
                """
                % edge.edge_type,
                src_type=edge.src_type,
                src_id=edge.src_id,
                dst_type=edge.dst_type,
                dst_id=edge.dst_id,
                attrs=edge.attributes or {},
            )

        try:
            # best-effort; do not await driver internals, run in thread
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._driver.execute_write, _write)
        except Exception:
            # best-effort mirror; swallow errors in MVP
            return


class LineageWriter:
    def __init__(self) -> None:
        self._pg = PostgresLineageStore()
        self._mg = MemgraphLineageStore()

    async def emit(self, edge: LineageEdge) -> None:
        # Write synchronously to Postgres
        await self._pg.write_edge(edge)
        # Fire-and-forget Memgraph mirror
        try:
            asyncio.create_task(self._mg.write_edge(edge))
        except Exception:
            pass
