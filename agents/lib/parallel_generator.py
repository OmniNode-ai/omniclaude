#!/usr/bin/env python3
"""
Parallel Code Generation Orchestrator

Coordinates multiple node generations using a worker pool for 3x+ throughput improvement.
Handles resource management, error recovery, and progress tracking.
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast
from uuid import UUID

from omnibase_core.errors import EnumCoreErrorCode, OnexError

from .omninode_template_engine import OmniNodeTemplateEngine
from .persistence import CodegenPersistence
from .simple_prd_analyzer import PRDAnalysisResult


logger = logging.getLogger(__name__)


@dataclass
class GenerationJob:
    """Single node generation job"""

    job_id: UUID
    node_type: str
    microservice_name: str
    domain: str
    analysis_result: PRDAnalysisResult
    output_directory: str


@dataclass
class GenerationResult:
    """Result of parallel generation"""

    job_id: UUID
    success: bool
    node_result: Optional[Dict[str, Any]]
    error: Optional[str]
    duration_ms: float
    node_type: str
    microservice_name: str


class ParallelGenerator:
    """
    Parallel code generation orchestrator.

    Coordinates multiple node generations using a worker pool.
    Handles resource management, error recovery, and progress tracking.

    Features:
    - Thread-based parallelism for I/O-bound operations
    - Thread-safe template engine access
    - Concurrent file writes with proper locking
    - Resource cleanup on errors/timeouts
    - Performance metrics tracking
    - Graceful degradation on failures
    """

    def __init__(
        self,
        max_workers: int = 3,
        timeout_seconds: int = 120,
        enable_metrics: bool = True,
    ):
        """
        Initialize parallel generator.

        Args:
            max_workers: Maximum number of concurrent workers (default: 3)
            timeout_seconds: Timeout for each generation job (default: 120)
            enable_metrics: Enable performance metrics tracking (default: True)
        """
        self.max_workers = max_workers
        self.timeout_seconds = timeout_seconds
        self.enable_metrics = enable_metrics

        # Worker pool (thread-based for I/O bound operations)
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="codegen_worker"
        )

        # Template engine (shared, thread-safe)
        # Disable caching for parallel mode to avoid event loop issues in worker threads
        self._template_engine_lock = threading.Lock()
        self._template_engine: Optional[OmniNodeTemplateEngine] = None
        self._cache_enabled = False  # Disable cache for thread-safe operation

        # Persistence for metrics
        self.persistence = CodegenPersistence() if enable_metrics else None

        # Progress tracking
        self._progress_lock = threading.Lock()
        self._completed_jobs = 0
        self._total_jobs = 0

        self.logger = logging.getLogger(__name__)

    @property
    def template_engine(self) -> OmniNodeTemplateEngine:
        """Get thread-safe template engine instance"""
        if self._template_engine is None:
            with self._template_engine_lock:
                if self._template_engine is None:
                    # Disable cache to avoid asyncio event loop issues in worker threads
                    self._template_engine = OmniNodeTemplateEngine(enable_cache=False)
        # At this point _template_engine is guaranteed to be initialized
        assert self._template_engine is not None
        return self._template_engine

    async def generate_nodes_parallel(
        self, jobs: List[GenerationJob], session_id: UUID
    ) -> List[GenerationResult]:
        """
        Generate multiple nodes in parallel.

        Args:
            jobs: List of generation jobs
            session_id: Session ID for tracking

        Returns:
            List of generation results (order not guaranteed)

        Raises:
            OnexError: If all jobs fail
        """
        if not jobs:
            return []

        start_time = time.time()
        self._total_jobs = len(jobs)
        self._completed_jobs = 0

        self.logger.info(
            f"Starting parallel generation: {len(jobs)} jobs, "
            f"{self.max_workers} workers, session={session_id}"
        )

        # Submit all jobs to worker pool
        future_to_job = {
            self.executor.submit(self._generate_node_sync, job): job for job in jobs
        }

        # Collect results as they complete
        results = []
        successful_results = 0
        failed_results = 0

        for future in as_completed(future_to_job):
            job = future_to_job[future]

            try:
                result = future.result(timeout=self.timeout_seconds)
                results.append(result)

                if result.success:
                    successful_results += 1
                    self.logger.info(
                        f"Job {job.job_id} ({job.node_type}) completed successfully "
                        f"in {result.duration_ms:.0f}ms"
                    )
                else:
                    failed_results += 1
                    self.logger.error(
                        f"Job {job.job_id} ({job.node_type}) failed: {result.error}"
                    )

            except TimeoutError:
                failed_results += 1
                self.logger.error(
                    f"Job {job.job_id} ({job.node_type}) timed out after {self.timeout_seconds}s"
                )
                results.append(
                    GenerationResult(
                        job_id=job.job_id,
                        success=False,
                        node_result=None,
                        error=f"Generation timed out after {self.timeout_seconds}s",
                        duration_ms=self.timeout_seconds * 1000,
                        node_type=job.node_type,
                        microservice_name=job.microservice_name,
                    )
                )

            except Exception as e:
                failed_results += 1
                self.logger.error(
                    f"Job {job.job_id} ({job.node_type}) error: {str(e)}", exc_info=True
                )
                results.append(
                    GenerationResult(
                        job_id=job.job_id,
                        success=False,
                        node_result=None,
                        error=str(e),
                        duration_ms=0,
                        node_type=job.node_type,
                        microservice_name=job.microservice_name,
                    )
                )

            # Update progress
            with self._progress_lock:
                self._completed_jobs += 1
                progress_pct = (self._completed_jobs / self._total_jobs) * 100
                self.logger.info(
                    f"Progress: {self._completed_jobs}/{self._total_jobs} "
                    f"({progress_pct:.1f}%)"
                )

        # Track performance metrics
        total_duration_ms = (time.time() - start_time) * 1000

        if self.enable_metrics and self.persistence:
            await self._track_parallel_metrics(
                session_id=session_id,
                total_jobs=len(jobs),
                successful_jobs=successful_results,
                failed_jobs=failed_results,
                total_duration_ms=total_duration_ms,
                worker_count=self.max_workers,
            )

        # Calculate throughput metrics
        avg_time_per_job = total_duration_ms / len(jobs) if jobs else 0
        estimated_sequential_time = sum(r.duration_ms for r in results if r.success)
        speedup = (
            estimated_sequential_time / total_duration_ms
            if total_duration_ms > 0
            else 1.0
        )

        self.logger.info(
            f"Parallel generation complete: "
            f"{successful_results}/{len(jobs)} succeeded, "
            f"{failed_results} failed, "
            f"{total_duration_ms:.0f}ms total, "
            f"{avg_time_per_job:.0f}ms avg/job, "
            f"{speedup:.2f}x speedup"
        )

        # If all jobs failed, raise error
        if successful_results == 0 and len(jobs) > 0:
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message="All parallel generation jobs failed",
                details={
                    "total_jobs": len(jobs),
                    "failed_jobs": failed_results,
                    "errors": [r.error for r in results if r.error],
                },
            )

        return results

    def _generate_node_sync(self, job: GenerationJob) -> GenerationResult:
        """
        Generate single node (synchronous wrapper for thread pool).

        This runs in a worker thread, so we need to create a new event loop.
        The template engine is thread-safe and shared across workers.

        Args:
            job: Generation job to execute

        Returns:
            GenerationResult with success/failure information
        """
        start_time = time.time()

        try:
            # Create event loop for async operations in worker thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                # Generate node using shared template engine
                # Cast analysis_result to match template engine's expected type
                node_result = loop.run_until_complete(
                    self.template_engine.generate_node(
                        analysis_result=cast(Any, job.analysis_result),
                        node_type=job.node_type,
                        microservice_name=job.microservice_name,
                        domain=job.domain,
                        output_directory=job.output_directory,
                    )
                )

                duration_ms = (time.time() - start_time) * 1000

                return GenerationResult(
                    job_id=job.job_id,
                    success=True,
                    node_result=node_result,
                    error=None,
                    duration_ms=duration_ms,
                    node_type=job.node_type,
                    microservice_name=job.microservice_name,
                )

            finally:
                loop.close()

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            self.logger.error(
                f"Node generation failed for {job.node_type}/{job.microservice_name}: {str(e)}",
                exc_info=True,
            )

            return GenerationResult(
                job_id=job.job_id,
                success=False,
                node_result=None,
                error=str(e),
                duration_ms=duration_ms,
                node_type=job.node_type,
                microservice_name=job.microservice_name,
            )

    async def _track_parallel_metrics(
        self,
        session_id: UUID,
        total_jobs: int,
        successful_jobs: int,
        failed_jobs: int,
        total_duration_ms: float,
        worker_count: int,
    ):
        """Track parallel generation metrics to database"""
        if not self.persistence:
            return

        try:
            await self.persistence.insert_performance_metric(
                session_id=session_id,
                node_type="PARALLEL_BATCH",  # Special node type for parallel operations
                phase="parallel_generation",
                duration_ms=int(total_duration_ms),
                parallel_execution=True,
                worker_count=worker_count,
                metadata={
                    "total_jobs": total_jobs,
                    "successful_jobs": successful_jobs,
                    "failed_jobs": failed_jobs,
                    "success_rate": (
                        successful_jobs / total_jobs if total_jobs > 0 else 0.0
                    ),
                    "avg_duration_ms": (
                        total_duration_ms / total_jobs if total_jobs > 0 else 0
                    ),
                },
            )
            self.logger.debug(
                f"Tracked parallel metrics: {successful_jobs}/{total_jobs} succeeded "
                f"in {total_duration_ms:.0f}ms"
            )
        except Exception as e:
            self.logger.warning(f"Failed to track parallel metrics: {e}")

    def get_progress(self) -> Dict[str, Any]:
        """
        Get current progress information.

        Returns:
            Dictionary with progress details
        """
        with self._progress_lock:
            return {
                "completed_jobs": self._completed_jobs,
                "total_jobs": self._total_jobs,
                "progress_percent": (
                    (self._completed_jobs / self._total_jobs * 100)
                    if self._total_jobs > 0
                    else 0
                ),
                "remaining_jobs": self._total_jobs - self._completed_jobs,
            }

    async def cleanup(self):
        """
        Cleanup resources and shutdown worker pool.

        Should be called when done with parallel generation.
        """
        self.logger.info("Shutting down parallel generator...")

        # Shutdown executor
        self.executor.shutdown(wait=True)

        # Close persistence
        if self.persistence:
            await self.persistence.close()

        self.logger.info("Parallel generator shutdown complete")

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        # Note: Need to run cleanup in async context
        # Users should call await cleanup() explicitly
        pass
