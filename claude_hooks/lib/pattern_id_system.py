#!/usr/bin/env python3
"""
Pattern ID & Hashing System
============================

Production-ready pattern identification with content-based hashing, versioning,
and parent-child lineage tracking.

Features:
- Deterministic SHA256-based pattern IDs
- Code normalization for consistent hashing
- Semantic versioning (semver) support
- Parent-child lineage detection via similarity analysis
- Thread-safe deduplication system
- Support for pattern evolution tracking
"""

import hashlib
import re
import threading
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Optional, Set, Tuple, List
from enum import Enum


class ModificationType(Enum):
    """Types of pattern modifications based on similarity"""

    PATCH = "patch"  # >90% similar - minor tweaks
    MINOR = "minor"  # 70-90% similar - moderate changes
    MAJOR = "major"  # <70% similar - significant refactor
    UNRELATED = "unrelated"  # <50% similar - different pattern


@dataclass
class PatternVersion:
    """Semantic version for pattern tracking"""

    major: int = 1
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def from_string(cls, version_str: str) -> "PatternVersion":
        """Parse version from string like '1.2.3'"""
        parts = version_str.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version_str}")

        try:
            return cls(major=int(parts[0]), minor=int(parts[1]), patch=int(parts[2]))
        except ValueError as e:
            raise ValueError(f"Invalid version numbers in {version_str}: {e}")

    def increment_patch(self) -> "PatternVersion":
        """Increment patch version (1.0.0 → 1.0.1)"""
        return PatternVersion(self.major, self.minor, self.patch + 1)

    def increment_minor(self) -> "PatternVersion":
        """Increment minor version (1.0.0 → 1.1.0)"""
        return PatternVersion(self.major, self.minor + 1, 0)

    def increment_major(self) -> "PatternVersion":
        """Increment major version (1.0.0 → 2.0.0)"""
        return PatternVersion(self.major + 1, 0, 0)

    def __lt__(self, other: "PatternVersion") -> bool:
        """Compare versions for sorting"""
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __le__(self, other: "PatternVersion") -> bool:
        """Compare versions for sorting (less than or equal)"""
        return (self.major, self.minor, self.patch) <= (other.major, other.minor, other.patch)

    def __gt__(self, other: "PatternVersion") -> bool:
        """Compare versions for sorting (greater than)"""
        return (self.major, self.minor, self.patch) > (other.major, other.minor, other.patch)

    def __ge__(self, other: "PatternVersion") -> bool:
        """Compare versions for sorting (greater than or equal)"""
        return (self.major, self.minor, self.patch) >= (other.major, other.minor, other.patch)

    def __eq__(self, other: object) -> bool:
        """Check version equality"""
        if not isinstance(other, PatternVersion):
            return False
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __hash__(self) -> int:
        """Hash for use in sets/dicts"""
        return hash((self.major, self.minor, self.patch))


@dataclass
class PatternMetadata:
    """Complete pattern metadata including ID, version, and lineage"""

    pattern_id: str
    version: PatternVersion
    parent_id: Optional[str] = None
    similarity_score: Optional[float] = None
    modification_type: Optional[ModificationType] = None
    created_at: Optional[str] = None
    tags: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            "pattern_id": self.pattern_id,
            "version": str(self.version),
            "parent_id": self.parent_id,
            "similarity_score": self.similarity_score,
            "modification_type": self.modification_type.value if self.modification_type else None,
            "created_at": self.created_at,
            "tags": list(self.tags),
        }


