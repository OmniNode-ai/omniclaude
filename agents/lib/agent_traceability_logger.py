"""
Agent Traceability Logger - Complete Execution Traceability

Provides comprehensive traceability for agent operations:
1. Prompt traceability - User prompts + agent instructions
2. File operation traceability - Every file read/write with hashes
3. Intelligence usage traceability - Patterns/schemas actually used

Features:
- SHA-256 content hashing for integrity verification
- Links to Archon intelligence DB (Qdrant, Memgraph, PostgreSQL)
- Kafka event streaming for real-time monitoring
- Non-blocking with fallback logging
- Correlation ID tracking through entire execution

Usage:
    tracer = AgentTraceabilityLogger(
        agent_name="agent-researcher",
        correlation_id=correlation_id
    )

    # Log user prompt
    await tracer.log_prompt(user_prompt, agent_instructions, manifest_id)

    # Log file operations
    await tracer.log_file_operation(
        operation_type="read",
        file_path="/path/to/file.py",
        content_before="...",
        content_after="..."
    )

    # Log intelligence usage
    await tracer.log_intelligence_usage(
        intelligence_type="pattern",
        intelligence_id=pattern_id,
        intelligence_name="Node State Management",
        was_applied=True
    )
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .db import get_pg_pool
from .structured_logger import StructuredLogger


def calculate_sha256(content: str) -> str:
    """
    Calculate SHA-256 hash of content.

    Args:
        content: Content to hash

    Returns:
        Hex string of SHA-256 hash
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class AgentTraceabilityLogger:
    """
    Comprehensive traceability logger for agent operations.

    Tracks:
    - User prompts and agent instructions
    - File operations with content hashes
    - Intelligence usage (patterns, schemas, debug intelligence)
    """

    def __init__(
        self,
        agent_name: str,
        correlation_id: UUID | str | None = None,
        session_id: UUID | str | None = None,
        execution_id: UUID | str | None = None,
        project_path: str | None = None,
        project_name: str | None = None,
        claude_session_id: str | None = None,
        terminal_id: str | None = None,
    ):
        """
        Initialize traceability logger.

        Args:
            agent_name: Name of the agent
            correlation_id: Correlation ID for request tracing
            session_id: Session ID for grouping related executions
            execution_id: Execution ID from AgentExecutionLogger
            project_path: Path to the project being worked on
            project_name: Name of the project
            claude_session_id: Claude session identifier
            terminal_id: Terminal identifier
        """
        self.agent_name = agent_name
        self.correlation_id = str(correlation_id) if correlation_id else str(uuid4())
        self.session_id = str(session_id) if session_id else None
        self.execution_id = str(execution_id) if execution_id else None
        self.project_path = project_path
        self.project_name = project_name
        self.claude_session_id = claude_session_id
        self.terminal_id = terminal_id

        # Track IDs for cross-references
        self.prompt_id: str | None = None
        self.manifest_injection_id: str | None = None

        # Structured logger
        self.logger = StructuredLogger(
            f"agent_traceability.{agent_name}", component=agent_name
        )
        self.logger.set_correlation_id(self.correlation_id)
        if self.session_id:
            self.logger.set_session_id(self.session_id)

        # Track DB availability
        self._db_available = True

    async def log_prompt(
        self,
        user_prompt: str,
        agent_instructions: str | None = None,
        manifest_injection_id: UUID | str | None = None,
        manifest_sections: list[str] | None = None,
        system_context: dict[str, Any] | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        attached_files: list[str] | None = None,
    ) -> str | None:
        """
        Log user prompt and agent instructions.

        Args:
            user_prompt: Original user request
            agent_instructions: Complete agent prompt with manifest injection
            manifest_injection_id: Link to manifest that was injected
            manifest_sections: Which sections were in the instructions
            system_context: System info (cwd, git status, environment)
            conversation_history: Previous messages in conversation
            attached_files: Files attached to prompt

        Returns:
            Prompt ID (UUID as string) or None on failure
        """
        try:
            pool = await get_pg_pool()
            if not pool:
                self.logger.warning("Database pool unavailable for prompt logging")
                return None

            # Calculate hashes
            user_prompt_hash = calculate_sha256(user_prompt)
            agent_instructions_hash = (
                calculate_sha256(agent_instructions) if agent_instructions else None
            )

            # Generate prompt ID
            prompt_id = str(uuid4())

            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    INSERT INTO agent_prompts (
                        id, correlation_id, session_id, execution_id,
                        agent_name, user_prompt, user_prompt_hash, user_prompt_length,
                        agent_instructions, agent_instructions_hash, agent_instructions_length,
                        manifest_injection_id, manifest_sections_included,
                        system_context, conversation_history, attached_files,
                        claude_session_id, terminal_id, project_path, project_name
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20
                    )
                    """,
                    prompt_id,
                    self.correlation_id,
                    self.session_id,
                    self.execution_id,
                    self.agent_name,
                    user_prompt,
                    user_prompt_hash,
                    len(user_prompt),
                    agent_instructions,
                    agent_instructions_hash,
                    len(agent_instructions) if agent_instructions else None,
                    str(manifest_injection_id) if manifest_injection_id else None,
                    manifest_sections,
                    json.dumps(system_context) if system_context else None,
                    json.dumps(conversation_history) if conversation_history else None,
                    attached_files,
                    self.claude_session_id,
                    self.terminal_id,
                    self.project_path,
                    self.project_name,
                )
                # Check if INSERT succeeded
                rows_inserted = int(result.split()[2])
                if rows_inserted == 0:
                    raise Exception(
                        f"Failed to insert agent prompt: prompt_id={prompt_id}, correlation_id={self.correlation_id}"
                    )

            self.prompt_id = prompt_id
            self.manifest_injection_id = (
                str(manifest_injection_id) if manifest_injection_id else None
            )

            self.logger.info(
                "Prompt traceability logged",
                metadata={
                    "prompt_id": prompt_id,
                    "user_prompt_length": len(user_prompt),
                    "agent_instructions_length": (
                        len(agent_instructions) if agent_instructions else 0
                    ),
                },
            )

            return prompt_id

        except Exception as e:
            self.logger.error(
                "Failed to log prompt traceability",
                metadata={"error": str(e), "correlation_id": self.correlation_id},
            )
            return None

    async def log_file_operation(
        self,
        operation_type: str,
        file_path: str,
        content_before: str | None = None,
        content_after: str | None = None,
        tool_name: str | None = None,
        line_range: dict[str, int] | None = None,
        operation_params: dict[str, Any] | None = None,
        intelligence_file_id: UUID | str | None = None,
        matched_pattern_ids: list[UUID | str] | None = None,
        success: bool = True,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> str | None:
        """
        Log file operation with content hashes.

        Args:
            operation_type: 'read', 'write', 'edit', 'delete', 'create', 'glob', 'grep'
            file_path: Absolute path to file
            content_before: File content before operation
            content_after: File content after operation
            tool_name: Tool used (Read, Write, Edit, Bash, etc)
            line_range: {"start": 1, "end": 100} for partial operations
            operation_params: Tool parameters
            intelligence_file_id: Link to Archon intelligence DB file record
            matched_pattern_ids: Pattern IDs that matched this file
            success: Whether operation succeeded
            error_message: Error if operation failed
            duration_ms: Operation duration

        Returns:
            File operation ID (UUID as string) or None on failure
        """
        try:
            pool = await get_pg_pool()
            if not pool:
                self.logger.warning(
                    "Database pool unavailable for file operation logging"
                )
                return None

            # Calculate hashes
            file_path_hash = calculate_sha256(file_path)
            content_hash_before = (
                calculate_sha256(content_before) if content_before else None
            )
            content_hash_after = (
                calculate_sha256(content_after) if content_after else None
            )
            content_changed = (
                content_hash_before != content_hash_after
                if content_hash_before and content_hash_after
                else False
            )

            # Extract file metadata
            path_obj = Path(file_path)
            file_name = path_obj.name
            file_extension = path_obj.suffix

            # Calculate file size and bytes
            file_size_bytes = None
            bytes_read = None
            bytes_written = None

            if content_after:
                file_size_bytes = len(content_after.encode("utf-8"))
                if operation_type in ("write", "edit", "create"):
                    bytes_written = file_size_bytes
            if content_before:
                if operation_type == "read":
                    bytes_read = len(content_before.encode("utf-8"))

            # Generate file operation ID
            file_op_id = str(uuid4())

            # Convert pattern IDs to strings
            matched_pattern_ids_str = (
                [str(pid) for pid in matched_pattern_ids]
                if matched_pattern_ids
                else None
            )

            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    INSERT INTO agent_file_operations (
                        id, correlation_id, execution_id, prompt_id,
                        agent_name, operation_type, file_path, file_path_hash,
                        file_name, file_extension, file_size_bytes,
                        content_hash_before, content_hash_after, content_changed,
                        intelligence_file_id, intelligence_pattern_match, matched_pattern_ids,
                        tool_name, line_range, operation_params,
                        success, error_message, bytes_read, bytes_written, duration_ms
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25
                    )
                    """,
                    file_op_id,
                    self.correlation_id,
                    self.execution_id,
                    self.prompt_id,
                    self.agent_name,
                    operation_type,
                    file_path,
                    file_path_hash,
                    file_name,
                    file_extension,
                    file_size_bytes,
                    content_hash_before,
                    content_hash_after,
                    content_changed,
                    str(intelligence_file_id) if intelligence_file_id else None,
                    bool(matched_pattern_ids),
                    matched_pattern_ids_str,
                    tool_name,
                    json.dumps(line_range) if line_range else None,
                    json.dumps(operation_params) if operation_params else None,
                    success,
                    error_message,
                    bytes_read,
                    bytes_written,
                    duration_ms,
                )
                # Check if INSERT succeeded
                rows_inserted = int(result.split()[2])
                if rows_inserted == 0:
                    raise Exception(
                        f"Failed to insert file operation: file_op_id={file_op_id}, correlation_id={self.correlation_id}"
                    )

            self.logger.info(
                f"File operation logged: {operation_type}",
                metadata={
                    "file_op_id": file_op_id,
                    "file_path": file_path,
                    "content_changed": content_changed,
                    "patterns_matched": (
                        len(matched_pattern_ids) if matched_pattern_ids else 0
                    ),
                },
            )

            return file_op_id

        except Exception as e:
            self.logger.error(
                f"Failed to log file operation: {operation_type}",
                metadata={
                    "error": str(e),
                    "file_path": file_path,
                    "correlation_id": self.correlation_id,
                },
            )
            return None

    async def log_intelligence_usage(
        self,
        intelligence_type: str,
        intelligence_source: str,
        intelligence_id: UUID | str | None = None,
        intelligence_name: str | None = None,
        collection_name: str | None = None,
        usage_context: str = "reference",
        usage_count: int = 1,
        confidence_score: float | None = None,
        intelligence_snapshot: dict[str, Any] | None = None,
        intelligence_summary: str | None = None,
        query_used: str | None = None,
        query_time_ms: int | None = None,
        query_results_rank: int | None = None,
        was_applied: bool = False,
        application_details: dict[str, Any] | None = None,
        file_operations_using_this: list[UUID | str] | None = None,
        contributed_to_success: bool | None = None,
        quality_impact: float | None = None,
    ) -> str | None:
        """
        Log intelligence usage (patterns, schemas, debug intelligence).

        Args:
            intelligence_type: 'pattern', 'schema', 'debug_intelligence', 'model', 'infrastructure'
            intelligence_source: 'qdrant', 'memgraph', 'postgres', 'archon-intelligence'
            intelligence_id: Qdrant point ID, Memgraph node ID, etc
            intelligence_name: Pattern name, schema name, etc
            collection_name: Qdrant collection (execution_patterns, code_patterns, etc)
            usage_context: 'reference', 'implementation', 'inspiration', 'validation'
            usage_count: How many times this intelligence was referenced
            confidence_score: Confidence/relevance score if available
            intelligence_snapshot: Complete intelligence data structure
            intelligence_summary: Human-readable summary
            query_used: Query that retrieved this intelligence
            query_time_ms: Query performance
            query_results_rank: Ranking in query results (1=top result)
            was_applied: Whether intelligence was actually used
            application_details: How it was applied
            file_operations_using_this: Links to agent_file_operations
            contributed_to_success: Whether this helped achieve success
            quality_impact: Estimated quality contribution (0.0-1.0)

        Returns:
            Intelligence usage ID (UUID as string) or None on failure
        """
        try:
            pool = await get_pg_pool()
            if not pool:
                self.logger.warning(
                    "Database pool unavailable for intelligence usage logging"
                )
                return None

            # Generate intelligence usage ID
            intel_usage_id = str(uuid4())

            # Convert file operation IDs to strings
            file_ops_str = (
                [str(fid) for fid in file_operations_using_this]
                if file_operations_using_this
                else None
            )

            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    INSERT INTO agent_intelligence_usage (
                        id, correlation_id, execution_id, manifest_injection_id, prompt_id,
                        agent_name, intelligence_type, intelligence_source,
                        intelligence_id, intelligence_name, collection_name,
                        usage_context, usage_count, confidence_score,
                        intelligence_snapshot, intelligence_summary,
                        query_used, query_time_ms, query_results_rank,
                        was_applied, application_details, file_operations_using_this,
                        contributed_to_success, quality_impact,
                        applied_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25
                    )
                    """,
                    intel_usage_id,
                    self.correlation_id,
                    self.execution_id,
                    self.manifest_injection_id,
                    self.prompt_id,
                    self.agent_name,
                    intelligence_type,
                    intelligence_source,
                    str(intelligence_id) if intelligence_id else None,
                    intelligence_name,
                    collection_name,
                    usage_context,
                    usage_count,
                    confidence_score,
                    (
                        json.dumps(intelligence_snapshot)
                        if intelligence_snapshot
                        else None
                    ),
                    intelligence_summary,
                    query_used,
                    query_time_ms,
                    query_results_rank,
                    was_applied,
                    json.dumps(application_details) if application_details else None,
                    file_ops_str,
                    contributed_to_success,
                    quality_impact,
                    datetime.now(timezone.utc) if was_applied else None,
                )
                # Check if INSERT succeeded
                rows_inserted = int(result.split()[2])
                if rows_inserted == 0:
                    raise Exception(
                        f"Failed to insert intelligence usage: intel_usage_id={intel_usage_id}, correlation_id={self.correlation_id}"
                    )

            self.logger.info(
                f"Intelligence usage logged: {intelligence_type}",
                metadata={
                    "intel_usage_id": intel_usage_id,
                    "intelligence_name": intelligence_name,
                    "was_applied": was_applied,
                    "quality_impact": quality_impact,
                },
            )

            return intel_usage_id

        except Exception as e:
            self.logger.error(
                f"Failed to log intelligence usage: {intelligence_type}",
                metadata={
                    "error": str(e),
                    "intelligence_name": intelligence_name,
                    "correlation_id": self.correlation_id,
                },
            )
            return None

    async def get_complete_trace(self) -> dict[str, Any] | None:
        """
        Get complete execution trace for this correlation ID.

        Returns:
            Complete trace data or None on failure
        """
        try:
            pool = await get_pg_pool()
            if not pool:
                return None

            async with pool.acquire() as conn:
                # Use the get_complete_trace function
                rows = await conn.fetch(
                    "SELECT * FROM get_complete_trace($1::UUID)",
                    self.correlation_id,
                )

            # Group by trace type
            trace_data: dict[str, list[Any]] = {
                "prompt": [],
                "file_operation": [],
                "intelligence_usage": [],
                "manifest": [],
                "execution": [],
            }

            for row in rows:
                trace_type = row["trace_type"]
                data = row["data"]
                if trace_type in trace_data:
                    trace_data[trace_type].append(data)

            return trace_data

        except Exception as e:
            self.logger.error(
                "Failed to get complete trace",
                metadata={"error": str(e), "correlation_id": self.correlation_id},
            )
            return None


async def create_traceability_logger(
    agent_name: str,
    correlation_id: UUID | str | None = None,
    session_id: UUID | str | None = None,
    execution_id: UUID | str | None = None,
    project_path: str | None = None,
    project_name: str | None = None,
    claude_session_id: str | None = None,
    terminal_id: str | None = None,
) -> AgentTraceabilityLogger:
    """
    Factory function to create traceability logger.

    Args:
        agent_name: Name of the agent
        correlation_id: Correlation ID for tracing
        session_id: Session ID for grouping
        execution_id: Execution ID from AgentExecutionLogger
        project_path: Path to the project being worked on
        project_name: Name of the project
        claude_session_id: Claude session identifier
        terminal_id: Terminal identifier

    Returns:
        AgentTraceabilityLogger instance

    Example:
        tracer = await create_traceability_logger(
            agent_name="agent-researcher",
            correlation_id=correlation_id,
            execution_id=execution_id
        )

        await tracer.log_prompt(user_prompt, agent_instructions)
        await tracer.log_file_operation("read", "/path/to/file.py", content=content)
        await tracer.log_intelligence_usage("pattern", "qdrant", pattern_id, "Node State")
    """
    return AgentTraceabilityLogger(
        agent_name=agent_name,
        correlation_id=correlation_id,
        session_id=session_id,
        execution_id=execution_id,
        project_path=project_path,
        project_name=project_name,
        claude_session_id=claude_session_id,
        terminal_id=terminal_id,
    )
