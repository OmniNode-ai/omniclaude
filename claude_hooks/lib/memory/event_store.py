#!/usr/bin/env python3
"""
Event Memory Store - Phase 1.2

Event-sourcing storage system that tracks complete workflows from
intent detection through validation, correction, and final outcome.

Features:
- Qdrant vector storage for similarity search
- SQLite fallback for reliability
- <100ms event recording
- Correlation ID-based workflow tracking
- Success pattern discovery via embeddings
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import Pydantic Settings for type-safe configuration
from config import settings

from .event_models import EventType, IntentContextData, WorkflowEvent

logger = logging.getLogger(__name__)


class EventStore:
    """
    Event-sourcing storage for workflow tracking.

    Provides dual storage:
    1. Qdrant vector store for semantic similarity search
    2. SQLite for reliable event log and quick queries

    Performance targets:
    - Record event: <100ms
    - Get workflow: <50ms
    - Find similar: <200ms (vector search)
    """

    def __init__(
        self,
        storage_path: Path,
        qdrant_url: str | None = None,
        ollama_url: str = "http://192.168.86.200:11434",
        retention_days: int = 90,
    ):
        """
        Initialize Event Store.

        Args:
            storage_path: Path to SQLite database
            qdrant_url: Qdrant server URL for vector storage (defaults to settings.qdrant_url if not provided)
            ollama_url: Ollama server for embeddings
            retention_days: Days to retain events (default 90)
        """
        # Use Pydantic settings if qdrant_url not explicitly provided
        if qdrant_url is None:
            qdrant_url = settings.qdrant_url

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self.qdrant_url = qdrant_url
        self.ollama_url = ollama_url
        self.retention_days = retention_days

        # Initialize storage backends
        self._init_sqlite()
        self._qdrant_available = self._init_qdrant()

        # Embedding cache for performance
        self._embedding_cache: Dict[str, List[float]] = {}

        logger.info(
            f"Event Store initialized - SQLite: {self.storage_path}, "
            f"Qdrant: {'available' if self._qdrant_available else 'unavailable'}"
        )

    def _init_sqlite(self) -> None:
        """Initialize SQLite database with schema."""
        conn = sqlite3.connect(str(self.storage_path))
        cursor = conn.cursor()

        # Events table - stores all workflow events
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                correlation_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                intent_json TEXT,
                violations_json TEXT,
                corrections_json TEXT,
                scores_json TEXT,
                success INTEGER,
                iteration_number INTEGER DEFAULT 1,
                parent_event_id TEXT,
                metadata_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Indexes for fast queries
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_correlation_id
            ON events(correlation_id)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_type
            ON events(event_type)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON events(timestamp)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_success
            ON events(success)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_file_path
            ON events(file_path)
        """
        )

        conn.commit()
        conn.close()

    def _init_qdrant(self) -> bool:
        """
        Initialize Qdrant vector storage.

        Returns:
            True if Qdrant available, False for SQLite-only mode
        """
        try:
            import httpx

            # Check Qdrant availability
            response = httpx.get(f"{self.qdrant_url}/collections", timeout=2.0)

            if response.status_code == 200:
                # Check if our collection exists
                collections = response.json().get("result", {}).get("collections", [])
                collection_names = [c["name"] for c in collections]

                if "workflow_events" not in collection_names:
                    # Create collection for workflow events
                    self._create_qdrant_collection()

                logger.info("Qdrant vector storage available")
                return True
            else:
                logger.warning(
                    f"Qdrant returned status {response.status_code}, using SQLite only"
                )
                return False

        except Exception as e:
            logger.warning(f"Qdrant unavailable, using SQLite only: {e}")
            return False

    def _create_qdrant_collection(self) -> None:
        """Create Qdrant collection for workflow events."""
        import httpx

        # Use nomic-embed-text model (768 dimensions)
        collection_config = {"vectors": {"size": 768, "distance": "Cosine"}}

        response = httpx.put(
            f"{self.qdrant_url}/collections/workflow_events",
            json=collection_config,
            timeout=5.0,
        )

        if response.status_code in [200, 201]:
            logger.info("Created Qdrant collection: workflow_events")
        else:
            logger.error(f"Failed to create Qdrant collection: {response.text}")

    def record_event(self, event: WorkflowEvent) -> bool:
        """
        Record workflow event to storage.

        Performance target: <100ms

        Args:
            event: WorkflowEvent to record

        Returns:
            True if successful
        """
        start_time = time.time()

        try:
            # Store in SQLite (always)
            self._store_event_sqlite(event)

            # Store in Qdrant (if available and event is successful)
            if self._qdrant_available and event.success:
                try:
                    self._store_event_qdrant(event)
                except Exception as e:
                    logger.warning(f"Qdrant storage failed (continuing): {e}")

            duration_ms = (time.time() - start_time) * 1000
            logger.debug(f"Recorded event {event.event_id} in {duration_ms:.1f}ms")

            return True

        except Exception as e:
            logger.error(f"Failed to record event {event.event_id}: {e}")
            return False

    def _store_event_sqlite(self, event: WorkflowEvent) -> None:
        """Store event in SQLite."""
        conn = sqlite3.connect(str(self.storage_path))
        cursor = conn.cursor()

        # Serialize complex fields to JSON
        intent_json = json.dumps(event.intent.to_dict()) if event.intent else None
        violations_json = (
            json.dumps([v.to_dict() for v in event.violations])
            if event.violations
            else None
        )
        corrections_json = (
            json.dumps([c.to_dict() for c in event.corrections])
            if event.corrections
            else None
        )
        scores_json = json.dumps(event.scores.to_dict()) if event.scores else None
        metadata_json = json.dumps(event.metadata)

        cursor.execute(
            """
            INSERT INTO events (
                event_id, correlation_id, timestamp, event_type,
                tool_name, file_path, content_hash,
                intent_json, violations_json, corrections_json, scores_json,
                success, iteration_number, parent_event_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                event.event_id,
                event.correlation_id,
                event.timestamp.isoformat(),
                event.event_type.value,
                event.tool_name,
                event.file_path,
                event.content_hash,
                intent_json,
                violations_json,
                corrections_json,
                scores_json,
                1 if event.success else 0,
                event.iteration_number,
                event.parent_event_id,
                metadata_json,
            ),
        )

        conn.commit()
        conn.close()

    def _store_event_qdrant(self, event: WorkflowEvent) -> None:
        """Store successful event in Qdrant for similarity search."""
        import httpx

        # Generate embedding for event context
        embedding_text = self._create_embedding_text(event)
        embedding = self._get_embedding(embedding_text)

        if not embedding:
            logger.warning(f"Could not generate embedding for event {event.event_id}")
            return

        # Store in Qdrant
        point = {
            "id": event.event_id,
            "vector": embedding,
            "payload": {
                "correlation_id": event.correlation_id,
                "event_type": event.event_type.value,
                "tool_name": event.tool_name,
                "file_path": event.file_path,
                "timestamp": event.timestamp.isoformat(),
                "success": event.success,
                "intent_category": (
                    event.intent.primary_intent if event.intent else "unknown"
                ),
                "embedding_text": embedding_text,
            },
        }

        response = httpx.put(
            f"{self.qdrant_url}/collections/workflow_events/points",
            json={"points": [point]},
            timeout=3.0,
        )

        if response.status_code not in [200, 201]:
            logger.warning(f"Qdrant storage failed: {response.text}")

    def _create_embedding_text(self, event: WorkflowEvent) -> str:
        """
        Create text representation for embedding generation.

        Combines key event details into semantic representation.
        """
        parts = [
            f"Tool: {event.tool_name}",
            f"File: {Path(event.file_path).name}",
            f"Event: {event.event_type.value}",
        ]

        if event.intent:
            parts.append(f"Intent: {event.intent.primary_intent}")
            parts.append(f"Rules: {', '.join(event.intent.onex_rules)}")

        if event.violations:
            parts.append(f"Violations: {len(event.violations)}")

        if event.corrections:
            corrections_text = [c.reasoning for c in event.corrections if c.applied]
            if corrections_text:
                parts.append(f"Corrections: {'; '.join(corrections_text)}")

        return " | ".join(parts)

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding using Ollama.

        Uses nomic-embed-text model (768 dimensions).
        Includes caching for performance.

        Args:
            text: Text to embed

        Returns:
            768-dimensional embedding vector or None if failed
        """
        # Check cache
        if text in self._embedding_cache:
            return self._embedding_cache[text]

        try:
            import httpx

            response = httpx.post(
                f"{self.ollama_url}/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": text},
                timeout=5.0,
            )

            if response.status_code == 200:
                embedding = response.json().get("embedding")

                # Cache for future use
                self._embedding_cache[text] = embedding

                return embedding
            else:
                logger.warning(f"Ollama embedding failed: {response.status_code}")
                return None

        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None

    def get_workflow(self, correlation_id: str) -> List[WorkflowEvent]:
        """
        Get all events for a workflow.

        Performance target: <50ms

        Args:
            correlation_id: Workflow identifier

        Returns:
            List of events in chronological order
        """
        conn = sqlite3.connect(str(self.storage_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM events
            WHERE correlation_id = ?
            ORDER BY timestamp ASC
        """,
            (correlation_id,),
        )

        rows = cursor.fetchall()
        conn.close()

        # Convert rows to WorkflowEvent objects
        events = []
        for row in rows:
            event = self._row_to_event(row)
            events.append(event)

        return events

    def _row_to_event(self, row: sqlite3.Row) -> WorkflowEvent:
        """Convert SQLite row to WorkflowEvent."""
        # Parse JSON fields
        intent = None
        if row["intent_json"]:
            intent_data = json.loads(row["intent_json"])
            intent = IntentContextData(**intent_data)

        violations = None
        if row["violations_json"]:
            from .event_models import Violation

            violations_data = json.loads(row["violations_json"])
            violations = [Violation(**v) for v in violations_data]

        corrections = None
        if row["corrections_json"]:
            from .event_models import Correction

            corrections_data = json.loads(row["corrections_json"])
            corrections = [Correction(**c) for c in corrections_data]

        scores = None
        if row["scores_json"]:
            from .event_models import AIQuorumScore

            scores_data = json.loads(row["scores_json"])
            scores = AIQuorumScore(**scores_data)

        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}

        return WorkflowEvent(
            event_id=row["event_id"],
            correlation_id=row["correlation_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            event_type=EventType(row["event_type"]),
            tool_name=row["tool_name"],
            file_path=row["file_path"],
            content_hash=row["content_hash"],
            intent=intent,
            violations=violations,
            corrections=corrections,
            scores=scores,
            success=bool(row["success"]) if row["success"] is not None else None,
            iteration_number=row["iteration_number"],
            parent_event_id=row["parent_event_id"],
            metadata=metadata,
        )

    def find_similar_successes(
        self, query_event: WorkflowEvent, limit: int = 5, threshold: float = 0.7
    ) -> List[Tuple[WorkflowEvent, float]]:
        """
        Find similar successful workflows using vector search.

        Performance target: <200ms

        Args:
            query_event: Event to find similar workflows for
            limit: Maximum number of results
            threshold: Minimum similarity score (0.0-1.0)

        Returns:
            List of (event, similarity_score) tuples
        """
        if not self._qdrant_available:
            logger.warning("Qdrant unavailable, using SQLite fallback for similarity")
            return self._find_similar_sqlite(query_event, limit)

        try:
            import httpx

            # Generate embedding for query
            embedding_text = self._create_embedding_text(query_event)
            query_embedding = self._get_embedding(embedding_text)

            if not query_embedding:
                return []

            # Search Qdrant
            search_request = {
                "vector": query_embedding,
                "limit": limit,
                "score_threshold": threshold,
                "with_payload": True,
                "filter": {"must": [{"key": "success", "match": {"value": True}}]},
            }

            response = httpx.post(
                f"{self.qdrant_url}/collections/workflow_events/points/search",
                json=search_request,
                timeout=3.0,
            )

            if response.status_code != 200:
                logger.warning(f"Qdrant search failed: {response.text}")
                return []

            results = response.json().get("result", [])

            # Fetch full events from SQLite
            similar_events = []
            for result in results:
                event_id = result["id"]
                score = result["score"]

                # Get full event from SQLite
                event = self._get_event_by_id(event_id)
                if event:
                    similar_events.append((event, score))

            return similar_events

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def _find_similar_sqlite(
        self, query_event: WorkflowEvent, limit: int
    ) -> List[Tuple[WorkflowEvent, float]]:
        """
        Fallback similarity search using SQLite.

        Uses simple matching on intent category and tool name.
        """
        if not query_event.intent:
            return []

        conn = sqlite3.connect(str(self.storage_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find successful events with same intent category
        cursor.execute(
            """
            SELECT * FROM events
            WHERE success = 1
              AND event_type = ?
              AND tool_name = ?
              AND intent_json LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (
                EventType.WRITE_SUCCESS.value,
                query_event.tool_name,
                f"%{query_event.intent.primary_intent}%",
                limit,
            ),
        )

        rows = cursor.fetchall()
        conn.close()

        # Convert to events with dummy similarity score
        similar_events = []
        for row in rows:
            event = self._row_to_event(row)
            similar_events.append((event, 0.8))  # Dummy score

        return similar_events

    def _get_event_by_id(self, event_id: str) -> Optional[WorkflowEvent]:
        """Get single event by ID."""
        conn = sqlite3.connect(str(self.storage_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_event(row)
        return None

    def get_recent_workflows(
        self, days: int = 7, success_only: bool = False
    ) -> List[str]:
        """
        Get recent workflow correlation IDs.

        Args:
            days: Number of days to look back
            success_only: Only return successful workflows

        Returns:
            List of correlation IDs
        """
        conn = sqlite3.connect(str(self.storage_path))
        cursor = conn.cursor()

        cutoff = datetime.utcnow() - timedelta(days=days)

        query = """
            SELECT DISTINCT correlation_id
            FROM events
            WHERE timestamp >= ?
        """

        if success_only:
            query += " AND success = 1"

        query += " ORDER BY timestamp DESC"

        cursor.execute(query, (cutoff.isoformat(),))
        rows = cursor.fetchall()
        conn.close()

        return [row[0] for row in rows]

    def cleanup_old_events(self) -> int:
        """
        Remove events older than retention period.

        Returns:
            Number of events removed
        """
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)

        conn = sqlite3.connect(str(self.storage_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM events
            WHERE timestamp < ?
        """,
            (cutoff.isoformat(),),
        )

        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(
            f"Cleaned up {deleted_count} events older than {self.retention_days} days"
        )
        return deleted_count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dict with event counts, success rates, etc.
        """
        conn = sqlite3.connect(str(self.storage_path))
        cursor = conn.cursor()

        stats = {}

        # Total events
        cursor.execute("SELECT COUNT(*) FROM events")
        stats["total_events"] = cursor.fetchone()[0]

        # Success rate
        cursor.execute("SELECT COUNT(*) FROM events WHERE success = 1")
        success_count = cursor.fetchone()[0]
        stats["success_count"] = success_count
        stats["success_rate"] = (
            success_count / stats["total_events"] if stats["total_events"] > 0 else 0.0
        )

        # Events by type
        cursor.execute(
            """
            SELECT event_type, COUNT(*)
            FROM events
            GROUP BY event_type
        """
        )
        stats["events_by_type"] = dict(cursor.fetchall())

        # Unique workflows
        cursor.execute("SELECT COUNT(DISTINCT correlation_id) FROM events")
        stats["unique_workflows"] = cursor.fetchone()[0]

        conn.close()

        return stats
