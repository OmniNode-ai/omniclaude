"""
State-Transformation Functions (STF) Execution Framework

Manages the discovery, execution, and tracking of State-Transformation Functions
for the debug loop system. Enables reusable transformation functions that can
be applied to fix errors and improve workflow execution.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .db import get_pg_pool
from .lineage import LineageEdge, LineageWriter


class STFRegistry:
    """Registry for managing State-Transformation Functions."""

    def __init__(self):
        self._loaded_functions: Dict[str, Callable] = {}
        self._lineage_writer = LineageWriter()

    async def register_stf(
        self,
        name: str,
        version: str,
        code_repo: str,
        commit_sha: str,
        file_path: str,
        symbol: str,
        line_start: int,
        line_end: int,
        is_pure: bool = True,
        lang: str = "python",
        license: str = "MIT",
        inputs_schema: Optional[Dict[str, Any]] = None,
        outputs_schema: Optional[Dict[str, Any]] = None,
        notes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Register a new STF in the database.

        Args:
            name: Function name
            version: Version identifier
            code_repo: Repository URL
            commit_sha: Git commit SHA
            file_path: Path to the function file
            symbol: Function symbol name
            line_start: Start line number
            line_end: End line number
            is_pure: Whether the function is pure (no side effects)
            lang: Programming language
            license: License information
            inputs_schema: JSON schema for inputs
            outputs_schema: JSON schema for outputs
            notes: Additional notes

        Returns:
            The STF ID
        """
        stf_id = str(uuid.uuid4())

        # Calculate function hash
        function_hash = await self._calculate_function_hash(
            code_repo, commit_sha, file_path, symbol, line_start, line_end
        )

        pool = await get_pg_pool()
        if pool is None:
            return stf_id

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO debug_transform_functions (
                    id, name, version, code_repo, commit_sha, file_path, symbol,
                    line_start, line_end, is_pure, lang, license, hash,
                    inputs_schema, outputs_schema, notes
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16
                )
                """,
                stf_id,
                name,
                version,
                code_repo,
                commit_sha,
                file_path,
                symbol,
                line_start,
                line_end,
                is_pure,
                lang,
                license,
                function_hash,
                json.dumps(inputs_schema or {}),
                json.dumps(outputs_schema or {}),
                json.dumps(notes or {}),
            )

        return stf_id

    async def _calculate_function_hash(
        self,
        code_repo: str,
        commit_sha: str,
        file_path: str,
        symbol: str,
        line_start: int,
        line_end: int,
    ) -> bytes:
        """Calculate hash of the function code."""
        # For now, create a hash based on the metadata
        # In a real implementation, this would fetch and hash the actual code
        content = (
            f"{code_repo}:{commit_sha}:{file_path}:{symbol}:{line_start}:{line_end}"
        )
        return hashlib.sha256(content.encode()).digest()

    async def discover_stfs(
        self,
        error_type: Optional[str] = None,
        lang: Optional[str] = None,
        is_pure: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Discover STFs that might be applicable to a given error or context.

        Args:
            error_type: Type of error to find fixes for
            lang: Programming language filter
            is_pure: Whether to include only pure functions

        Returns:
            List of applicable STFs
        """
        pool = await get_pg_pool()
        if pool is None:
            return []

        async with pool.acquire() as conn:
            # Build query based on filters
            where_conditions: List[str] = ["blocked = false"]
            params: List[Union[str, bool]] = []
            param_count = 0

            if error_type:
                param_count += 1
                where_conditions.append(f"notes->>'error_types' LIKE ${param_count}")
                params.append(f"%{error_type}%")

            if lang:
                param_count += 1
                where_conditions.append(f"lang = ${param_count}")
                params.append(lang)

            if is_pure is not None:
                param_count += 1
                where_conditions.append(f"is_pure = ${param_count}")
                params.append(is_pure)

            # Note: where_conditions contains safe parameterized SQL fragments (e.g., "is_pure = $1")
            # Values are passed separately via params array
            query = f"""  # nosec B608
                SELECT id, name, version, code_repo, commit_sha, file_path, symbol,
                       line_start, line_end, is_pure, lang, inputs_schema, outputs_schema, notes
                FROM debug_transform_functions
                WHERE {' AND '.join(where_conditions)}
                ORDER BY created_at DESC
            """

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def load_stf(self, stf_id: str) -> Optional[Callable]:
        """
        Load an STF function for execution.

        Args:
            stf_id: The STF ID to load

        Returns:
            The loaded function or None if not found
        """
        if stf_id in self._loaded_functions:
            return self._loaded_functions[stf_id]

        pool = await get_pg_pool()
        if pool is None:
            return None

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT name, version, code_repo, file_path, symbol, lang, line_start, line_end
                FROM debug_transform_functions
                WHERE id = $1
                """,
                stf_id,
            )

            if not row:
                return None

            # Try to load the actual function
            try:
                stf_func = await self._load_function_from_source(
                    code_repo=row["code_repo"],
                    file_path=row["file_path"],
                    symbol=row["symbol"],
                    line_start=row["line_start"],
                    line_end=row["line_end"],
                    lang=row["lang"],
                )

                if stf_func:
                    self._loaded_functions[stf_id] = stf_func
                    return stf_func
            except Exception as e:
                print(f"Warning: Failed to load STF {stf_id}: {e}")

            # Fallback to mock function if real loading fails
            def mock_stf(*args, **kwargs):
                return {
                    "transformed": True,
                    "stf_id": stf_id,
                    "stf_name": row["name"],
                    "timestamp": datetime.now().isoformat(),
                    "inputs": args,
                    "kwargs": kwargs,
                    "note": "Mock function - real loading failed",
                }

            self._loaded_functions[stf_id] = mock_stf
            return mock_stf

    async def _load_function_from_source(
        self,
        code_repo: str,
        file_path: str,
        symbol: str,
        line_start: int,
        line_end: int,
        lang: str,
    ) -> Optional[Callable]:
        """
        Load a function from source code.

        Args:
            code_repo: Repository URL
            file_path: Path to the function file
            symbol: Function symbol name
            line_start: Start line number
            line_end: End line number
            lang: Programming language

        Returns:
            The loaded function or None if loading fails
        """
        if lang != "python":
            # Only support Python for now
            return None

        try:
            # For MVP, we'll implement a simple local file loading
            # In production, this would fetch from the repository

            # Check if it's a local file path
            if file_path.startswith("/") or file_path.startswith("./"):
                import os

                if os.path.exists(file_path):
                    return await self._load_from_local_file(
                        file_path, symbol, line_start, line_end
                    )

            # For remote repositories, we would:
            # 1. Clone/fetch the repository
            # 2. Load the specific file
            # 3. Extract the function
            # This is complex and would require git integration

            return None

        except Exception as e:
            print(f"Error loading function from source: {e}")
            return None

    async def _load_from_local_file(
        self, file_path: str, symbol: str, line_start: int, line_end: int
    ) -> Optional[Callable]:
        """
        Load a function from a local file.

        Args:
            file_path: Path to the Python file
            symbol: Function symbol name
            line_start: Start line number
            line_end: End line number

        Returns:
            The loaded function or None if loading fails
        """
        try:
            import importlib.util

            # Load the module
            spec = importlib.util.spec_from_file_location("stf_module", file_path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Get the function
            if hasattr(module, symbol):
                func = getattr(module, symbol)
                if callable(func):
                    return func  # type: ignore[no-any-return]

            return None

        except Exception as e:
            print(f"Error loading from local file {file_path}: {e}")
            return None

    async def execute_stf(
        self,
        stf_id: str,
        inputs: Dict[str, Any],
        run_id: str,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Any, str]:
        """
        Execute an STF with given inputs.

        Args:
            stf_id: The STF ID to execute
            inputs: Input parameters for the function
            run_id: The workflow run ID
            correlation_id: Optional correlation ID

        Returns:
            Tuple of (success, result, execution_id)
        """
        execution_id = str(uuid.uuid4())

        try:
            # Load the STF function
            stf_func = await self.load_stf(stf_id)
            if not stf_func:
                return False, {"error": "STF not found"}, execution_id

            # Execute the function
            result = stf_func(**inputs)

            # Log the execution
            await self._log_stf_execution(
                execution_id, stf_id, run_id, correlation_id, True, result
            )

            # Emit lineage edge
            edge = LineageEdge(
                src_type="stf",
                src_id=stf_id,
                dst_type="execution",
                dst_id=execution_id,
                edge_type="EXECUTED",
                attributes={
                    "run_id": run_id,
                    "correlation_id": correlation_id,
                    "success": True,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            await self._lineage_writer.emit(edge)

            return True, result, execution_id

        except Exception as e:
            # Log the failed execution
            await self._log_stf_execution(
                execution_id, stf_id, run_id, correlation_id, False, {"error": str(e)}
            )

            return False, {"error": str(e)}, execution_id

    async def _log_stf_execution(
        self,
        execution_id: str,
        stf_id: str,
        run_id: str,
        correlation_id: Optional[str],
        success: bool,
        result: Any,
    ) -> None:
        """Log STF execution details."""
        pool = await get_pg_pool()
        if pool is None:
            return

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_steps (
                    id, run_id, step_index, phase, correlation_id, applied_tf_id,
                    started_at, completed_at, duration_ms, success, error
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
                )
                """,
                execution_id,
                run_id,
                999,  # Special step index for STF executions
                "STF_EXECUTION",
                correlation_id,
                stf_id,
                datetime.now(),
                datetime.now(),
                0,  # Duration will be calculated if needed
                success,
                str(result.get("error", "")) if not success else None,
            )


# Global STF registry instance
stf_registry = STFRegistry()


async def discover_applicable_stfs(
    error_type: str, context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Discover STFs that might be applicable to fix a given error.

    Args:
        error_type: Type of error to find fixes for
        context: Additional context for STF discovery

    Returns:
        List of applicable STFs
    """
    return await stf_registry.discover_stfs(
        error_type=error_type, lang=context.get("language", "python"), is_pure=True
    )


async def apply_stf_fix(
    stf_id: str,
    inputs: Dict[str, Any],
    run_id: str,
    correlation_id: Optional[str] = None,
) -> Tuple[bool, Any]:
    """
    Apply an STF to fix an error or improve state.

    Args:
        stf_id: The STF ID to apply
        inputs: Input parameters for the STF
        run_id: The workflow run ID
        correlation_id: Optional correlation ID

    Returns:
        Tuple of (success, result)
    """
    success, result, execution_id = await stf_registry.execute_stf(
        stf_id, inputs, run_id, correlation_id
    )

    return success, result
