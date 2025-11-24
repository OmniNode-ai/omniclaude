#!/usr/bin/env python3
"""
Generate Migration Patch for config.settings

Analyzes a Python file and generates a suggested migration patch
to replace os.getenv() calls with config.settings.

Usage:
    python3 scripts/generate_migration_patch.py <file_path>
    python3 scripts/generate_migration_patch.py agents/services/agent_router_event_service.py
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


# Known environment variable mappings
ENV_VAR_MAPPING = {
    "KAFKA_BOOTSTRAP_SERVERS": "settings.get_effective_kafka_bootstrap_servers()",
    "KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS": "settings.kafka_intelligence_bootstrap_servers",
    "KAFKA_BROKERS": "settings.kafka_bootstrap_servers",
    "KAFKA_GROUP_ID": "settings.kafka_group_id",
    "REGISTRY_PATH": "settings.registry_path",
    "HEALTH_CHECK_PORT": "settings.health_check_port",
    "POSTGRES_HOST": "settings.postgres_host",
    "POSTGRES_PORT": "settings.postgres_port",
    "POSTGRES_DATABASE": "settings.postgres_database",
    "POSTGRES_USER": "settings.postgres_user",
    "POSTGRES_PASSWORD": "settings.get_effective_postgres_password()",
    "QDRANT_HOST": "settings.qdrant_host",
    "QDRANT_PORT": "settings.qdrant_port",
    "QDRANT_URL": "settings.qdrant_url",
    "ENABLE_PATTERN_QUALITY_FILTER": "settings.enable_pattern_quality_filter",
    "MIN_PATTERN_QUALITY": "settings.min_pattern_quality",
    "ENABLE_INTELLIGENCE_CACHE": "settings.enable_intelligence_cache",
    "CACHE_TTL_PATTERNS": "settings.cache_ttl_patterns",
    "CACHE_TTL_INFRASTRUCTURE": "settings.cache_ttl_infrastructure",
    "MANIFEST_CACHE_TTL_SECONDS": "settings.manifest_cache_ttl_seconds",
    "VALKEY_URL": "settings.valkey_url",
    "ARCHON_INTELLIGENCE_URL": "settings.archon_intelligence_url",
    "ARCHON_SEARCH_URL": "settings.archon_search_url",
    "ARCHON_BRIDGE_URL": "settings.archon_bridge_url",
    "ARCHON_MCP_URL": "settings.archon_mcp_url",
}


def extract_getenv_calls(content: str) -> List[Tuple[str, str, str, int]]:
    """
    Extract all os.getenv() calls from content.

    Returns:
        List of (full_match, var_name, default_value, line_number)
    """
    results = []
    lines = content.split("\n")

    # Pattern: os.getenv("VAR_NAME", "default") or os.getenv("VAR_NAME")
    pattern = r'os\.getenv\(["\'](\w+)["\'](?:,\s*["\']([^"\']*)["\'])?\)'

    for line_num, line in enumerate(lines, 1):
        for match in re.finditer(pattern, line):
            full_match = match.group(0)
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else None
            results.append((full_match, var_name, default, line_num))

    return results


def generate_migration_suggestion(var_name: str, default: str) -> str:
    """Generate suggested settings.* replacement."""
    if var_name in ENV_VAR_MAPPING:
        return ENV_VAR_MAPPING[var_name]

    # Generate generic suggestion
    setting_name = var_name.lower()
    return f"settings.{setting_name}  # TODO: Verify this exists in config/settings.py"


def analyze_type_conversions(content: str) -> List[Tuple[str, str, int]]:
    """
    Find type conversion patterns that can be removed.

    Returns:
        List of (pattern, suggestion, line_number)
    """
    results = []
    lines = content.split("\n")

    # Pattern: int(os.getenv(...))
    int_pattern = r'int\(os\.getenv\(["\'](\w+)["\'].*?\)\)'
    # Pattern: float(os.getenv(...))
    float_pattern = r'float\(os\.getenv\(["\'](\w+)["\'].*?\)\)'
    # Pattern: os.getenv(...).lower() == "true"
    bool_pattern = r'os\.getenv\(["\'](\w+)["\'].*?\)\.lower\(\)\s*==\s*["\']true["\']'

    for line_num, line in enumerate(lines, 1):
        # Check int conversions
        for match in re.finditer(int_pattern, line):
            var_name = match.group(1)
            suggestion = generate_migration_suggestion(var_name, None)
            results.append(
                (
                    match.group(0),
                    suggestion + "  # Already int, no conversion needed",
                    line_num,
                )
            )

        # Check float conversions
        for match in re.finditer(float_pattern, line):
            var_name = match.group(1)
            suggestion = generate_migration_suggestion(var_name, None)
            results.append(
                (
                    match.group(0),
                    suggestion + "  # Already float, no conversion needed",
                    line_num,
                )
            )

        # Check bool conversions
        for match in re.finditer(bool_pattern, line):
            var_name = match.group(1)
            suggestion = generate_migration_suggestion(var_name, None)
            results.append(
                (
                    match.group(0),
                    suggestion + "  # Already bool, no conversion needed",
                    line_num,
                )
            )

    return results


def main():
    """Generate migration patch."""
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/generate_migration_patch.py <file_path>")
        print()
        print("Examples:")
        print(
            "  python3 scripts/generate_migration_patch.py agents/services/agent_router_event_service.py"
        )
        print(
            "  python3 scripts/generate_migration_patch.py agents/lib/manifest_injector.py"
        )
        sys.exit(1)

    filepath = sys.argv[1]
    # Use project root dynamically (scripts/ is in project root)
    root = Path(__file__).parent.parent.resolve()
    full_path = root / filepath if not filepath.startswith("/") else Path(filepath)

    if not full_path.exists():
        print(f"❌ File not found: {full_path}")
        sys.exit(1)

    # Read file
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract os.getenv() calls
    getenv_calls = extract_getenv_calls(content)

    # Check if already has settings import
    has_settings_import = "from config import settings" in content

    print("=" * 80)
    print(f"MIGRATION PATCH FOR: {filepath}")
    print("=" * 80)
    print()

    # Summary
    print("SUMMARY:")
    print(f"  os.getenv() calls: {len(getenv_calls)}")
    print(f"  Has settings import: {'✅ Yes' if has_settings_import else '❌ No'}")
    print()

    if not getenv_calls:
        print("✅ No os.getenv() calls found. File may already be migrated!")
        sys.exit(0)

    # Step 1: Add import
    print("=" * 80)
    print("STEP 1: ADD IMPORT (if not present)")
    print("=" * 80)
    print()

    if not has_settings_import:
        print("Add this import at the top of the file:")
        print()
        print("    from config import settings")
        print()
    else:
        print("✅ Import already present")
        print()

    # Step 2: Replace os.getenv() calls
    print("=" * 80)
    print("STEP 2: REPLACE os.getenv() CALLS")
    print("=" * 80)
    print()

    # Group by variable name
    var_groups: Dict[str, List[Tuple[str, str, int]]] = {}
    for full_match, var_name, default, line_num in getenv_calls:
        if var_name not in var_groups:
            var_groups[var_name] = []
        var_groups[var_name].append((full_match, default, line_num))

    for var_name in sorted(var_groups.keys()):
        occurrences = var_groups[var_name]
        suggestion = generate_migration_suggestion(var_name, occurrences[0][1])

        print(f"Variable: {var_name}")
        print(f"  Occurrences: {len(occurrences)}")
        print(f"  Suggestion: {suggestion}")
        print()

        for full_match, default, line_num in occurrences:
            print(f"  Line {line_num}:")
            print(f"    ❌ OLD: {full_match}")
            print(f"    ✅ NEW: {suggestion}")
            if default and default != "":
                print(
                    f"         Note: Default '{default}' should be in config/settings.py"
                )
            print()

    # Step 3: Type conversions
    print("=" * 80)
    print("STEP 3: REMOVE TYPE CONVERSIONS")
    print("=" * 80)
    print()

    type_conversions = analyze_type_conversions(content)
    if type_conversions:
        print("These type conversions can be removed (already handled by Pydantic):")
        print()
        for pattern, suggestion, line_num in type_conversions:
            print(f"  Line {line_num}:")
            print(f"    ❌ OLD: {pattern}")
            print(f"    ✅ NEW: {suggestion}")
            print()
    else:
        print("✅ No unnecessary type conversions found")
        print()

    # Step 4: Verification
    print("=" * 80)
    print("STEP 4: VERIFY AFTER MIGRATION")
    print("=" * 80)
    print()
    print("Run these commands to verify:")
    print()
    print(f"  # Check no os.getenv() calls remain")
    print(f"  grep 'os\\.getenv' {filepath}")
    print()
    print(f"  # Check settings import exists")
    print(f"  grep 'from config import settings' {filepath}")
    print()
    print(f"  # Test file runs without errors")
    print(f"  python3 {filepath}")
    print()

    # Step 5: TODO items
    print("=" * 80)
    print("STEP 5: VERIFY CONFIG VARIABLES EXIST")
    print("=" * 80)
    print()
    print("Ensure these variables are defined in config/settings.py:")
    print()

    missing_vars = []
    for var_name in sorted(var_groups.keys()):
        if var_name not in ENV_VAR_MAPPING:
            missing_vars.append(var_name)
            print(f"  ❓ {var_name} (may need to be added)")
        else:
            print(f"  ✅ {var_name} (already mapped)")

    if missing_vars:
        print()
        print("For variables marked ❓, add them to config/settings.py:")
        print()
        for var_name in missing_vars:
            setting_name = var_name.lower()
            print(
                f"  {setting_name}: str = '{var_groups[var_name][0][1] or 'default_value'}'"
            )
        print()

    print()
    print("=" * 80)
    print("Full documentation: config/README.md")
    print("Migration guide: CONFIG_MIGRATION_AUDIT.md")
    print("=" * 80)


if __name__ == "__main__":
    main()
