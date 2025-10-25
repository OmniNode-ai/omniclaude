#!/usr/bin/env python3
"""
Code Refiner - Pattern Matcher & Applicator (Poly 2)

Finds and applies production ONEX patterns to generated code using:
1. ProductionPatternMatcher - Discovers similar production nodes
2. CodeRefiner - Applies patterns using AI-powered refinement

Part of the node generation pipeline for producing production-ready ONEX code.
"""

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai

from .config.intelligence_config import IntelligenceConfig
from .intelligence_event_client import IntelligenceEventClient

logger = logging.getLogger(__name__)


# ============================================================================
# Pattern Extraction Models
# ============================================================================


@dataclass
class ProductionPattern:
    """
    Extracted pattern from production code.

    Attributes:
        node_path: Path to production node file
        node_type: Node type (effect, compute, reducer, orchestrator)
        domain: Domain/category of the node
        imports: Import statements extracted
        class_structure: Class definition patterns
        method_signatures: Method signature patterns
        error_handling: Error handling patterns
        transaction_management: Transaction management patterns (Effect nodes)
        metrics_tracking: Metrics tracking patterns
        documentation: Docstring patterns
        key_patterns: Key implementation patterns
        confidence: Pattern applicability confidence (0.0-1.0)
    """

    node_path: Path
    node_type: str
    domain: str
    imports: List[str] = field(default_factory=list)
    class_structure: str = ""
    method_signatures: List[str] = field(default_factory=list)
    error_handling: List[str] = field(default_factory=list)
    transaction_management: List[str] = field(default_factory=list)
    metrics_tracking: List[str] = field(default_factory=list)
    documentation: List[str] = field(default_factory=list)
    key_patterns: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class RefinementContext:
    """
    Context for code refinement operations.

    Attributes:
        file_type: Type of file being refined (model, node, enum, contract)
        node_type: ONEX node type (effect, compute, reducer, orchestrator)
        domain: Domain/category (database, api, analytics, etc.)
        original_code: Original generated code
        production_patterns: Extracted production patterns
        requirements: Additional requirements/constraints
    """

    file_type: str
    node_type: Optional[str]
    domain: str
    original_code: str
    production_patterns: List[ProductionPattern] = field(default_factory=list)
    requirements: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Production Pattern Matcher
# ============================================================================