class PatternIDSystem:
    """
    Advanced pattern ID generation with deterministic content-based hashing.

    Generates consistent, reproducible IDs from code content using SHA256.
    Supports normalization to ignore non-semantic differences.
    """

    # Regex patterns for code normalization
    COMMENT_PATTERNS = {
        "python": [
            (re.compile(r"#.*$", re.MULTILINE), ""),  # Line comments
            (re.compile(r'""".*?"""', re.DOTALL), ""),  # Docstrings
            (re.compile(r"'''.*?'''", re.DOTALL), ""),  # Docstrings
        ],
        "javascript": [
            (re.compile(r"//.*$", re.MULTILINE), ""),  # Line comments
            (re.compile(r"/\*.*?\*/", re.DOTALL), ""),  # Block comments
        ],
        "java": [
            (re.compile(r"//.*$", re.MULTILINE), ""),  # Line comments
            (re.compile(r"/\*.*?\*/", re.DOTALL), ""),  # Block comments
        ],
        "typescript": [
            (re.compile(r"//.*$", re.MULTILINE), ""),  # Line comments
            (re.compile(r"/\*.*?\*/", re.DOTALL), ""),  # Block comments
        ],
    }

    @staticmethod
    def generate_id(code: str, normalize: bool = True, language: str = "python") -> str:
        """
        Generate deterministic pattern ID from code.

        Args:
            code: Source code to hash
            normalize: Whether to normalize code before hashing
            language: Programming language for comment removal

        Returns:
            16-character hex string (first 16 chars of SHA256)
        """
        if not code or not code.strip():
            raise ValueError("Cannot generate ID from empty code")

        if normalize:
            code = PatternIDSystem._normalize_code(code, language)

        # Generate SHA256 hash and return first 16 characters
        hash_obj = hashlib.sha256(code.encode("utf-8"))
        return hash_obj.hexdigest()[:16]

    @staticmethod
    def _normalize_code(code: str, language: str = "python") -> str:
        """
        Normalize code for consistent hashing.

        Removes:
        - Comments (language-specific)
        - Leading/trailing whitespace
        - Blank lines
        - Normalizes indentation to single spaces

        Preserves:
        - Semantic structure
        - Code logic
        - Variable names
        - String literals
        """
        # Remove comments based on language
        comment_patterns = PatternIDSystem.COMMENT_PATTERNS.get(
            language.lower(), PatternIDSystem.COMMENT_PATTERNS["python"]  # Default to Python
        )

        normalized = code
        for pattern, replacement in comment_patterns:
            normalized = pattern.sub(replacement, normalized)

        # Split into lines and process
        lines = normalized.split("\n")
        processed_lines = []

        for line in lines:
            # Strip leading/trailing whitespace
            line = line.strip()

            # Skip blank lines
            if not line:
                continue

            # Normalize internal whitespace (multiple spaces → single space)
            line = re.sub(r"\s+", " ", line)

            processed_lines.append(line)

        # Join with newlines for consistent structure
        return "\n".join(processed_lines)

    @staticmethod
    def validate_id(pattern_id: str) -> bool:
        """Validate that a pattern ID is properly formatted"""
        if not pattern_id:
            return False

        # Must be exactly 16 hex characters
        return bool(re.match(r"^[0-9a-f]{16}$", pattern_id))


