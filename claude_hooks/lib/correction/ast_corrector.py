"""
AST-Based Code Corrector using libcst

Provides surgical, line/column-specific code corrections while preserving:
- All formatting (indentation, spacing, line breaks)
- All comments (inline, block, docstrings)
- Framework method contracts (AST visitors, Django, FastAPI, etc.)

This replaces the broken regex-based correction approach that caused false positives.

Performance Target: <100ms for typical files (95th percentile)

Author: Claude Code + Archon AI Quality Enforcer
Date: 2025-09-30
"""

import ast
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .framework_detector import FrameworkMethodDetector, FrameworkPattern

logger = logging.getLogger(__name__)

# Try to import libcst
try:
    import libcst as cst
    from libcst import metadata

    LIBCST_AVAILABLE = True
except ImportError:
    LIBCST_AVAILABLE = False
    logger.warning(
        "libcst not available - falling back to regex-based corrections. "
        "Install libcst for AST-aware corrections: pip install libcst"
    )


@dataclass
class CorrectionResult:
    """Result of applying corrections."""

    success: bool
    corrected_content: Optional[str]
    corrections_applied: int
    corrections_skipped: int
    framework_methods_preserved: int
    error_message: Optional[str] = None
    performance_ms: Optional[float] = None


class ContextAwareRenameTransformer(cst.CSTTransformer if LIBCST_AVAILABLE else object):
    """
    libcst transformer for surgical, position-aware identifier renaming.

    Only renames at specific line/column violations, preserving:
    - Framework methods (AST visitors, Django, FastAPI, pytest)
    - All formatting and comments
    - String literal contents
    - Docstrings
    """

    if LIBCST_AVAILABLE:
        METADATA_DEPENDENCIES = (metadata.PositionProvider,)

    def __init__(
        self,
        corrections: Dict[Tuple[int, int, str], str],
        framework_detector: FrameworkMethodDetector,
        original_tree: ast.Module,
    ):
        """
        Initialize transformer.

        Args:
            corrections: {(line, col, old_name): new_name}
            framework_detector: Framework method detector instance
            original_tree: Original AST tree for framework detection
        """
        super().__init__()
        self.corrections = corrections
        self.framework_detector = framework_detector
        self.original_tree = original_tree
        self.corrections_applied = 0
        self.corrections_skipped = 0
        self.framework_methods_preserved = 0
        self.current_function = None
        self.current_class = None

    def visit_ClassDef(self, node) -> bool:
        """Track current class for framework context."""
        self.current_class = node
        return True

    def leave_ClassDef(self, original_node, updated_node):
        """Handle class name renaming and exit class context."""
        if not LIBCST_AVAILABLE:
            return updated_node

        try:
            # Check if class name needs renaming
            pos = self.get_metadata(metadata.PositionProvider, original_node)
            old_name = original_node.name.value

            # Check if this name should be corrected
            new_name = self._check_correction(pos.start.line, pos.start.column, old_name)
            if new_name:
                logger.debug(f"Renaming class '{old_name}' → '{new_name}'")
                self.corrections_applied += 1
                updated_node = updated_node.with_changes(
                    name=cst.Name(value=new_name)
                )
        except Exception as e:
            logger.error(f"Error during class renaming: {e}")

        self.current_class = None
        return updated_node

    def visit_FunctionDef(self, node) -> bool:
        """Track current function for framework context."""
        self.current_function = node
        return True

    def leave_FunctionDef(self, original_node, updated_node):
        """Handle function name renaming and exit function context."""
        if not LIBCST_AVAILABLE:
            return updated_node

        try:
            # Check if function name needs renaming
            pos = self.get_metadata(metadata.PositionProvider, original_node)
            old_name = original_node.name.value

            # Check if this is a framework method
            # Find corresponding function in original AST
            for ast_node in ast.walk(self.original_tree):
                if isinstance(ast_node, ast.FunctionDef) and ast_node.name == old_name:
                    pattern = self.framework_detector.is_framework_method(
                        ast_node, self.original_tree
                    )
                    if pattern:
                        logger.debug(
                            f"Preserving framework method: {pattern.framework}.{pattern.method_name} "
                            f"({pattern.reason})"
                        )
                        self.corrections_skipped += 1
                        self.framework_methods_preserved += 1
                        self.current_function = None
                        return updated_node
                    break

            # Check if this function should be renamed
            new_name = self._check_correction(pos.start.line, pos.start.column, old_name)
            if new_name:
                logger.debug(f"Renaming function '{old_name}' → '{new_name}'")
                self.corrections_applied += 1
                updated_node = updated_node.with_changes(
                    name=cst.Name(value=new_name)
                )
        except Exception as e:
            logger.error(f"Error during function renaming: {e}")

        self.current_function = None
        return updated_node

    def leave_Name(self, original_node, updated_node):
        """Rename variable/identifier names at specific line/column positions."""
        if not LIBCST_AVAILABLE:
            return updated_node

        try:
            # Get position metadata
            pos = self.get_metadata(metadata.PositionProvider, original_node)
            old_name = original_node.value

            # Check if this name should be corrected
            new_name = self._check_correction(pos.start.line, pos.start.column, old_name)
            if new_name:
                logger.debug(f"Renaming identifier '{old_name}' → '{new_name}'")
                self.corrections_applied += 1
                return updated_node.with_changes(value=new_name)

        except Exception as e:
            logger.error(f"Error during name transformation: {e}")
            self.corrections_skipped += 1

        return updated_node

    def _check_correction(self, line: int, column: int, old_name: str) -> Optional[str]:
        """
        Check if a correction should be applied at the given position.

        Returns new_name if correction found, None otherwise.
        """
        # Try exact match first
        key = (line, column, old_name)
        if key in self.corrections:
            return self.corrections[key]

        # Try fuzzy matching (off-by-one column due to different parsers)
        for col_offset in range(-2, 3):
            key = (line, column + col_offset, old_name)
            if key in self.corrections:
                return self.corrections[key]

        return None

    def _is_in_framework_context(self, node, pos) -> bool:
        """
        Check if the current node is in a framework method context.

        This prevents renaming framework methods like visit_FunctionDef,
        save(), get(), etc. that are part of framework contracts.
        """
        # If we're in a function, check if it's a framework method
        if self.current_function:
            # Convert libcst FunctionDef to ast FunctionDef for framework detection
            func_name = self.current_function.name.value

            # Find corresponding function in original AST
            for ast_node in ast.walk(self.original_tree):
                if isinstance(ast_node, ast.FunctionDef):
                    if ast_node.name == func_name:
                        # Check if this is a framework method
                        pattern = self.framework_detector.is_framework_method(
                            ast_node, self.original_tree
                        )
                        if pattern:
                            logger.debug(
                                f"Framework method detected: {pattern.framework}.{pattern.method_name} "
                                f"({pattern.reason})"
                            )
                            return True

        return False