class ProductionPatternMatcher:
    """
    Finds similar production nodes and extracts applicable patterns.

    Uses production catalog and filesystem scanning to discover
    relevant ONEX patterns from omniarchon codebase.
    """

    # Production codebase paths (configurable via environment variables)
    # Default: assumes sibling directories
    OMNIARCHON_PATH = Path(
        os.getenv(
            "OMNIARCHON_PATH",
            str(Path(__file__).resolve().parents[2] / "../omniarchon"),
        )
    ).resolve()
    OMNINODE_BRIDGE_PATH = Path(
        os.getenv(
            "OMNINODE_BRIDGE_PATH",
            str(Path(__file__).resolve().parents[2] / "../omninode_bridge"),
        )
    ).resolve()

    # Node type to directory mappings (omniarchon structure)
    NODE_TYPE_PATHS = {
        "effect": [
            "services/intelligence/onex/effects",
            "services/intelligence/src/services/pattern_learning",
        ],
        "compute": [
            "services/intelligence/src/services/pattern_learning/phase1_foundation/extraction",
            "services/intelligence/src/services/pattern_learning/phase3_validation",
        ],
        "reducer": [
            "services/intelligence/src/services/pattern_learning/phase4_traceability",
        ],
        "orchestrator": [
            "services/intelligence/src/services/pattern_learning/phase1_foundation/extraction",
            "services/intelligence/src/services/pattern_learning/phase3_validation",
            "services/intelligence/src/services/pattern_learning/phase4_traceability",
        ],
    }

    # Best production examples by node type (from catalog)
    BEST_EXAMPLES = {
        "effect": [
            "services/intelligence/onex/effects/node_qdrant_search_effect.py",
            "services/intelligence/onex/effects/node_qdrant_vector_index_effect.py",
            "services/intelligence/src/pattern_learning/node_pattern_storage_effect.py",
        ],
        "compute": [
            "services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_intent_classifier_compute.py",
            "services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_keyword_extractor_compute.py",
            "services/intelligence/src/services/pattern_learning/phase3_validation/node_onex_validator_compute.py",
        ],
        "reducer": [
            "services/intelligence/src/services/pattern_learning/phase4_traceability/node_usage_analytics_reducer.py",
        ],
        "orchestrator": [
            "services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_pattern_assembler_orchestrator.py",
            "services/intelligence/src/services/pattern_learning/phase3_validation/node_quality_gate_orchestrator.py",
        ],
    }

    def __init__(
        self,
        event_client: Optional[IntelligenceEventClient] = None,
        config: Optional[IntelligenceConfig] = None,
    ):
        """
        Initialize pattern matcher with production codebase paths and
        optional event client.
        """
        self.cache: Dict[str, ProductionPattern] = {}
        self.event_client = event_client
        self.config = config or IntelligenceConfig.from_env()
        logger.info("Initialized ProductionPatternMatcher")

    async def find_similar_nodes(
        self, node_type: str, domain: str, limit: int = 3
    ) -> List[Path]:
        """
        Search for similar production nodes by type and domain.

        Uses event-based discovery first (if enabled), then falls back
        to filesystem scanning for local development.

        Args:
            node_type: ONEX node type (effect, compute, reducer, orchestrator)
            domain: Domain/category (database, api, analytics, vector_search, etc.)
            limit: Maximum number of examples to return

        Returns:
            List of paths to similar production nodes

        Example:
            >>> matcher = ProductionPatternMatcher()
            >>> nodes = await matcher.find_similar_nodes("effect", "database")
            >>> assert len(nodes) <= 3
        """
        logger.info(f"Finding similar {node_type} nodes for domain '{domain}'")

        # Try event-based discovery first
        if self.config.is_event_discovery_enabled() and self.event_client:
            try:
                event_patterns = await self._find_nodes_via_events(
                    node_type=node_type,
                    domain=domain,
                    limit=limit,
                )
                if event_patterns:
                    logger.info(f"Found {len(event_patterns)} nodes via events")
                    return event_patterns
            except Exception as e:
                logger.warning(
                    f"Event-based discovery failed: {e}, falling back to filesystem"
                )

        # Fallback to filesystem scanning (original implementation)
        similar_nodes: List[Tuple[Path, float]] = []

        # 1. Start with best examples for this node type
        if node_type in self.BEST_EXAMPLES:
            for example_path in self.BEST_EXAMPLES[node_type]:
                full_path = self.OMNIARCHON_PATH / example_path
                if full_path.exists():
                    # Calculate domain similarity score
                    score = self._calculate_domain_similarity(domain, example_path)
                    similar_nodes.append((full_path, score))
                    logger.debug(
                        f"Added best example: {example_path} (score: {score:.2f})"
                    )

        # 2. Scan node type directories for additional matches
        if node_type in self.NODE_TYPE_PATHS:
            for search_dir in self.NODE_TYPE_PATHS[node_type]:
                search_path = self.OMNIARCHON_PATH / search_dir
                if not search_path.exists():
                    continue

                # Find all node files of this type
                pattern = f"node_*_{node_type}.py"
                for node_file in search_path.rglob(pattern):
                    if node_file in [n[0] for n in similar_nodes]:
                        continue  # Skip duplicates

                    # Calculate domain similarity
                    score = self._calculate_domain_similarity(domain, str(node_file))
                    similar_nodes.append((node_file, score))
                    logger.debug(
                        f"Found candidate: {node_file.name} (score: {score:.2f})"
                    )

        # 3. Sort by similarity score and return top N
        similar_nodes.sort(key=lambda x: x[1], reverse=True)
        result = [node[0] for node in similar_nodes[:limit]]

        logger.info(f"Found {len(result)} similar nodes for {node_type}/{domain}")
        return result

    async def _find_nodes_via_events(
        self, node_type: str, domain: str, limit: int = 3
    ) -> List[Path]:
        """
        Find similar nodes using event-based intelligence discovery.

        Args:
            node_type: ONEX node type (effect, compute, reducer, orchestrator)
            domain: Domain/category (database, api, analytics, etc.)
            limit: Maximum number of examples to return

        Returns:
            List of paths to similar production nodes

        Raises:
            Exception: If event client not configured or request fails
        """
        if not self.event_client:
            raise ValueError("Event client not configured")

        # Build search pattern for this node type
        search_pattern = f"node_*_{node_type}.py"

        # Request pattern discovery via events
        response = await self.event_client.request_pattern_discovery(
            source_path=search_pattern,
            language="python",
            timeout_ms=self.config.kafka_request_timeout_ms,
        )

        # Extract patterns from response
        node_paths = []
        if response and isinstance(response, list):
            for pattern_data in response[:limit]:
                # Extract file path from pattern data
                file_path = pattern_data.get("file_path") or pattern_data.get("path")
                if file_path:
                    # Calculate domain similarity for ranking
                    similarity = self._calculate_domain_similarity(domain, file_path)
                    node_paths.append((Path(file_path), similarity))

        # Sort by similarity and return top N
        node_paths.sort(key=lambda x: x[1], reverse=True)
        return [path[0] for path in node_paths[:limit]]

    def _calculate_domain_similarity(self, target_domain: str, file_path: str) -> float:
        """
        Calculate similarity between target domain and file path.

        Uses keyword matching and path analysis to estimate relevance.

        Args:
            target_domain: Target domain (e.g., "database", "api", "vector_search")
            file_path: Path to production node file

        Returns:
            Similarity score (0.0-1.0)
        """
        # Normalize domain and path
        domain_lower = target_domain.lower()
        path_lower = str(file_path).lower()
        file_name = Path(file_path).stem.lower()

        score = 0.0

        # Exact domain match in file name (highest weight)
        if domain_lower in file_name:
            score += 1.0

        # Domain keywords in file name (medium weight)
        domain_keywords = domain_lower.replace("_", " ").split()
        name_keywords = file_name.replace("_", " ").split()
        keyword_matches = sum(1 for kw in domain_keywords if kw in name_keywords)
        if domain_keywords:
            score += 0.5 * (keyword_matches / len(domain_keywords))

        # Domain in path (low weight)
        if domain_lower in path_lower:
            score += 0.3

        # Boost for best examples
        if "best" in path_lower or "example" in path_lower:
            score *= 1.2

        return min(score, 1.0)  # Cap at 1.0

    def extract_patterns(self, node_path: Path) -> ProductionPattern:
        """
        Extract reusable patterns from production code.

        Parses production node file and extracts:
        - Import statements
        - Class structure and inheritance
        - Method signatures
        - Error handling patterns
        - Transaction management (Effect nodes)
        - Metrics tracking
        - Documentation patterns

        Args:
            node_path: Path to production node file

        Returns:
            ProductionPattern with extracted patterns

        Example:
            >>> matcher = ProductionPatternMatcher()
            >>> pattern = matcher.extract_patterns(
            ...     Path("/path/to/node_qdrant_search_effect.py")
            ... )
            >>> assert pattern.node_type == "effect"
            >>> assert len(pattern.imports) > 0
        """
        # Check cache first
        cache_key = str(node_path)
        if cache_key in self.cache:
            logger.debug(f"Using cached pattern for {node_path.name}")
            return self.cache[cache_key]

        logger.info(f"Extracting patterns from {node_path.name}")

        # Determine node type from filename
        node_type = self._extract_node_type(node_path.name)
        domain = self._extract_domain(node_path.name)

        # Read source code
        try:
            source_code = node_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read {node_path}: {e}")
            return ProductionPattern(
                node_path=node_path,
                node_type=node_type,
                domain=domain,
                confidence=0.0,
            )

        # Parse AST
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            logger.error(f"Syntax error parsing {node_path}: {e}")
            return ProductionPattern(
                node_path=node_path,
                node_type=node_type,
                domain=domain,
                confidence=0.0,
            )

        # Extract patterns
        pattern = ProductionPattern(
            node_path=node_path,
            node_type=node_type,
            domain=domain,
        )

        # Extract imports
        pattern.imports = self._extract_imports(tree)

        # Extract class structure
        pattern.class_structure = self._extract_class_structure(tree, source_code)

        # Extract method signatures
        pattern.method_signatures = self._extract_method_signatures(tree)

        # Extract error handling
        pattern.error_handling = self._extract_error_handling(source_code)

        # Extract transaction management (Effect nodes)
        if node_type == "effect":
            pattern.transaction_management = self._extract_transaction_patterns(
                source_code
            )

        # Extract metrics tracking
        pattern.metrics_tracking = self._extract_metrics_patterns(source_code)

        # Extract documentation patterns
        pattern.documentation = self._extract_documentation(tree)

        # Calculate confidence based on completeness
        pattern.confidence = self._calculate_pattern_confidence(pattern)

        # Cache the pattern
        self.cache[cache_key] = pattern

        logger.info(
            f"Extracted pattern from {node_path.name} "
            f"(confidence: {pattern.confidence:.2f})"
        )
        return pattern

    def _extract_node_type(self, filename: str) -> str:
        """Extract node type from filename."""
        if "_effect.py" in filename:
            return "effect"
        elif "_compute.py" in filename:
            return "compute"
        elif "_reducer.py" in filename:
            return "reducer"
        elif "_orchestrator.py" in filename:
            return "orchestrator"
        return "unknown"

    def _extract_domain(self, filename: str) -> str:
        """Extract domain from filename."""
        # Remove prefix and suffix
        name = filename.replace("node_", "").replace(".py", "")
        # Remove node type suffix
        for suffix in ["_effect", "_compute", "_reducer", "_orchestrator"]:
            name = name.replace(suffix, "")
        return name

    def _extract_imports(self, tree: ast.AST) -> List[str]:
        """Extract import statements from AST."""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = ", ".join(alias.name for alias in node.names)
                imports.append(f"from {module} import {names}")
        return imports

    def _extract_class_structure(self, tree: ast.AST, source_code: str) -> str:
        """Extract class definition and inheritance."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Get the class definition line
                lines = source_code.split("\n")
                if node.lineno <= len(lines):
                    return lines[node.lineno - 1].strip()
        return ""

    def _extract_method_signatures(self, tree: ast.AST) -> List[str]:
        """Extract method signatures from class definitions."""
        signatures = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) or isinstance(
                        item, ast.AsyncFunctionDef
                    ):
                        # Build signature
                        is_async = isinstance(item, ast.AsyncFunctionDef)
                        prefix = "async " if is_async else ""
                        args_str = self._build_args_string(item.args)
                        return_annotation = ""
                        if item.returns:
                            return_annotation = f" -> {ast.unparse(item.returns)}"
                        sig = f"{prefix}def {item.name}({args_str}){return_annotation}"
                        signatures.append(sig)
        return signatures

    def _build_args_string(self, args: ast.arguments) -> str:
        """Build argument string from ast.arguments."""
        parts = []
        for arg in args.args:
            annotation = ""
            if arg.annotation:
                annotation = f": {ast.unparse(arg.annotation)}"
            parts.append(f"{arg.arg}{annotation}")
        return ", ".join(parts)

    def _extract_error_handling(self, source_code: str) -> List[str]:
        """Extract error handling patterns."""
        patterns = []

        # Find try-except blocks
        try_except_pattern = re.compile(
            r"try:.*?except\s+(\w+(?:\s*,\s*\w+)*)\s+as\s+(\w+):", re.DOTALL
        )
        for match in try_except_pattern.finditer(source_code):
            patterns.append(f"except {match.group(1)} as {match.group(2)}")

        # Find logger.error patterns
        logger_pattern = re.compile(r"logger\.(error|warning|info)\([^)]+\)")
        for match in logger_pattern.finditer(source_code):
            patterns.append(match.group(0))

        return patterns

    def _extract_transaction_patterns(self, source_code: str) -> List[str]:
        """Extract transaction management patterns (Effect nodes)."""
        patterns = []

        # Find transaction manager usage
        transaction_pattern = re.compile(
            r"async with self\.transaction_manager\.begin\(\):"
        )
        if transaction_pattern.search(source_code):
            patterns.append("async with self.transaction_manager.begin():")

        return patterns

    def _extract_metrics_patterns(self, source_code: str) -> List[str]:
        """Extract metrics tracking patterns."""
        patterns = []

        # Find _record_metric calls
        metrics_pattern = re.compile(r"self\._record_metric\([^)]+\)")
        for match in metrics_pattern.finditer(source_code):
            patterns.append(match.group(0))

        # Find time.perf_counter usage
        if "time.perf_counter()" in source_code:
            patterns.append("time.perf_counter()")

        return patterns

    def _extract_documentation(self, tree: ast.AST) -> List[str]:
        """Extract docstring patterns."""
        docs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node)
                if docstring:
                    docs.append(docstring)
        return docs

    def _calculate_pattern_confidence(self, pattern: ProductionPattern) -> float:
        """Calculate pattern confidence based on completeness."""
        score = 0.0

        # Check for required components
        if pattern.imports:
            score += 0.2
        if pattern.class_structure:
            score += 0.2
        if pattern.method_signatures:
            score += 0.2
        if pattern.error_handling:
            score += 0.15
        if pattern.documentation:
            score += 0.15

        # Bonus for Effect nodes with transaction management
        if pattern.node_type == "effect" and pattern.transaction_management:
            score += 0.1

        return min(score, 1.0)


# ============================================================================
# Code Refiner
# ============================================================================


class CodeRefiner:
    """
    Applies production patterns to generated code using AI refinement.

    Uses Gemini 2.5 Flash to refine generated code with production patterns
    extracted from omniarchon codebase.
    """

    def __init__(
        self,
        event_client: Optional[IntelligenceEventClient] = None,
        config: Optional[IntelligenceConfig] = None,
    ):
        """
        Initialize code refiner with AI model, pattern matcher, and
        optional event client.
        """
        # Initialize Gemini 2.5 Flash
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash-exp")

        # Initialize pattern matcher with event client
        self.pattern_matcher = ProductionPatternMatcher(
            event_client=event_client,
            config=config,
        )

        # Pattern extraction cache
        self.pattern_cache: Dict[str, List[ProductionPattern]] = {}

        logger.info(
            "Initialized CodeRefiner with Gemini 2.5 Flash and " "event-based discovery"
        )

    async def refine_code(
        self,
        code: str,
        file_type: str,
        refinement_context: Dict[str, Any],
    ) -> str:
        """
        Use AI to refine code with production patterns.

        Args:
            code: Original generated code
            file_type: Type of file (model, node, enum, contract)
            refinement_context: Context with node_type, domain, requirements

        Returns:
            Refined code with production patterns applied

        Raises:
            ValueError: If refinement fails or produces invalid code

        Example:
            >>> refiner = CodeRefiner()
            >>> refined = await refiner.refine_code(
            ...     code=generated_code,
            ...     file_type="node",
            ...     refinement_context={
            ...         "node_type": "effect",
            ...         "domain": "database",
            ...         "requirements": {"transaction_management": True}
            ...     }
            ... )
            >>> assert "async with self.transaction_manager.begin():" in refined
        """
        logger.info(
            f"Refining {file_type} code for "
            f"{refinement_context.get('node_type', 'N/A')}/"
            f"{refinement_context.get('domain', 'N/A')}"
        )

        # 1. Find production patterns
        patterns = await self._get_production_patterns(refinement_context)
        if not patterns:
            logger.warning("No production patterns found, returning original code")
            return code

        # 2. Build refinement prompt
        prompt = self._build_refinement_prompt(
            code, file_type, patterns, refinement_context
        )

        # 3. Call AI model
        try:
            response = self.model.generate_content(prompt)
            refined_code = self._extract_code_from_response(response.text)
        except Exception as e:
            logger.error(f"AI refinement failed: {e}")
            raise ValueError(f"AI refinement failed: {e}")

        # 4. Validate refined code compiles
        if not self._validate_code_compiles(refined_code):
            logger.error("Refined code does not compile, returning original")
            return code

        logger.info("Code refinement completed successfully")
        return refined_code

    async def _get_production_patterns(
        self, context: Dict[str, Any]
    ) -> List[ProductionPattern]:
        """
        Get production patterns from cache or pattern matcher.

        Args:
            context: Refinement context with node_type, domain

        Returns:
            List of applicable production patterns
        """
        node_type = context.get("node_type")
        domain = context.get("domain", "")

        if not node_type:
            return []

        # Check cache
        cache_key = f"{node_type}:{domain}"
        if cache_key in self.pattern_cache:
            logger.debug(f"Using cached patterns for {cache_key}")
            return self.pattern_cache[cache_key]

        # Find similar nodes
        similar_nodes = await self.pattern_matcher.find_similar_nodes(
            node_type=node_type,
            domain=domain,
            limit=3,
        )

        # Extract patterns
        patterns = []
        for node_path in similar_nodes:
            pattern = self.pattern_matcher.extract_patterns(node_path)
            if pattern.confidence > 0.5:  # Only use high-confidence patterns
                patterns.append(pattern)

        # Cache patterns
        self.pattern_cache[cache_key] = patterns

        logger.info(f"Loaded {len(patterns)} production patterns for {cache_key}")
        return patterns

    def _build_refinement_prompt(
        self,
        code: str,
        file_type: str,
        patterns: List[ProductionPattern],
        context: Dict[str, Any],
    ) -> str:
        """
        Build AI prompt for code refinement.

        Args:
            code: Original code
            file_type: File type (model, node, enum, contract)
            patterns: Production patterns to apply
            context: Additional context

        Returns:
            Refinement prompt for AI model
        """
        # Build pattern examples section
        pattern_examples = []
        for i, pattern in enumerate(patterns, 1):
            example = f"""
