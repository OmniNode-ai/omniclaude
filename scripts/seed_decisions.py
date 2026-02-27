#!/usr/bin/env python3
"""Seed architectural decisions into the decision_store table.

Seeds 4 decisions from the Insights report (OMN-2822) into the decision_store
PostgreSQL table. These decisions are surfaced to agents via the ticket-work
intake injection pipeline (DecisionContextLoader in OMN-2770).

Idempotent: uses stable UUIDs derived from decision titles. Re-running updates
existing rows (ON CONFLICT ... DO UPDATE).

Usage:
    # Dry-run (prints SQL, does not execute)
    python scripts/seed_decisions.py --dry-run

    # Execute against the database
    source .env
    python scripts/seed_decisions.py

    # Verify after seeding
    python scripts/seed_decisions.py --verify

Environment:
    OMNIBASE_INFRA_DB_URL  — PostgreSQL connection string (required unless --dry-run)
    POSTGRES_PASSWORD      — Used if OMNIBASE_INFRA_DB_URL is not set

Related:
    - OMN-2822: Phase 1a — Seed Decisions into Decision Store
    - OMN-2821: Claude Code Insights Report Integration (parent epic)
    - OMN-2765: NodeDecisionStoreEffect (runtime write path)
    - OMN-2770: ticket-work / ticket-pipeline decision context injection
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Stable UUID generation from decision title
# ---------------------------------------------------------------------------

# Namespace UUID for decision store seeds (deterministic, reproducible)
DECISION_NAMESPACE = uuid.UUID("b8f9a2e1-4c7d-4f3a-9e6b-1d2c3a4b5c6d")


def stable_decision_id(title: str) -> uuid.UUID:
    """Generate a stable UUID5 from a decision title.

    Uses a fixed namespace so the same title always produces the same UUID,
    making the seed script idempotent.
    """
    return uuid.uuid5(DECISION_NAMESPACE, title)


# ---------------------------------------------------------------------------
# Decision definitions
# ---------------------------------------------------------------------------


class DecisionSeed(NamedTuple):
    """A decision to seed into the decision_store table."""

    title: str
    decision_type: str
    scope_domain: str
    scope_layer: str
    scope_services: list[str]
    rationale: str
    alternatives: list[dict[str, object]]
    tags: list[str]
    source: str
    epic_id: str | None


# Correlation ID for this seed batch
SEED_CORRELATION_ID = uuid.UUID(
    "00000000-0000-0000-0000-omn282200001".replace("omn", "000")
)
# Simpler: use a fixed UUID
SEED_CORRELATION_ID = uuid.UUID("a822a822-a822-4822-a822-a82200002822")

DECISIONS: list[DecisionSeed] = [
    DecisionSeed(
        title="Treat skills as ONEX nodes; do not design parallel runtimes",
        decision_type="DESIGN_PATTERN",
        scope_domain="code-structure",
        scope_layer="architecture",
        scope_services=[],  # global / platform-wide
        rationale=(
            "60 wrong-approach events observed from agents treating skills as "
            "separate systems outside the ONEX node framework. Skills ARE ONEX "
            "nodes — they follow the same contract, lifecycle, and execution "
            "patterns. Designing parallel runtimes creates redundant "
            "infrastructure and violates the single-runtime principle."
        ),
        alternatives=[
            {
                "label": "Parallel skill runtime alongside ONEX",
                "status": "rejected",
                "rejection_reason": (
                    "Creates redundant infrastructure; agents repeatedly "
                    "attempted this approach causing 60 wrong-approach events"
                ),
            },
        ],
        tags=["insights-report", "skills", "onex-nodes", "architecture"],
        source="manual",
        epic_id="OMN-2821",
    ),
    DecisionSeed(
        title="Use GitHub Merge Queue for CI composition; do not implement CI merge branches",
        decision_type="TECH_STACK_CHOICE",
        scope_domain="infra",
        scope_layer="architecture",
        scope_services=[],  # global / platform-wide
        rationale=(
            "Agents repeatedly pursued Path A (ephemeral merge branches) for "
            "CI composition instead of using GitHub Merge Queue. Merge Queue "
            "is the platform-standard mechanism for serializing CI checks "
            "before merge. Custom branch-based CI composition duplicates "
            "this functionality and creates maintenance burden."
        ),
        alternatives=[
            {
                "label": "Ephemeral CI merge branches (Path A)",
                "status": "rejected",
                "rejection_reason": (
                    "Agents kept pursuing this approach despite it duplicating "
                    "GitHub Merge Queue functionality; creates maintenance burden"
                ),
            },
        ],
        tags=["insights-report", "ci-cd", "merge-queue", "github"],
        source="manual",
        epic_id="OMN-2821",
    ),
    DecisionSeed(
        title="Ticket routing uses prefix-based repo mapping; always verify repo before dispatch",
        decision_type="API_CONTRACT",
        scope_domain="api",
        scope_layer="architecture",
        scope_services=[],  # global / platform-wide
        rationale=(
            "Ticket misrouted to wrong repo causing failed implementation. "
            "The ticket routing system uses prefix-based mapping from ticket "
            "labels to repository slugs (e.g., 'omniclaude' label maps to "
            "OmniNode-ai/omniclaude repo). Agents MUST verify the target "
            "repo matches the ticket's labeled repo before dispatching "
            "any implementation work."
        ),
        alternatives=[
            {
                "label": "Dynamic repo detection from ticket content",
                "status": "rejected",
                "rejection_reason": (
                    "Unreliable — ticket content does not always indicate "
                    "the correct repo; prefix-based label mapping is deterministic"
                ),
            },
        ],
        tags=["insights-report", "routing", "ticket-dispatch", "repo-mapping"],
        source="manual",
        epic_id="OMN-2821",
    ),
    DecisionSeed(
        title="Plan-to-tickets: parse plan files directly; never analyze format compatibility",
        decision_type="DESIGN_PATTERN",
        scope_domain="code-structure",
        scope_layer="design",
        scope_services=["omniclaude"],  # scoped to plan-to-tickets skill
        rationale=(
            "Multiple sessions wasted on format analysis instead of directly "
            "parsing plan files. The plan-to-tickets skill should parse "
            "markdown plan files directly using the established heading "
            "structure (## Phase, ### Task, etc.) without analyzing or "
            "negotiating format compatibility. The format is fixed and "
            "documented."
        ),
        alternatives=[
            {
                "label": "Format compatibility analysis before parsing",
                "status": "rejected",
                "rejection_reason": (
                    "Multiple sessions wasted on this approach; format is "
                    "fixed and documented, analysis adds no value"
                ),
            },
        ],
        tags=["insights-report", "plan-to-tickets", "parsing", "skill-specific"],
        source="manual",
        epic_id="OMN-2821",
    ),
]


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------

SQL_UPSERT_DECISION = """\
INSERT INTO decision_store (
    decision_id, correlation_id, title, decision_type, status,
    scope_domain, scope_services, scope_layer, rationale, alternatives,
    tags, source, epic_id, supersedes, superseded_by,
    created_at, db_written_at, created_by
) VALUES (
    %(decision_id)s, %(correlation_id)s, %(title)s, %(decision_type)s, %(status)s,
    %(scope_domain)s, %(scope_services)s::jsonb, %(scope_layer)s, %(rationale)s,
    %(alternatives)s::jsonb,
    %(tags)s::jsonb, %(source)s, %(epic_id)s, %(supersedes)s::jsonb, %(superseded_by)s,
    %(created_at)s, NOW(), %(created_by)s
)
ON CONFLICT (decision_id) DO UPDATE SET
    correlation_id  = EXCLUDED.correlation_id,
    title           = EXCLUDED.title,
    decision_type   = EXCLUDED.decision_type,
    status          = EXCLUDED.status,
    scope_domain    = EXCLUDED.scope_domain,
    scope_services  = EXCLUDED.scope_services,
    scope_layer     = EXCLUDED.scope_layer,
    rationale       = EXCLUDED.rationale,
    alternatives    = EXCLUDED.alternatives,
    tags            = EXCLUDED.tags,
    source          = EXCLUDED.source,
    epic_id         = EXCLUDED.epic_id,
    supersedes      = EXCLUDED.supersedes,
    superseded_by   = EXCLUDED.superseded_by,
    created_at      = EXCLUDED.created_at,
    created_by      = EXCLUDED.created_by
