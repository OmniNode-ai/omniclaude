"""
NodeContextRewriterCompute - Pure Context Rewriting Logic

This node rewrites conversation context by pruning stale messages, formatting
intelligence manifests, and managing token budgets.

Type: ONEX Compute Node
Characteristics:
- **Pure function** - No I/O, no side effects
- **Deterministic** - Same input always produces same output
- **Cacheable** - Results can be cached for identical inputs
- **Fast** - Target <100ms processing time

Key Responsibilities:
1. Message Pruning - Keep recent + relevant + tool-heavy messages
2. Intelligence Manifest Formatting - Format patterns, examples, debug intel
3. Manifest Injection - Append manifest to system prompt
4. Token Budget Management - Ensure total < 180K tokens (20K buffer)

Event Flow:
1. Consume: context.rewrite.requested.v1
2. Process: Prune messages, format manifest, inject into system prompt
3. Publish: context.rewrite.completed.v1

Performance Targets:
- Processing time: <100ms
- Token accuracy: ±2% (tiktoken estimation)
- Token limit: <180K (20K buffer for response)
"""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from config import settings

try:
    import tiktoken
except ImportError:
    tiktoken = None
    logging.warning("tiktoken not available - token counting will use approximation")

from ..models.event_envelope import (
    ContextRewriteCompletedEvent,
    ContextFailedEvent,
    EventType,
    KafkaTopics,
)

logger = logging.getLogger(__name__)


