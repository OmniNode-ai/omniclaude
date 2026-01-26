"""DEPRECATED: Use ProtocolPatternPersistence via container resolution.

This module is DEAD. Do not use it.
"""

raise RuntimeError(
    "repository_patterns.py is deprecated and removed. "
    "Use ProtocolPatternPersistence from "
    "omniclaude.nodes.node_pattern_persistence_effect.protocols "
    "resolved via container.get_service_async(ProtocolPatternPersistence)"
)