RETURNING
    (xmax = 0) AS was_insert,
    decision_id;
"""

SQL_QUERY_DECISIONS = """\
SELECT
    decision_id, title, decision_type, status,
    scope_domain, scope_services, scope_layer,
    rationale, tags, epic_id, created_at
FROM decision_store
WHERE epic_id = %(epic_id)s
  AND status = 'ACTIVE'
ORDER BY created_at;
"""


def build_params(d: DecisionSeed) -> dict[str, object]:
    """Build SQL parameter dict for a single decision."""
    decision_id = stable_decision_id(d.title)
    now = datetime.now(UTC)
    return {
        "decision_id": str(decision_id),
        "correlation_id": str(SEED_CORRELATION_ID),
        "title": d.title,
        "decision_type": d.decision_type,
        "status": "ACTIVE",
        "scope_domain": d.scope_domain,
        "scope_services": json.dumps(sorted(s.lower() for s in d.scope_services)),
        "scope_layer": d.scope_layer,
        "rationale": d.rationale,
        "alternatives": json.dumps(d.alternatives),
        "tags": json.dumps(d.tags),
        "source": d.source,
        "epic_id": d.epic_id,
        "supersedes": json.dumps([]),
        "superseded_by": None,
        "created_at": now,
        "created_by": "seed-script:OMN-2822",
    }


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


def get_connection_string() -> str:
    """Resolve the PostgreSQL connection string from environment."""
    db_url = os.environ.get("OMNIBASE_INFRA_DB_URL", "").strip()
    if db_url:
        return db_url

    password = os.environ.get("POSTGRES_PASSWORD", "").strip()
    if not password:
        print(
            "ERROR: Neither OMNIBASE_INFRA_DB_URL nor POSTGRES_PASSWORD is set.",
            file=sys.stderr,
        )
        sys.exit(1)

    return f"postgresql://postgres:{password}@localhost:5436/omnibase_infra"


def seed_decisions(*, dry_run: bool = False) -> int:
    """Seed all decisions into the database.

    Returns:
        Number of decisions seeded (inserted or updated).
    """
    if dry_run:
        print("=== DRY RUN — no database writes ===\n")
        for d in DECISIONS:
            params = build_params(d)
            scope = (
                "platform-wide" if not d.scope_services else ", ".join(d.scope_services)
            )
            print(f"  [{d.decision_type}/{d.scope_layer}] {d.title}")
            print(f"    ID:    {params['decision_id']}")
            print(f"    Scope: {d.scope_domain} / {scope}")
            print(f"    Tags:  {', '.join(d.tags)}")
            print()
        print(f"Would seed {len(DECISIONS)} decisions.")
        return len(DECISIONS)

    try:
        import psycopg2  # noqa: PLC0415
    except ImportError:
        print(
            "ERROR: psycopg2 not installed. Install with: uv pip install psycopg2-binary",
            file=sys.stderr,
        )
        sys.exit(1)

    conn_str = get_connection_string()
    print("Connecting to database...")

    conn = psycopg2.connect(conn_str)
    try:
        cur = conn.cursor()
        count = 0
        for d in DECISIONS:
            params = build_params(d)
            cur.execute(SQL_UPSERT_DECISION, params)
            row = cur.fetchone()
            was_insert = row[0] if row else None
            decision_id = row[1] if row else params["decision_id"]
            action = "inserted" if was_insert else "updated"
            scope = (
                "platform-wide" if not d.scope_services else ", ".join(d.scope_services)
            )
            print(f"  [{action}] [{d.decision_type}/{d.scope_layer}] {d.title}")
            print(f"           ID: {decision_id} | Scope: {d.scope_domain} / {scope}")
            count += 1

        conn.commit()
        print(f"\nSeeded {count} decisions successfully.")
        return count
    except Exception as exc:
        conn.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


def verify_decisions() -> bool:
    """Verify that all 4 decisions exist and are ACTIVE.

    Returns:
        True if all decisions are present and ACTIVE.
    """
    try:
        import psycopg2  # noqa: PLC0415
    except ImportError:
        print(
            "ERROR: psycopg2 not installed. Install with: uv pip install psycopg2-binary",
            file=sys.stderr,
        )
        sys.exit(1)

    conn_str = get_connection_string()
    conn = psycopg2.connect(conn_str)
    try:
        cur = conn.cursor()
        cur.execute(SQL_QUERY_DECISIONS, {"epic_id": "OMN-2821"})
        rows = cur.fetchall()

        print(f"Found {len(rows)} ACTIVE decisions for epic OMN-2821:\n")

        expected_titles = {d.title for d in DECISIONS}
        found_titles: set[str] = set()

        for row in rows:
            (
                decision_id,
                title,
                decision_type,
                status,
                scope_domain,
                scope_services,
                scope_layer,
                _rationale,
                tags,
                _epic_id,
                _created_at,
            ) = row
            scope_svc = (
                json.loads(scope_services)
                if isinstance(scope_services, str)
                else scope_services
            )
            scope_display = "platform-wide" if not scope_svc else ", ".join(scope_svc)
            print(f"  [{decision_type}/{scope_layer}] {title}")
            print(f"    ID:     {decision_id}")
            print(f"    Status: {status}")
            print(f"    Scope:  {scope_domain} / {scope_display}")
            print(
                f"    Tags:   {', '.join(json.loads(tags) if isinstance(tags, str) else tags)}"
            )
            print()
            found_titles.add(title)

        missing = expected_titles - found_titles
        if missing:
            print(f"MISSING {len(missing)} decisions:")
            for t in sorted(missing):
                print(f"  - {t}")
            return False

        print("All 4 decisions verified: present and ACTIVE.")
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Seed architectural decisions into decision_store (OMN-2822)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print decisions without writing to database.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify that all decisions exist in the database.",
    )
    args = parser.parse_args()

    if args.verify:
        ok = verify_decisions()
        sys.exit(0 if ok else 1)

    seed_decisions(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
