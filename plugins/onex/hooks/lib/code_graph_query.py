#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CLI wrapper for code graph queries (plan-time context injection).

JSON stdin → JSON stdout. Always exits 0. Logs to stderr.

Two modes:
  structural — SQL against code_entities (epic-level overview)
  semantic   — Qdrant embedding search (ticket/brainstorm-level relevance)

Usage:
  echo '{"mode": "structural", "repos": ["omniclaude"]}' | python3 code_graph_query.py
  echo '{"mode": "semantic", "query": "add handler", "limit": 20}' | python3 code_graph_query.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

REPO_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
EMBEDDING_URL = os.environ.get("LLM_EMBEDDING_URL", "http://192.168.86.200:8100")  # noqa: E501  # onex-allow-internal-ip  # kafka-fallback-ok
COLLECTION = "code_patterns"
SIMILARITY_THRESHOLD = 0.75


def _run_psql(sql: str) -> tuple[bool, str]:
    """Run psql query against omniintelligence DB. Returns (ok, output).

    Note: OMNIINTELLIGENCE_DB_URL must use the host-accessible address
    (localhost:5436), not the Docker-internal hostname (postgres:5432).
    If ~/.omnibase/.env has the Docker-internal URL, override via:
      OMNIINTELLIGENCE_DB_URL=postgresql://postgres:...@localhost:5436/omniintelligence
    """
    db_url = os.environ.get("OMNIINTELLIGENCE_DB_URL", "")
    if not db_url:
        return False, "OMNIINTELLIGENCE_DB_URL not set"
    try:
        proc = subprocess.run(
            ["psql", db_url, "-t", "-A", "-F|", "-c", sql],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0:
            return False, proc.stderr
        return True, proc.stdout.strip()
    except Exception as e:
        return False, str(e)


def _get_embedding(text: str) -> list[float]:
    """Get embedding vector from LLM endpoint."""
    payload = json.dumps({"input": text, "model": "default"}).encode()
    req = Request(  # noqa: S310 — URL from env var, not user input
        f"{EMBEDDING_URL}/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:  # noqa: S310
        data = json.loads(resp.read())
    return data["data"][0]["embedding"]


def _search_qdrant(vector: list[float], limit: int) -> dict[str, Any]:
    """Search Qdrant for similar entities."""
    payload = json.dumps(
        {
            "vector": vector,
            "limit": limit,
            "score_threshold": SIMILARITY_THRESHOLD,
            "with_payload": True,
        }
    ).encode()
    req = Request(  # noqa: S310 — URL from env var, not user input
        f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read())


def query_structural(*, repos: list[str]) -> dict[str, Any]:
    """SQL-based structural overview for epic-level context."""
    for repo in repos:
        if not REPO_NAME_RE.match(repo):
            return {
                "success": True,
                "mode": "structural",
                "status": "service_unavailable",
                "error": f"Unsafe repo name: {repo}",
                "entities": [],
                "relationships": [],
            }

    # Detect which schema variant is active. Two competing migrations exist:
    #   025_code_entities.sql: entity_name, qualified_name, inject_into_context
    #   025_create_code_entities.sql: name, file_path (no qualified_name)
    # Try the richer schema first; fall back to the simpler one.
    ok, _ = _run_psql("SELECT entity_name FROM code_entities LIMIT 1")
    if ok:
        schema = "rich"  # 025_code_entities.sql
    else:
        ok, _ = _run_psql("SELECT name FROM code_entities LIMIT 1")
        if ok:
            schema = "simple"  # 025_create_code_entities.sql
        else:
            return {
                "success": True,
                "mode": "structural",
                "status": "service_unavailable",
                "entities": [],
                "relationships": [],
            }

    repo_list = ",".join(f"'{r}'" for r in repos)

    if schema == "rich":
        entity_sql = f"""
            SELECT source_repo, entity_type, entity_name, qualified_name,
                   COALESCE(classification, entity_type) AS classification
            FROM code_entities
            WHERE source_repo IN ({repo_list})
              AND entity_type IN ('class', 'protocol', 'model')
            ORDER BY source_repo, entity_type, entity_name
            LIMIT 50
        """
    else:
        entity_sql = f"""
            SELECT source_repo, entity_type, name,
                   file_path || ':' || name AS qualified_name,
                   COALESCE(classification, entity_type) AS classification
            FROM code_entities
            WHERE source_repo IN ({repo_list})
              AND entity_type IN ('class', 'protocol', 'model')
            ORDER BY source_repo, entity_type, name
            LIMIT 50
        """

    ok, entity_output = _run_psql(entity_sql)
    entities = []
    if ok and entity_output:
        for line in entity_output.split("\n"):
            parts = line.split("|")
            if len(parts) >= 5:
                entities.append(
                    {
                        "source_repo": parts[0],
                        "entity_type": parts[1],
                        "entity_name": parts[2],
                        "qualified_name": parts[3],
                        "classification": parts[4],
                    }
                )

    # Relationship query: inject_into_context only exists in the rich schema
    if schema == "rich":
        rel_sql = f"""
            SELECT ce.source_repo, cr.relationship_type, COUNT(*)
            FROM code_relationships cr
            JOIN code_entities ce ON cr.source_entity_id = ce.id
            WHERE ce.source_repo IN ({repo_list})
              AND cr.inject_into_context = true
            GROUP BY ce.source_repo, cr.relationship_type
            ORDER BY ce.source_repo, cr.relationship_type
        """
    else:
        rel_sql = f"""
            SELECT ce.source_repo, cr.relationship_type, COUNT(*)
            FROM code_relationships cr
            JOIN code_entities ce ON cr.source_entity_id = ce.id
            WHERE ce.source_repo IN ({repo_list})
            GROUP BY ce.source_repo, cr.relationship_type
            ORDER BY ce.source_repo, cr.relationship_type
        """
    ok, rel_output = _run_psql(rel_sql)
    relationships: list[dict[str, Any]] = []
    if ok and rel_output:
        for line in rel_output.split("\n"):
            parts = line.split("|")
            if len(parts) >= 3:
                relationships.append(
                    {
                        "source_repo": parts[0],
                        "relationship_type": parts[1],
                        "count": int(parts[2]),
                    }
                )

    return {
        "success": True,
        "mode": "structural",
        "status": "ok",
        "entities": entities,
        "relationships": relationships,
    }


def query_semantic(
    *, query: str, repos: list[str] | None = None, limit: int = 20
) -> dict[str, Any]:
    """Qdrant-based semantic search for ticket/brainstorm-level context.

    Args:
        query: Search text (ticket title, brainstorm topic, etc.)
        repos: Optional repo filter. If provided, results are filtered to these repos only.
               Task-scoped queries should always pass repos to suppress cross-repo noise.
               Omit for intentional cross-repo search (e.g., epic-level).
        limit: Max results to return.
    """
    try:
        embedding = _get_embedding(query)
        results = _search_qdrant(
            embedding, limit * 2 if repos else limit
        )  # over-fetch when filtering
        entities = []
        for hit in results.get("result", []):
            payload = hit.get("payload", {})
            if repos and payload.get("source_repo", "") not in repos:
                continue
            # Qdrant payload fields: entity_id, entity_type, name, file_path,
            # source_repo, line_start. Map to stable output contract.
            entity_name = payload.get("name", "")
            file_path = payload.get("file_path", "")
            entities.append(
                {
                    "entity_name": entity_name,
                    "entity_type": payload.get("entity_type", ""),
                    "qualified_name": f"{file_path}:{entity_name}"
                    if file_path
                    else entity_name,
                    "source_repo": payload.get("source_repo", ""),
                    "classification": payload.get("entity_type", ""),
                    "relevance_score": hit.get("score", 0.0),
                }
            )
            if len(entities) >= limit:
                break
        return {
            "success": True,
            "mode": "semantic",
            "status": "ok",
            "entities": entities,
        }
    except Exception as e:
        logger.warning("Semantic query failed: %s", e)
        return {
            "success": True,
            "mode": "semantic",
            "status": "service_unavailable",
            "entities": [],
            "error": str(e),
        }


def main() -> None:
    start = time.monotonic()
    try:
        raw = sys.stdin.read()
        request = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        request = {}

    mode = request.get("mode", "structural")

    if mode == "structural":
        repos = request.get("repos", [])
        result = query_structural(repos=repos)
    elif mode == "semantic":
        query = request.get("query", "")
        repos = request.get("repos")  # None = cross-repo, list = scoped
        limit = request.get("limit", 20)
        result = query_semantic(query=query, repos=repos, limit=limit)
    else:
        result = {
            "success": True,
            "mode": mode,
            "status": "error",
            "error": f"Unknown mode: {mode}",
            "entities": [],
        }

    result["retrieval_ms"] = int((time.monotonic() - start) * 1000)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e), "entities": []}))
    sys.exit(0)
