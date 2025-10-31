"""
Detection Failure Tracker
Captures failed, missed, or low-confidence agent detections for system improvement
"""

import hashlib
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import psycopg2
from psycopg2.extras import Json


class DetectionFailureTracker:
    """Track detection failures for system improvement"""

    def __init__(self, db_password: str = None):
        password = db_password or os.getenv(
            "OMNINODE_BRIDGE_PASSWORD", "omninode-bridge-postgres-dev-2024"
        )
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5436")
        db = os.getenv("POSTGRES_DB", "omninode_bridge")
        user = os.getenv("POSTGRES_USER", "postgres")
        self.conn_string = (
            f"host={host} port={port} dbname={db} " f"user={user} password={password}"
        )

    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.conn_string)

    def _hash_prompt(self, prompt: str) -> str:
        """Generate SHA-256 hash of prompt for deduplication"""
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def record_failure(
        self,
        correlation_id: UUID,
        user_prompt: str,
        detection_status: str,
        detected_agent: Optional[str] = None,
        detection_confidence: Optional[float] = None,
        detection_method: Optional[str] = None,
        routing_duration_ms: Optional[int] = None,
        failure_reason: Optional[str] = None,
        failure_category: Optional[str] = None,
        trigger_matches: Optional[List[Dict]] = None,
        capability_scores: Optional[Dict] = None,
        fuzzy_match_results: Optional[List[Dict]] = None,
        detection_metadata: Optional[Dict] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        rag_query_performed: bool = False,
        rag_results_count: int = 0,
        rag_intelligence_used: bool = False,
    ) -> int:
        """
        Record a detection failure

        Args:
            correlation_id: Correlation ID for the request
            user_prompt: The user's prompt text
            detection_status: Type of failure (no_detection, low_confidence, wrong_agent, timeout, error)
            detected_agent: Agent that was detected (if any)
            detection_confidence: Confidence score (0.0-1.0)
            detection_method: How detection was performed
            routing_duration_ms: How long routing took
            failure_reason: Why detection failed
            failure_category: Category for reporting
            trigger_matches: Triggers that were evaluated
            capability_scores: Capability matching scores
            fuzzy_match_results: Fuzzy matching details
            detection_metadata: Additional debug info
            session_id: Session identifier
            user_id: User identifier
            rag_query_performed: Whether RAG query was performed
            rag_results_count: Number of RAG results
            rag_intelligence_used: Whether RAG intelligence was used

        Returns:
            ID of the created record
        """
        query = """
        INSERT INTO agent_detection_failures (
            correlation_id,
            session_id,
            user_id,
            user_prompt,
            prompt_length,
            prompt_hash,
            detection_status,
            detected_agent,
            detection_confidence,
            detection_method,
            routing_duration_ms,
            failure_reason,
            failure_category,
            trigger_matches,
            capability_scores,
            fuzzy_match_results,
            detection_metadata,
            rag_query_performed,
            rag_results_count,
            rag_intelligence_used
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
        """

        params = (
            str(correlation_id),
            session_id,
            user_id,
            user_prompt,
            len(user_prompt),
            self._hash_prompt(user_prompt),
            detection_status,
            detected_agent,
            detection_confidence,
            detection_method,
            routing_duration_ms,
            failure_reason,
            failure_category,
            Json(trigger_matches or []),
            Json(capability_scores or {}),
            Json(fuzzy_match_results or []),
            Json(detection_metadata or {}),
            rag_query_performed,
            rag_results_count,
            rag_intelligence_used,
        )

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                failure_id = cur.fetchone()[0]
                conn.commit()
                return failure_id

    def should_record_failure(
        self,
        detected_agent: Optional[str],
        detection_confidence: Optional[float],
        low_confidence_threshold: float = 0.85,
    ) -> tuple[bool, str, str]:
        """
        Determine if a detection should be recorded as a failure

        Args:
            detected_agent: Agent that was detected
            detection_confidence: Confidence score
            low_confidence_threshold: Minimum acceptable confidence

        Returns:
            Tuple of (should_record, detection_status, failure_reason)
        """
        # No detection at all
        if detected_agent is None or detected_agent == "":
            return (
                True,
                "no_detection",
                "No agent detected for user prompt",
            )

        # Low confidence detection
        if (
            detection_confidence is not None
            and detection_confidence < low_confidence_threshold
        ):
            return (
                True,
                "low_confidence",
                f"Detection confidence {detection_confidence:.2f} below threshold {low_confidence_threshold}",
            )

        # Detection looks good
        return (False, "", "")

    def get_recent_failures(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        unreviewed_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get recent detection failures

        Args:
            limit: Maximum number of results
            status: Filter by detection status
            unreviewed_only: Only return unreviewed failures

        Returns:
            List of failure records
        """
        conditions = []
        params = []

        if status:
            conditions.append("detection_status = %s")
            params.append(status)

        if unreviewed_only:
            conditions.append("reviewed = FALSE")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
        SELECT
            id,
            created_at,
            correlation_id,
            user_prompt,
            prompt_length,
            detection_status,
            detected_agent,
            detection_confidence,
            failure_reason,
            failure_category,
            reviewed
        FROM agent_detection_failures
        {where_clause}
        ORDER BY created_at DESC
        LIMIT %s
        """

        params.append(limit)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_failure_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get detection failure statistics"""
        query = "SELECT * FROM get_detection_failure_stats(%s)"

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (hours,))
                columns = [desc[0] for desc in cur.description]
                row = cur.fetchone()
                return dict(zip(columns, row)) if row else {}

    def mark_reviewed(
        self,
        failure_id: int,
        reviewed_by: str,
        expected_agent: Optional[str] = None,
        resolution_notes: Optional[str] = None,
    ):
        """Mark a failure as reviewed"""
        query = "SELECT mark_detection_failure_reviewed(%s, %s, %s, %s)"

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query, (failure_id, reviewed_by, expected_agent, resolution_notes)
                )
                conn.commit()

    def mark_pattern_improved(
        self,
        failure_id: int,
        update_type: str,
        update_details: Optional[Dict] = None,
    ):
        """Mark that a failure led to pattern improvements"""
        query = "SELECT mark_pattern_improved(%s, %s, %s)"

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query, (failure_id, update_type, Json(update_details or {}))
                )
                conn.commit()

    def get_failure_patterns(self) -> List[Dict[str, Any]]:
        """Get aggregated failure patterns"""
        query = "SELECT * FROM agent_detection_failure_patterns"

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]


# Singleton instance
_tracker_instance: Optional[DetectionFailureTracker] = None


def get_failure_tracker() -> DetectionFailureTracker:
    """Get singleton failure tracker instance"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = DetectionFailureTracker()
    return _tracker_instance
