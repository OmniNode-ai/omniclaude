"""
STF Hash Compute Node

ONEX v2.0 compliant Compute node for generating SHA-256 hashes of
normalized STF code for deduplication.

Contract: contracts/debug_loop/stf_hash_compute.yaml
Node Type: COMPUTE
Base Class: NodeCompute

Pure function - deterministic, no side effects, thread-safe.
"""

import ast
import hashlib
import time
from datetime import UTC, datetime
from typing import Any, Dict, List

from omnibase_core.errors.error_codes import EnumCoreErrorCode
from omnibase_core.errors.model_onex_error import ModelOnexError

# omnibase_core imports
from omnibase_core.nodes import NodeCompute


class NodeSTFHashCompute(NodeCompute):
    """
    Compute node for STF hash generation with code normalization.

    Pure ONEX Compute pattern - deterministic, no side effects, thread-safe.
    """

    async def execute_compute(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate SHA-256 hash of normalized STF code.

        Args:
            contract: Input contract with stf_code and normalization_options

        Returns:
            Output contract with stf_hash, normalized_code, metadata

        Raises:
            ModelOnexError: On validation or execution errors
        """
        start_time = time.time()

        try:
            # Extract input
            stf_code = contract.get("stf_code")
            if not stf_code:
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="Missing required field: stf_code",
                )

            if not isinstance(stf_code, str):
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="stf_code must be a string",
                )

            # Get normalization options
            options = contract.get("normalization_options", {})
            strip_whitespace = options.get("strip_whitespace", True)
            strip_comments = options.get("strip_comments", True)
            normalize_indentation = options.get("normalize_indentation", True)
            remove_docstrings = options.get("remove_docstrings", False)

            # Apply normalization
            normalized_code, applied_normalizations = self._normalize_code(
                stf_code,
                strip_whitespace=strip_whitespace,
                strip_comments=strip_comments,
                normalize_indentation=normalize_indentation,
                remove_docstrings=remove_docstrings,
            )

            # Generate SHA-256 hash
            stf_hash = self._generate_hash(normalized_code)

            # Calculate computation time
            computation_time_ms = (time.time() - start_time) * 1000

            return {
                "stf_hash": stf_hash,
                "normalized_code": normalized_code,
                "normalization_applied": applied_normalizations,
                "computation_time_ms": computation_time_ms,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        except ModelOnexError:
            raise
        except Exception as e:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Hash computation failed: {str(e)}",
            ) from e

    def _normalize_code(
        self,
        code: str,
        strip_whitespace: bool = True,
        strip_comments: bool = True,
        normalize_indentation: bool = True,
        remove_docstrings: bool = False,
    ) -> tuple[str, List[str]]:
        """
        Normalize code according to options using AST.

        Uses AST (Abstract Syntax Tree) for robust code normalization that:
        - Automatically handles comments (AST ignores them)
        - Correctly identifies and removes docstrings (not all triple-quoted strings)
        - Preserves code structure and semantics
        - Handles edge cases that regex cannot

        Args:
            code: Original code
            strip_whitespace: Remove leading/trailing whitespace
            strip_comments: Remove comments (via AST parsing)
            normalize_indentation: Normalize to 4 spaces
            remove_docstrings: Remove docstrings (first string in function/class/module)

        Returns:
            Tuple of (normalized_code, list of applied normalizations)
        """
        normalized = code
        applied = []

        # 1. Strip leading/trailing whitespace
        if strip_whitespace:
            normalized = normalized.strip()
            applied.append("strip_whitespace")

        # 2. & 3. Use AST for comment and docstring removal
        if strip_comments or remove_docstrings:
            try:
                # Parse to AST (automatically strips comments)
                tree = ast.parse(normalized)

                # Remove docstrings if requested
                if remove_docstrings:
                    self._remove_docstrings_from_ast(tree)
                    applied.append("remove_docstrings")

                # Generate normalized code from AST
                # Note: ast.unparse is available in Python 3.9+
                if hasattr(ast, "unparse"):
                    normalized = ast.unparse(tree)
                else:
                    # Fallback for Python 3.8 and earlier
                    # Keep original code if unparse is not available
                    pass

                if strip_comments:
                    applied.append("strip_comments")

            except SyntaxError:
                # Fallback for invalid syntax - keep original code
                # This ensures we don't break on malformed code
                pass

        # 4. Normalize indentation to 4 spaces
        if normalize_indentation:
            lines = []
            for line in normalized.split("\n"):
                if not line.strip():
                    continue  # Skip empty lines

                # Count leading whitespace
                stripped = line.lstrip()
                leading_whitespace = line[: len(line) - len(stripped)]

                # Convert tabs to spaces (1 tab = 4 spaces)
                leading_whitespace = leading_whitespace.replace("\t", "    ")

                # Count spaces
                leading_spaces = len(leading_whitespace)

                # Normalize to multiple of 4
                indent_level = leading_spaces // 4
                normalized_line = "    " * indent_level + stripped
                lines.append(normalized_line)

            normalized = "\n".join(lines)
            applied.append("normalize_indentation")

        return normalized, applied

    def _remove_docstrings_from_ast(self, tree: ast.AST) -> None:
        """
        Remove docstrings from AST in-place.

        Docstrings are identified as:
        - First statement in a Module that is an Expr containing a Constant/Str
        - First statement in a FunctionDef that is an Expr containing a Constant/Str
        - First statement in a ClassDef that is an Expr containing a Constant/Str

        Args:
            tree: AST tree to modify in-place
        """
        for node in ast.walk(tree):
            # Check Module, FunctionDef, ClassDef, AsyncFunctionDef
            if isinstance(
                node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)
            ):
                if node.body and isinstance(node.body[0], ast.Expr):
                    # Check if it's a string constant (docstring)
                    value = node.body[0].value
                    # Handle both ast.Constant (Python 3.8+) and ast.Str (Python 3.7)
                    is_string = False
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        is_string = True
                    elif hasattr(ast, "Str") and isinstance(value, ast.Str):
                        is_string = True

                    if is_string:
                        # Remove docstring
                        node.body.pop(0)

    def _generate_hash(self, code: str) -> str:
        """
        Generate SHA-256 hash of code.

        Args:
            code: Code to hash

        Returns:
            64-character hexadecimal hash
        """
        # Convert to UTF-8 bytes
        code_bytes = code.encode("utf-8")

        # Generate SHA-256 hash
        hash_obj = hashlib.sha256(code_bytes)
        stf_hash = hash_obj.hexdigest()

        return stf_hash