class PatternLineageDetector:
    """
    Detect parent-child relationships between patterns using similarity analysis.

    Uses SequenceMatcher to calculate similarity and classify modifications.
    Tracks pattern evolution and derivation relationships.
    """

    # Similarity thresholds for classification
    SIMILARITY_THRESHOLDS = {
        "patch": 0.90,  # >90% similar = patch version
        "minor": 0.70,  # 70-90% similar = minor version
        "major": 0.50,  # 50-70% similar = major version
        # <50% = unrelated pattern
    }

    @staticmethod
    def detect_derivation(
        original_code: str, modified_code: str, original_id: Optional[str] = None, language: str = "python"
    ) -> Dict:
        """
        Detect if modified code is derived from original.

        Args:
            original_code: Original source code
            modified_code: Potentially modified source code
            original_id: Pre-computed original pattern ID (optional)
            language: Programming language for normalization

        Returns:
            Dictionary with derivation analysis:
            - is_derived: bool - Whether it's a derivation
            - parent_id: str - Original pattern ID
            - child_id: str - Modified pattern ID
            - similarity_score: float - Similarity ratio (0-1)
            - modification_type: ModificationType - Type of change
            - suggested_version: PatternVersion - Suggested next version
        """
        # Generate pattern IDs
        parent_id = original_id or PatternIDSystem.generate_id(original_code, language=language)
        child_id = PatternIDSystem.generate_id(modified_code, language=language)

        # If IDs are identical, it's the same pattern
        if parent_id == child_id:
            return {
                "is_derived": False,
                "is_identical": True,
                "parent_id": parent_id,
                "child_id": child_id,
                "similarity_score": 1.0,
                "modification_type": None,
                "suggested_version": None,
            }

        # Calculate similarity
        similarity = PatternLineageDetector._calculate_similarity(original_code, modified_code)

        # Classify modification type
        mod_type = PatternLineageDetector._classify_modification(similarity)

        # Suggest version increment
        suggested_version = PatternLineageDetector._suggest_version(mod_type)

        return {
            "is_derived": similarity >= PatternLineageDetector.SIMILARITY_THRESHOLDS["major"],
            "is_identical": False,
            "parent_id": parent_id,
            "child_id": child_id,
            "similarity_score": similarity,
            "modification_type": mod_type,
            "suggested_version": suggested_version,
        }

    @staticmethod
    def _calculate_similarity(code1: str, code2: str) -> float:
        """
        Calculate code similarity using difflib.SequenceMatcher.

        Returns ratio between 0.0 (completely different) and 1.0 (identical).
        """
        matcher = SequenceMatcher(None, code1, code2)
        return matcher.ratio()

    @staticmethod
    def _classify_modification(similarity: float) -> ModificationType:
        """Classify modification type based on similarity score"""
        if similarity >= PatternLineageDetector.SIMILARITY_THRESHOLDS["patch"]:
            return ModificationType.PATCH
        elif similarity >= PatternLineageDetector.SIMILARITY_THRESHOLDS["minor"]:
            return ModificationType.MINOR
        elif similarity >= PatternLineageDetector.SIMILARITY_THRESHOLDS["major"]:
            return ModificationType.MAJOR
        else:
            return ModificationType.UNRELATED

    @staticmethod
    def _suggest_version(
        mod_type: ModificationType, current_version: Optional[PatternVersion] = None
    ) -> PatternVersion:
        """Suggest next version based on modification type"""
        base_version = current_version or PatternVersion()

        if mod_type == ModificationType.PATCH:
            return base_version.increment_patch()
        elif mod_type == ModificationType.MINOR:
            return base_version.increment_minor()
        elif mod_type == ModificationType.MAJOR:
            return base_version.increment_major()
        else:
            # Unrelated - start fresh
            return PatternVersion()

    @staticmethod
    def build_lineage_chain(patterns: List[Tuple[str, str]]) -> Dict[str, List[str]]:
        """
        Build complete lineage chain from pattern pairs.

        Args:
            patterns: List of (original_code, modified_code) tuples

        Returns:
            Dictionary mapping parent IDs to lists of child IDs
        """
        lineage: Dict[str, List[str]] = {}

        for original, modified in patterns:
            result = PatternLineageDetector.detect_derivation(original, modified)

            if result["is_derived"]:
                parent_id = result["parent_id"]
                child_id = result["child_id"]

                if parent_id not in lineage:
                    lineage[parent_id] = []

                lineage[parent_id].append(child_id)

        return lineage


