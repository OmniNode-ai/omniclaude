"""
STF Hash Compute Node

ONEX v2.0 compliant Compute node for generating SHA-256 hashes of
normalized STF code for deduplication.

Contract: contracts/debug_loop/stf_hash_compute.yaml
Node Type: COMPUTE
Base Class: NodeComputeService

Pure function - deterministic, no side effects, thread-safe.
"""

import hashlib
import re
import time
from datetime import datetime
from typing import Any, Dict, List

# omnibase_core imports
from omnibase_core.core.infrastructure_service_bases import NodeComputeService
from omnibase_core.errors.model_onex_error import ModelOnexError
from omnibase_core.errors.error_codes import EnumCoreErrorCode


class NodeSTFHashCompute(NodeComputeService):
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
                "timestamp": datetime.utcnow().isoformat(),
            }

        except ModelOnexError:
            raise
        except Exception as e:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.EXECUTION_ERROR,
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
        Normalize code according to options.

        Args:
            code: Original code
            strip_whitespace: Remove leading/trailing whitespace
            strip_comments: Remove comments
            normalize_indentation: Normalize to 4 spaces
            remove_docstrings: Remove docstrings

        Returns:
            Tuple of (normalized_code, list of applied normalizations)
        """
        normalized = code
        applied = []

        # 1. Strip leading/trailing whitespace
        if strip_whitespace:
            normalized = normalized.strip()
            applied.append("strip_whitespace")

        # 2. Remove comments
        if strip_comments:
            lines = []
            for line in normalized.split("\n"):
                # Remove inline comments (but preserve strings with #)
                # Simple heuristic: if # is not in a string, remove from # onwards
                if "#" in line:
                    # Check if # is in a string
                    in_string = False
                    quote_char = None
                    for i, char in enumerate(line):
                        if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                            if not in_string:
                                in_string = True
                                quote_char = char
                            elif char == quote_char:
                                in_string = False
                                quote_char = None
                        elif char == "#" and not in_string:
                            line = line[:i].rstrip()
                            break
                if line:  # Only keep non-empty lines
                    lines.append(line)
            normalized = "\n".join(lines)
            applied.append("strip_comments")

        # 3. Remove docstrings
        if remove_docstrings:
            # Remove triple-quoted strings (simple regex approach)
            normalized = re.sub(r'"""[\s\S]*?"""', "", normalized)
            normalized = re.sub(r"'''[\s\S]*?'''", "", normalized)
            applied.append("remove_docstrings")

        # 4. Normalize indentation to 4 spaces
        if normalize_indentation:
            lines = []
            for line in normalized.split("\n"):
                if not line.strip():
                    continue  # Skip empty lines

                # Count leading whitespace
                leading_spaces = len(line) - len(line.lstrip())

                # Convert tabs to 4 spaces
                if "\t" in line[:leading_spaces]:
                    tabs = line[:leading_spaces].count("\t")
                    leading_spaces = tabs * 4

                # Normalize to multiple of 4
                indent_level = leading_spaces // 4
                normalized_line = "    " * indent_level + line.lstrip()
                lines.append(normalized_line)

            normalized = "\n".join(lines)
            applied.append("normalize_indentation")

        return normalized, applied

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