### Production Example {i}: {pattern.node_path.name}

**Imports:**
```python
{chr(10).join(pattern.imports[:10])}  # Top 10 imports
```

**Class Structure:**
```python
{pattern.class_structure}
```

**Method Signatures:**
```python
{chr(10).join(pattern.method_signatures[:5])}  # Key methods
```

**Error Handling:**
```python
{chr(10).join(pattern.error_handling[:3])}  # Error patterns
```

**Documentation:**
```
{pattern.documentation[0] if pattern.documentation else 'N/A'}
```
"""
            pattern_examples.append(example)

        prompt = f"""
You are an expert Python developer specializing in ONEX architecture patterns.

**Task**: Refine the following {file_type} code to match production ONEX patterns.

**CRITICAL REQUIREMENTS**:
1. Use `model_config = ConfigDict(...)` instead of `class Config` (Pydantic v2)
2. Add full type hints to all parameters and return values
3. Add comprehensive docstrings (Google style)
4. Follow import order: stdlib → third-party → local
5. Use proper error handling with context logging
6. For Effect nodes: Use `async with self.transaction_manager.begin():`
7. Add performance metrics tracking with `self._record_metric()`
8. Follow ONEX naming: `Node<Name><Type>`, `Model<Name>`, `Enum<Name>`