class PatternDeduplicator:
    """
    Thread-safe pattern deduplication system.

    Maintains cache of seen patterns to prevent duplicate tracking.
    Supports version management and lineage tracking.
    """

    def __init__(self):
        """Initialize deduplicator with empty cache and thread lock"""
        self._seen_patterns: Dict[str, PatternMetadata] = {}
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        self._pattern_count = 0

    def check_duplicate(self, code: str, language: str = "python") -> Optional[PatternMetadata]:
        """
        Check if pattern already exists in cache.

        Args:
            code: Source code to check
            language: Programming language

        Returns:
            PatternMetadata if duplicate found, None otherwise
        """
        pattern_id = PatternIDSystem.generate_id(code, language=language)

        with self._lock:
            return self._seen_patterns.get(pattern_id)

    def register_pattern(
        self,
        code: str,
        version: Optional[PatternVersion] = None,
        parent_id: Optional[str] = None,
        language: str = "python",
        tags: Optional[Set[str]] = None,
    ) -> PatternMetadata:
        """
        Register new pattern in cache.

        Args:
            code: Source code to register
            version: Pattern version (defaults to 1.0.0)
            parent_id: Parent pattern ID if derived
            language: Programming language
            tags: Optional tags for categorization

        Returns:
            PatternMetadata for the registered pattern
        """
        pattern_id = PatternIDSystem.generate_id(code, language=language)

        with self._lock:
            # Check if already registered
            if pattern_id in self._seen_patterns:
                return self._seen_patterns[pattern_id]

            # Create metadata
            metadata = PatternMetadata(
                pattern_id=pattern_id, version=version or PatternVersion(), parent_id=parent_id, tags=tags or set()
            )

            self._seen_patterns[pattern_id] = metadata
            self._pattern_count += 1

            return metadata

    def register_with_lineage(
        self, original_code: str, modified_code: str, language: str = "python", tags: Optional[Set[str]] = None
    ) -> Tuple[PatternMetadata, PatternMetadata]:
        """
        Register both original and modified patterns with lineage tracking.

        Args:
            original_code: Original source code
            modified_code: Modified source code
            language: Programming language
            tags: Optional tags for both patterns

        Returns:
            Tuple of (original_metadata, modified_metadata)
        """
        with self._lock:
            # Register original if not exists
            original_meta = self.check_duplicate(original_code, language)
            if not original_meta:
                original_meta = self.register_pattern(original_code, language=language, tags=tags)

            # Detect derivation
            derivation = PatternLineageDetector.detect_derivation(
                original_code, modified_code, original_id=original_meta.pattern_id, language=language
            )

            # Register modified with lineage
            if derivation["is_identical"]:
                # Same pattern, return original twice
                return original_meta, original_meta

            modified_meta = self.check_duplicate(modified_code, language)
            if not modified_meta:
                # Calculate next version
                if derivation["is_derived"]:
                    next_version = derivation["suggested_version"]
                    parent_id = original_meta.pattern_id
                else:
                    next_version = PatternVersion()
                    parent_id = None

                modified_meta = self.register_pattern(
                    modified_code, version=next_version, parent_id=parent_id, language=language, tags=tags
                )

                # Update with similarity info
                modified_meta.similarity_score = derivation["similarity_score"]
                modified_meta.modification_type = derivation["modification_type"]

            return original_meta, modified_meta

    def get_pattern_lineage(self, pattern_id: str) -> List[PatternMetadata]:
        """
        Get complete lineage chain for a pattern.

        Args:
            pattern_id: Pattern ID to trace

        Returns:
            List of PatternMetadata in lineage order (oldest to newest)
        """
        with self._lock:
            lineage = []
            current_id = pattern_id

            # Trace back to root
            while current_id:
                metadata = self._seen_patterns.get(current_id)
                if not metadata:
                    break

                lineage.insert(0, metadata)  # Insert at beginning
                current_id = metadata.parent_id

            return lineage

    def get_children(self, pattern_id: str) -> List[PatternMetadata]:
        """
        Get all direct children of a pattern.

        Args:
            pattern_id: Parent pattern ID

        Returns:
            List of child PatternMetadata
        """
        with self._lock:
            children = []
            for metadata in self._seen_patterns.values():
                if metadata.parent_id == pattern_id:
                    children.append(metadata)

            # Sort by version
            children.sort(key=lambda m: m.version)
            return children

    def get_stats(self) -> Dict:
        """Get deduplicator statistics"""
        with self._lock:
            derived_count = sum(1 for m in self._seen_patterns.values() if m.parent_id)
            root_count = sum(1 for m in self._seen_patterns.values() if not m.parent_id)

            return {
                "total_patterns": self._pattern_count,
                "unique_patterns": len(self._seen_patterns),
                "root_patterns": root_count,
                "derived_patterns": derived_count,
                "deduplication_rate": 1 - (len(self._seen_patterns) / max(self._pattern_count, 1)),
            }

    def clear(self) -> None:
        """Clear all cached patterns (use with caution!)"""
        with self._lock:
            self._seen_patterns.clear()
            self._pattern_count = 0