class NodeContextRewriterCompute:
    """
    Compute node for context rewriting.

    Pure computation:
    - No I/O operations
    - Deterministic (same input → same output)
    - Cacheable results
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        token_limit: int = 180000,  # Leave 20K buffer for response
        recent_message_count: int = 20,
    ):
        """
        Initialize context rewriter node.

        Args:
            bootstrap_servers: Kafka bootstrap servers (default from settings)
            token_limit: Maximum total tokens (default 180K)
            recent_message_count: Number of recent messages to always keep
        """
        self.bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self.token_limit = token_limit
        self.recent_message_count = recent_message_count

        # Tokenizer (for accurate token counting)
        if tiktoken:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        else:
            self.encoding = None

        # Kafka consumer/producer (initialized in start())
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.producer: Optional[AIOKafkaProducer] = None

        # Running flag
        self._running = False

        logger.info("NodeContextRewriterCompute initialized (Pure computation node)")

    async def start(self) -> None:
        """Start Kafka consumer and producer."""
        logger.info("Starting NodeContextRewriterCompute...")

        # Create Kafka consumer
        self.consumer = AIOKafkaConsumer(
            KafkaTopics.CONTEXT_REWRITE_REQUESTED,
            bootstrap_servers=self.bootstrap_servers,
            group_id="context-rewriter-group",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
        )

        # Create Kafka producer
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        # Start connections (clean up on partial failure)
        try:
            await self.consumer.start()
            await self.producer.start()
        except Exception:
            if self.consumer:
                await self.consumer.stop()
            if self.producer:
                await self.producer.stop()
            raise

        self._running = True
        logger.info("NodeContextRewriterCompute started successfully")

    async def stop(self) -> None:
        """Stop Kafka consumer and producer."""
        logger.info("Stopping NodeContextRewriterCompute...")
        self._running = False

        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()

        logger.info("NodeContextRewriterCompute stopped")

    async def run(self) -> None:
        """
        Main event loop - processes context rewriting requests.

        For each request:
        1. Extract messages, system prompt, intelligence
        2. Prune messages (recent + relevant + tool-heavy)
        3. Format intelligence manifest
        4. Inject manifest into system prompt
        5. Ensure token limit (<180K)
        6. Publish completed event
        """
        if not self.consumer:
            raise RuntimeError("Consumer not started - call start() first")

        logger.info("NodeContextRewriterCompute event loop started")

        try:
            async for message in self.consumer:
                if not self._running:
                    break

                try:
                    # Parse event
                    event = message.value
                    correlation_id = event.get("correlation_id")
                    payload = event.get("payload", {})

                    if not correlation_id:
                        logger.warning("Received event missing correlation_id, skipping")
                        continue

                    logger.info(f"Processing context rewrite (correlation_id={correlation_id})")

                    # Process rewrite (async task to avoid blocking)
                    asyncio.create_task(
                        self._process_context_rewrite(
                            correlation_id=correlation_id,
                            messages=payload.get("messages", []),
                            system_prompt=payload.get("system_prompt", ""),
                            intelligence=payload.get("intelligence", {}),
                            intent=payload.get("intent", {}),
                        )
                    )

                except Exception as e:
                    logger.error(f"Error processing rewrite event: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Fatal error in context rewriter event loop: {e}", exc_info=True)
            raise

    async def _process_context_rewrite(
        self,
        correlation_id: str,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        intelligence: Dict[str, Any],
        intent: Dict[str, Any],
    ) -> None:
        """
        Process context rewriting (pure computation).

        Args:
            correlation_id: Request correlation ID
            messages: Original message array
            system_prompt: Original system prompt
            intelligence: Intelligence data from query effect
            intent: Extracted intent (task_type, entities, operations, files)
        """
        start_time = asyncio.get_running_loop().time()

        try:
            # Count tokens before
            tokens_before = self._count_tokens_in_messages(messages) + self._count_tokens(
                system_prompt
            )

            logger.info(
                f"Context rewrite started: {len(messages)} messages, "
                f"{tokens_before} tokens (correlation_id={correlation_id})"
            )

            # Step 1: Prune messages (keep recent + relevant + tool-heavy)
            pruned_messages = self._prune_messages(messages, intent)

            # Step 2: Format intelligence manifest
            manifest = self._build_intelligence_manifest(intelligence, intent)

            # Step 3: Inject manifest into system prompt
            enhanced_system = f"{system_prompt}\n\n{manifest}"

            # Step 4: Ensure token limit (<180K)
            final_messages, final_system = self._ensure_token_limit(
                pruned_messages, enhanced_system
            )

            # Count tokens after
            tokens_after = self._count_tokens_in_messages(final_messages) + self._count_tokens(
                final_system
            )

            end_time = asyncio.get_running_loop().time()
            processing_time_ms = int((end_time - start_time) * 1000)

            logger.info(
                f"Context rewrite completed: {len(messages)} → {len(final_messages)} messages, "
                f"{tokens_before} → {tokens_after} tokens, {processing_time_ms}ms "
                f"(correlation_id={correlation_id})"
            )

            # Publish completed event
            await self._publish_completed(
                correlation_id=correlation_id,
                messages=final_messages,
                system=final_system,
                messages_before=len(messages),
                messages_after=len(final_messages),
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                processing_time_ms=processing_time_ms,
            )

        except Exception as e:
            logger.error(f"Context rewrite error (correlation_id={correlation_id}): {e}", exc_info=True)
            await self._publish_error(correlation_id, str(e))

    def _prune_messages(
        self, messages: List[Dict[str, Any]], intent: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Prune messages keeping recent + relevant + tool-heavy.

        Strategy:
        1. Keep recent messages (last N)
        2. Keep tool-heavy messages (Read, Edit, Bash)
        3. Keep messages relevant to intent

        Args:
            messages: Original message array
            intent: Extracted intent

        Returns:
            Pruned message array
        """
        if len(messages) <= self.recent_message_count:
            # Short conversation, keep all
            return messages

        # Recent messages (always keep)
        recent = messages[-self.recent_message_count :]

        # Tool-heavy messages
        tool_heavy = self._find_tool_heavy(messages[: -self.recent_message_count])

        # Relevant messages
        relevant = self._find_relevant(messages[: -self.recent_message_count], intent)

        # Combine (with deduplication)
        kept_messages = self._deduplicate_messages(recent + tool_heavy + relevant)

        # Sort by original order
        original_indices = {id(msg): i for i, msg in enumerate(messages)}
        kept_messages.sort(key=lambda msg: original_indices.get(id(msg), float("inf")))

        return kept_messages

    def _find_tool_heavy(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find messages with tool usage."""
        tool_messages = []
        tool_keywords = ["Read", "Edit", "Write", "Bash", "Grep", "Glob", "Task"]

        for msg in messages:
            content = str(msg.get("content", ""))
            if any(tool in content for tool in tool_keywords):
                tool_messages.append(msg)

        return tool_messages

    def _find_relevant(
        self, messages: List[Dict[str, Any]], intent: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Find messages relevant to current intent."""
        relevant = []
        entities = intent.get("entities", [])
        files = intent.get("files", [])
        operations = intent.get("operations", [])

        for msg in messages:
            content = str(msg.get("content", "")).lower()

            # Check for entity overlap
            if any(entity.lower() in content for entity in entities):
                relevant.append(msg)
                continue

            # Check for file references
            if any(file in content for file in files):
                relevant.append(msg)
                continue

            # Check for operation keywords
            if any(op in content for op in operations):
                relevant.append(msg)

        return relevant

    def _deduplicate_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate messages (preserve order)."""
        seen = set()
        unique = []
        for msg in messages:
            msg_id = id(msg)
            if msg_id not in seen:
                seen.add(msg_id)
                unique.append(msg)
        return unique

    def _build_intelligence_manifest(
        self, intelligence: Dict[str, Any], intent: Dict[str, Any]
    ) -> str:
        """
        Build intelligence manifest (same format as agent manifests).

        Args:
            intelligence: Intelligence data from query effect
            intent: Extracted intent

        Returns:
            Formatted manifest string
        """
        parts = []

        # Header
        parts.append(
            """
======================================================================
INTELLIGENCE CONTEXT (Dynamic)
======================================================================
"""
        )

        # Intent Summary
        task_type = intent.get("task_type", "unknown")
        entities = intent.get("entities", [])
        operations = intent.get("operations", [])
        files = intent.get("files", [])
        confidence = intent.get("confidence", 0.0)

        parts.append(
            f"""
## DETECTED INTENT
- Task Type: {task_type}
- Entities: {', '.join(entities) if entities else 'None'}
- Operations: {', '.join(operations) if operations else 'None'}
- Files: {', '.join(files) if files else 'None'}
- Confidence: {confidence:.0%}
"""
        )

        # Execution Patterns (from Qdrant)
        patterns = intelligence.get("patterns", [])
        if patterns:
            parts.append(
                f"""
## RELEVANT EXECUTION PATTERNS ({len(patterns)} found)
"""
            )
            for pattern in patterns[:10]:  # Top 10
                name = pattern.get("name", "Unknown Pattern")
                confidence = pattern.get("score", 0.0)
                file_path = pattern.get("file_path", "unknown")
                node_types = pattern.get("metadata", {}).get("node_type", [])
                if isinstance(node_types, str):
                    node_types = [node_types]

                parts.append(
                    f"""
- **{name}** ({confidence:.0%} match)
  File: {file_path}
  Node Types: {', '.join(node_types) if node_types else 'N/A'}
"""
                )

        # Debug Intelligence (from PostgreSQL)
        debug_intel = intelligence.get("debug_intelligence", {})
        successes = debug_intel.get("successful_approaches", [])
        failures = debug_intel.get("failed_approaches", [])

        if successes or failures:
            parts.append(
                f"""
## DEBUG INTELLIGENCE (Similar Workflows)
Total Similar: {len(successes)} successes, {len(failures)} failures
"""
            )

            if successes:
                parts.append(
                    """
✅ **SUCCESSFUL APPROACHES** (what worked):
"""
                )
                for success in successes[:5]:
                    approach = success.get("approach", "Unknown")
                    quality = success.get("quality_score", 0.0)
                    parts.append(f"  - {approach} (quality: {quality:.0%})")

            if failures:
                parts.append(
                    """
❌ **FAILED APPROACHES** (avoid these):
"""
                )
                for failure in failures[:3]:
                    approach = failure.get("approach", "Unknown")
                    reason = failure.get("failure_reason", "Unknown")
                    parts.append(f"  - {approach} (reason: {reason})")

        # Footer
        parts.append(
            """
======================================================================
"""
        )

        return "\n".join(parts)

    def _ensure_token_limit(
        self, messages: List[Dict[str, Any]], system_prompt: str
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Ensure total tokens don't exceed limit.

        Args:
            messages: Message array
            system_prompt: System prompt

        Returns:
            (messages, system_prompt) tuple with tokens under limit
        """
        # Estimate tokens
        message_tokens = self._count_tokens_in_messages(messages)
        system_tokens = self._count_tokens(system_prompt)
        total_tokens = message_tokens + system_tokens

        if total_tokens <= self.token_limit:
            return messages, system_prompt

        logger.warning(
            f"Token limit exceeded: {total_tokens} > {self.token_limit}, pruning more aggressively"
        )

        # Over limit - prune messages more aggressively
        if message_tokens > self.token_limit * 0.7:  # Messages taking >70%
            # Keep fewer messages
            target_messages = int(self.token_limit / 200)  # Rough estimate
            messages = messages[-target_messages:]

        # Recalculate
        message_tokens = self._count_tokens_in_messages(messages)
        total_tokens = message_tokens + self._count_tokens(system_prompt)

        if total_tokens <= self.token_limit:
            return messages, system_prompt

        # Still over - truncate manifest
        allowed_system_tokens = self.token_limit - message_tokens
        max_system_chars = allowed_system_tokens * 4  # Rough estimate

        if len(system_prompt) > max_system_chars:
            system_prompt = (
                system_prompt[:max_system_chars] + "\n\n[Truncated due to token limit]"
            )
            logger.warning(f"Truncated system prompt to {max_system_chars} characters")

        return messages, system_prompt

    def _count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Text to count

        Returns:
            Token count
        """
        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except Exception as e:
                logger.warning(f"Token counting failed, using approximation: {e}")

        # Fallback: approximate (1 token ~= 4 characters)
        return len(text) // 4

    def _count_tokens_in_messages(self, messages: List[Dict[str, Any]]) -> int:
        """
        Count tokens in message array.

        Args:
            messages: Message array

        Returns:
            Total token count
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multi-part content
                for part in content:
                    if part.get("type") == "text":
                        total += self._count_tokens(part.get("text", ""))
            else:
                total += self._count_tokens(str(content))

        return total

    async def _publish_completed(
        self,
        correlation_id: str,
        messages: List[Dict[str, Any]],
        system: str,
        messages_before: int,
        messages_after: int,
        tokens_before: int,
        tokens_after: int,
        processing_time_ms: int,
    ) -> None:
        """
        Publish completed event with rewritten context.

        Args:
            correlation_id: Request correlation ID
            messages: Rewritten message array
            system: Enhanced system prompt with manifest
            messages_before: Message count before pruning
            messages_after: Message count after pruning
            tokens_before: Token count before
            tokens_after: Token count after
            processing_time_ms: Processing time
        """
        if not self.producer:
            logger.warning("Producer not available - cannot publish completed event")
            return

        try:
            # Create completed event
            event = ContextRewriteCompletedEvent(
                correlation_id=correlation_id,
                payload={
                    "messages": messages,
                    "system": system,
                    "messages_before": messages_before,
                    "messages_after": messages_after,
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_after,
                    "processing_time_ms": processing_time_ms,
                },
            )

            # Publish event
            await self.producer.send_and_wait(
                topic=KafkaTopics.CONTEXT_REWRITE_COMPLETED,
                value=event.model_dump(),
                key=correlation_id.encode("utf-8"),
            )

            logger.info(f"Published rewrite completed event (correlation_id={correlation_id})")

        except Exception as e:
            logger.error(f"Failed to publish completed event: {e}", exc_info=True)

    async def _publish_error(self, correlation_id: str, error_message: str) -> None:
        """
        Publish error event.

        Args:
            correlation_id: Request correlation ID
            error_message: Error message
        """
        if not self.producer:
            logger.warning("Producer not available - cannot publish error")
            return

        try:
            # Create error event
            event = ContextFailedEvent(
                correlation_id=correlation_id,
                payload={
                    "error_message": error_message,
                    "error_code": "CONTEXT_REWRITE_ERROR",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # Publish event
            await self.producer.send_and_wait(
                topic=KafkaTopics.CONTEXT_FAILED,
                value=event.model_dump(),
                key=correlation_id.encode("utf-8"),
            )

            logger.info(f"Published error event (correlation_id={correlation_id})")

        except Exception as e:
            logger.error(f"Failed to publish error event: {e}", exc_info=True)


# ============================================================================
# Main entry point (for testing)
# ============================================================================

async def main():
    """Main entry point for testing."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    node = NodeContextRewriterCompute()

    try:
        await node.start()
        await node.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await node.stop()


if __name__ == "__main__":
    asyncio.run(main())
