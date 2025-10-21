#!/usr/bin/env python3
"""
Batch Event Processor

Accumulates events into batches and processes them together for improved throughput.
Reduces per-event overhead and enables efficient bulk operations.

Performance target: p95 latency ≤200ms (from ~500ms baseline)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from .persistence import CodegenPersistence

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    """Batch processing configuration"""

    max_batch_size: int = 10
    max_wait_ms: int = 100
    enable_metrics: bool = True


class BatchProcessor:
    """
    Batch event processor for improved throughput.

    Features:
    - Accumulate events into batches
    - Process batches with configurable size/timeout
    - Track batch processing metrics
    - Automatic flush on timeout
    """

    def __init__(
        self,
        processor_func: Callable[[List[Any]], Any],
        config: Optional[BatchConfig] = None,
        persistence: Optional[CodegenPersistence] = None,
    ):
        """
        Initialize batch processor.

        Args:
            processor_func: Async function to process a batch of events
            config: Optional batch configuration
            persistence: Optional persistence layer for metrics
        """
        self.processor_func = processor_func
        self.config = config or BatchConfig()

        self.batch: List[Any] = []
        self.batch_lock = asyncio.Lock()
        self.flush_task: Optional[asyncio.Task] = None

        # Only create persistence if explicitly enabled and not provided
        if persistence is not None:
            self.persistence = persistence
        elif self.config.enable_metrics:
            self.persistence = CodegenPersistence()
        else:
            self.persistence = None

        self.logger = logging.getLogger(__name__)

    async def add_event(self, event: Any) -> Optional[Any]:
        """
        Add event to batch.

        If batch is full, process immediately.
        Otherwise, schedule flush after max_wait_ms.

        Args:
            event: Event to process

        Returns:
            Processing result if batch was flushed, None otherwise
        """
        async with self.batch_lock:
            self.batch.append(event)

            # Check if batch is full
            if len(self.batch) >= self.config.max_batch_size:
                return await self._flush_batch()

            # Schedule flush if not already scheduled
            if not self.flush_task or self.flush_task.done():
                self.flush_task = asyncio.create_task(self._flush_after_delay())

            return None

    async def _flush_after_delay(self):
        """Flush batch after max_wait_ms"""
        try:
            await asyncio.sleep(self.config.max_wait_ms / 1000.0)

            async with self.batch_lock:
                if self.batch:
                    await self._flush_batch()
        except asyncio.CancelledError:
            # Task was cancelled during sleep, which is normal during cleanup
            pass

    async def _flush_batch(self) -> Any:
        """Process current batch"""
        if not self.batch:
            return None

        start_time = time.time()
        batch_size = len(self.batch)

        try:
            # Process batch
            result = await self.processor_func(self.batch)

            duration_ms = (time.time() - start_time) * 1000

            # Track metrics
            if self.persistence:
                await self.persistence.insert_event_processing_metric(
                    event_type="batch_processed",
                    event_source="batch_processor",
                    processing_duration_ms=int(duration_ms),
                    success=True,
                    batch_size=batch_size,
                )

            self.logger.debug(
                f"Batch processed: {batch_size} events in {duration_ms:.0f}ms"
            )

            # Clear batch
            self.batch.clear()

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # Track error
            if self.persistence:
                await self.persistence.insert_event_processing_metric(
                    event_type="batch_processed",
                    event_source="batch_processor",
                    processing_duration_ms=int(duration_ms),
                    success=False,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    batch_size=batch_size,
                )

            self.logger.error(f"Batch processing failed: {e}")

            # Clear batch to prevent retry loops
            self.batch.clear()

            raise

    async def flush(self) -> Any:
        """Force flush current batch"""
        async with self.batch_lock:
            return await self._flush_batch()

    async def cleanup(self):
        """Cleanup resources and flush remaining events"""
        # Cancel pending flush task
        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass

        # Flush remaining events
        await self.flush()

        if self.persistence:
            await self.persistence.close()