def apply_corrections_with_ast(
    content: str,
    corrections: List[Dict],
    framework_detector: Optional[FrameworkMethodDetector] = None,
) -> CorrectionResult:
    """
    Apply corrections using AST-based approach with libcst.

    Args:
        content: Original source code
        corrections: List of correction dicts with keys:
            - old_name: str
            - new_name: str
            - line: int (1-based)
            - column: int (0-based)
        framework_detector: Optional framework detector (created if not provided)

    Returns:
        CorrectionResult with corrected code or error information
    """
    import time

    start_time = time.time()

    # Fallback to regex if libcst not available
    if not LIBCST_AVAILABLE:
        return _fallback_regex_correction(content, corrections)

    try:
        # Create framework detector if not provided
        if framework_detector is None:
            framework_detector = FrameworkMethodDetector()

        # Parse original content with stdlib AST for framework detection
        try:
            original_ast = ast.parse(content)
        except SyntaxError as e:
            logger.warning(f"Syntax error in original content: {e}")
            return CorrectionResult(
                success=False,
                corrected_content=None,
                corrections_applied=0,
                corrections_skipped=0,
                framework_methods_preserved=0,
                error_message=f"Syntax error: {e}",
                performance_ms=(time.time() - start_time) * 1000,
            )

        # Parse with libcst
        try:
            module = cst.parse_module(content)
        except Exception as e:
            logger.error(f"libcst parse error: {e}")
            return CorrectionResult(
                success=False,
                corrected_content=None,
                corrections_applied=0,
                corrections_skipped=0,
                framework_methods_preserved=0,
                error_message=f"Parse error: {e}",
                performance_ms=(time.time() - start_time) * 1000,
            )

        # Build correction index: {(line, col, old_name): new_name}
        correction_index = {}
        for correction in corrections:
            key = (
                correction.get("line"),
                correction.get("column", 0),
                correction.get("old_name"),
            )
            correction_index[key] = correction.get("new_name")

        logger.debug(f"Applying {len(correction_index)} corrections")

        # Create transformer with metadata wrapper
        wrapper = metadata.MetadataWrapper(module)
        transformer = ContextAwareRenameTransformer(
            correction_index, framework_detector, original_ast
        )

        # Apply transformations
        try:
            modified_tree = wrapper.visit(transformer)
        except Exception as e:
            logger.error(f"Transformation error: {e}")
            return CorrectionResult(
                success=False,
                corrected_content=None,
                corrections_applied=0,
                corrections_skipped=0,
                framework_methods_preserved=0,
                error_message=f"Transformation error: {e}",
                performance_ms=(time.time() - start_time) * 1000,
            )

        # Generate corrected code
        corrected_content = modified_tree.code

        # Validate: ensure no syntax errors
        try:
            ast.parse(corrected_content)
        except SyntaxError as e:
            logger.error(f"Generated code has syntax errors: {e}")
            return CorrectionResult(
                success=False,
                corrected_content=None,
                corrections_applied=0,
                corrections_skipped=0,
                framework_methods_preserved=0,
                error_message=f"Generated code has syntax errors: {e}",
                performance_ms=(time.time() - start_time) * 1000,
            )

        performance_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Corrections applied: {transformer.corrections_applied}, "
            f"skipped: {transformer.corrections_skipped}, "
            f"framework methods preserved: {transformer.framework_methods_preserved}, "
            f"performance: {performance_ms:.2f}ms"
        )

        return CorrectionResult(
            success=True,
            corrected_content=corrected_content,
            corrections_applied=transformer.corrections_applied,
            corrections_skipped=transformer.corrections_skipped,
            framework_methods_preserved=transformer.framework_methods_preserved,
            error_message=None,
            performance_ms=performance_ms,
        )

    except Exception as e:
        logger.error(f"Unexpected error during AST correction: {e}")
        performance_ms = (time.time() - start_time) * 1000
        return CorrectionResult(
            success=False,
            corrected_content=None,
            corrections_applied=0,
            corrections_skipped=0,
            framework_methods_preserved=0,
            error_message=f"Unexpected error: {e}",
            performance_ms=performance_ms,
        )