# Singleton instance for global use
_global_deduplicator: Optional[PatternDeduplicator] = None
_global_lock = threading.Lock()


def get_global_deduplicator() -> PatternDeduplicator:
    """Get or create global deduplicator instance (thread-safe singleton)"""
    global _global_deduplicator

    if _global_deduplicator is None:
        with _global_lock:
            if _global_deduplicator is None:
                _global_deduplicator = PatternDeduplicator()

    return _global_deduplicator


# Convenience functions for common operations
def generate_pattern_id(code: str, normalize: bool = True, language: str = "python") -> str:
    """Convenience function for ID generation"""
    return PatternIDSystem.generate_id(code, normalize, language)


def detect_pattern_derivation(original: str, modified: str, language: str = "python") -> Dict:
    """Convenience function for derivation detection"""
    return PatternLineageDetector.detect_derivation(original, modified, language=language)


def register_pattern(code: str, language: str = "python", tags: Optional[Set[str]] = None) -> PatternMetadata:
    """Convenience function for pattern registration"""
    dedup = get_global_deduplicator()
    return dedup.register_pattern(code, language=language, tags=tags)


if __name__ == "__main__":
    # Example usage and testing
    print("Pattern ID System - Example Usage")
    print("=" * 50)

    # Example 1: Generate pattern IDs
    code1 = """
    def calculate_sum(a, b):
        # Calculate the sum of two numbers
        return a + b
    """

    code2 = """
    def calculate_sum(a, b):
        # Different comment
        return a + b
    """

    code3 = """
    def calculate_sum(a, b):
        result = a + b
        return result
    """

    print("\n1. Pattern ID Generation:")
    print(f"Code 1 ID: {generate_pattern_id(code1)}")
    print(f"Code 2 ID: {generate_pattern_id(code2)}")
    print(f"Code 3 ID: {generate_pattern_id(code3)}")

    # Example 2: Lineage detection
    print("\n2. Lineage Detection:")
    derivation = detect_pattern_derivation(code1, code3)
    print(f"Is derived: {derivation['is_derived']}")
    print(f"Similarity: {derivation['similarity_score']:.2%}")
    print(f"Modification type: {derivation['modification_type'].value if derivation['modification_type'] else 'N/A'}")

    # Example 3: Deduplication
    print("\n3. Pattern Registration:")
    dedup = get_global_deduplicator()

    meta1 = register_pattern(code1, tags={"utility", "math"})
    print(f"Registered: {meta1.pattern_id} v{meta1.version}")

    # Try to register same pattern
    meta2 = register_pattern(code1)
    print(f"Duplicate check: Same as first? {meta1.pattern_id == meta2.pattern_id}")

    # Register with lineage
    original_meta, modified_meta = dedup.register_with_lineage(code1, code3)
    print(f"\nOriginal: {original_meta.pattern_id} v{original_meta.version}")
    print(f"Modified: {modified_meta.pattern_id} v{modified_meta.version}")
    print(f"Similarity: {modified_meta.similarity_score:.2%}")

    # Example 4: Statistics
    print("\n4. Deduplicator Statistics:")
    stats = dedup.get_stats()
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"{key}: {value:.2%}")
        else:
            print(f"{key}: {value}")