**Production Patterns to Apply**:
{''.join(pattern_examples)}

**Original Code**:
```python
{code}
```

**Context**:
- File Type: {file_type}
- Node Type: {context.get('node_type', 'N/A')}
- Domain: {context.get('domain', 'N/A')}

**Instructions**:
1. Apply production patterns from the examples above
2. Ensure code follows all CRITICAL REQUIREMENTS
3. Preserve original functionality and logic
4. Return ONLY the refined code, no explanations
5. Code must be valid Python that compiles without errors

**Output Format**:
```python
# Refined code here
```
"""
        return prompt

    def _extract_code_from_response(self, response_text: str) -> str:
        """
        Extract Python code from AI response.

        Args:
            response_text: Raw AI response text

        Returns:
            Extracted Python code
        """
        # Find code between ```python and ``` markers
        import re

        # Try to find code block with language specifier
        pattern = r"```(?:python)?\s*\n(.*?)```"
        matches = re.findall(pattern, response_text, re.DOTALL)

        if matches:
            # Return the first (or largest) code block
            return matches[0].strip()

        # Fallback: return stripped response
        return response_text.strip()

    def _validate_code_compiles(self, code: str) -> bool:
        """
        Validate that refined code compiles.

        Args:
            code: Python code to validate

        Returns:
            True if code compiles, False otherwise
        """
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            logger.error(f"Code validation failed: {e}")
            return False
