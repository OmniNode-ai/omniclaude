"""
Import Utils Demo - Before/After Usage Examples

Demonstrates how to replace repetitive try/except import blocks with
the import_from_lib() utility function.

This file is for documentation purposes only and shows the refactoring
pattern for existing code.
"""

# ============================================================================
# BEFORE: Repetitive try/except pattern (60+ lines for 5 imports)
# ============================================================================

"""
# Import IntelligenceEventClient
try:
    from intelligence_event_client import IntelligenceEventClient
except ImportError:
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from intelligence_event_client import IntelligenceEventClient

# Import IntelligenceCache
try:
    from intelligence_cache import IntelligenceCache
except ImportError:
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from intelligence_cache import IntelligenceCache

# Import PatternQualityScorer
try:
    from pattern_quality_scorer import PatternQualityScorer
except ImportError:
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from pattern_quality_scorer import PatternQualityScorer

# Import TaskClassifier (multiple classes)
try:
    from task_classifier import TaskClassifier, TaskContext, TaskIntent
except ImportError:
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from task_classifier import TaskClassifier, TaskContext, TaskIntent

# Import ArchonHybridScorer
try:
    from archon_hybrid_scorer import ArchonHybridScorer
except ImportError:
    import sys
    from pathlib import Path

    lib_path = Path(__file__).parent
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    from archon_hybrid_scorer import ArchonHybridScorer
"""


# ============================================================================
# AFTER: Clean, concise pattern using import_utils (15 lines for 5 imports)
# ============================================================================

from import_utils import (  # noqa: E402 (demo file - import shown in context)
    import_from_lib,
)


# Import modules
intelligence_event_client = import_from_lib("intelligence_event_client")
intelligence_cache = import_from_lib("intelligence_cache")
pattern_quality_scorer = import_from_lib("pattern_quality_scorer")
task_classifier = import_from_lib("task_classifier")

# Note: archon_hybrid_scorer has a dependency issue (imports from agents.lib)
# This demonstrates that import_from_lib correctly propagates ImportError
# when underlying modules have unresolved dependencies
try:
    archon_hybrid_scorer = import_from_lib("archon_hybrid_scorer")
    ArchonHybridScorer = archon_hybrid_scorer.ArchonHybridScorer
except ModuleNotFoundError as e:
    print(f"Note: archon_hybrid_scorer has dependency issues: {e}")
    ArchonHybridScorer = None

# Access classes
IntelligenceEventClient = intelligence_event_client.IntelligenceEventClient
IntelligenceCache = intelligence_cache.IntelligenceCache
PatternQualityScorer = pattern_quality_scorer.PatternQualityScorer

# Multiple classes from same module
TaskClassifier = task_classifier.TaskClassifier
TaskContext = task_classifier.TaskContext
TaskIntent = task_classifier.TaskIntent


# ============================================================================
# BENEFITS
# ============================================================================

"""
Code Reduction:
    - Before: 60+ lines of repetitive try/except blocks
    - After: 15 lines of clean, readable imports
    - Reduction: 75% less code

Maintainability:
    - Single point of change for import logic
    - No duplicated error handling
    - Consistent behavior across all imports

Readability:
    - Clear import pattern
    - Easy to understand intent
    - Follows DRY principle

Performance:
    - Same performance as manual try/except
    - sys.path modification only happens once per module
    - Modules cached in sys.modules as normal

ONEX Compliance:
    - Follows utility function pattern
    - Centralized computation logic (COMPUTE node type)
    - Type hints and comprehensive documentation
"""


# ============================================================================
# USAGE IN EXISTING CODE
# ============================================================================


def example_usage():
    """Show how to use imported classes in existing code."""
    # Classes are imported normally and can be used as before
    # Prefixed with _ to indicate demo/example usage
    _client = IntelligenceEventClient(bootstrap_servers="localhost:9092")  # noqa: F841

    _cache = IntelligenceCache()  # noqa: F841

    _scorer = PatternQualityScorer()  # noqa: F841

    _classifier = TaskClassifier()  # noqa: F841
    _context = TaskContext(task_type="code_generation")  # noqa: F841
    _intent = TaskIntent.CREATE  # noqa: F841

    if ArchonHybridScorer:
        _hybrid_scorer = ArchonHybridScorer()  # noqa: F841

    # All functionality remains the same
    # Only the import mechanism has changed


if __name__ == "__main__":
    print("✓ Core imports successful")
    print("✓ Classes accessible:")
    print(f"  - IntelligenceEventClient: {IntelligenceEventClient.__name__}")
    print(f"  - IntelligenceCache: {IntelligenceCache.__name__}")
    print(f"  - PatternQualityScorer: {PatternQualityScorer.__name__}")
    print(f"  - TaskClassifier: {TaskClassifier.__name__}")
    print(f"  - TaskContext: {TaskContext.__name__}")
    print(f"  - TaskIntent: {TaskIntent.__name__}")
    if ArchonHybridScorer:
        print(f"  - ArchonHybridScorer: {ArchonHybridScorer.__name__}")
    else:
        print("  - ArchonHybridScorer: (skipped due to dependency issues)")
    print("\n✓ Demo completed successfully")
    print("\nNote: import_from_lib correctly propagates ImportError for modules")
    print("      with unresolved dependencies, maintaining proper error handling.")