def _fallback_regex_correction(content: str, corrections: List[Dict]) -> CorrectionResult:
    """
    Fallback to regex-based correction when libcst is not available.

    This is the old approach that caused false positives, but kept as fallback.
    """
    import re
    import time

    start_time = time.time()

    logger.warning(
        "Using fallback regex-based corrections (may cause false positives). "
        "Install libcst for AST-aware corrections."
    )

    corrected = content
    corrections_applied = 0

    for correction in corrections:
        old_name = correction.get("old_name")
        new_name = correction.get("new_name")

        # Use word boundaries to avoid partial matches
        pattern = r"\b" + re.escape(old_name) + r"\b"
        modified = re.sub(pattern, new_name, corrected)

        if modified != corrected:
            corrections_applied += 1
            corrected = modified

    performance_ms = (time.time() - start_time) * 1000

    return CorrectionResult(
        success=True,
        corrected_content=corrected,
        corrections_applied=corrections_applied,
        corrections_skipped=0,
        framework_methods_preserved=0,
        error_message=None,
        performance_ms=performance_ms,
    )


def apply_single_correction(
    content: str, correction: Dict, framework_detector: Optional[FrameworkMethodDetector] = None
) -> Optional[str]:
    """
    Apply a single correction using AST-based approach.

    Args:
        content: Original source code
        correction: Single correction dict
        framework_detector: Optional framework detector

    Returns:
        Corrected content or None on error
    """
    result = apply_corrections_with_ast(content, [correction], framework_detector)

    if result.success:
        return result.corrected_content
    else:
        logger.error(f"Correction failed: {result.error_message}")
        return None
