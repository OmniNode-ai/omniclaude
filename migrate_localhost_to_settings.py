#!/usr/bin/env python3
"""
Automated migration script to replace hardcoded localhost:8053 with settings.archon_intelligence_url
"""

import re
from pathlib import Path

# Files to migrate
FILES_TO_MIGRATE = [
    "claude_hooks/debug_utils.py",
    "claude_hooks/error_handling.py",
    "claude_hooks/pattern_tracker.py",
    "claude_hooks/performance_test.py",
    "claude_hooks/test_pattern_tracking.py",
    "claude_hooks/test_phase4_connectivity.py",
    "claude_hooks/lib/pattern_tracker_sync.py",
    "claude_hooks/lib/test_resilience.py",
    "claude_hooks/tests/test_live_integration.py",
    "claude_hooks/tests/test_phase4_integration.py",
]


def migrate_file(file_path: Path) -> tuple[bool, str]:
    """
    Migrate a single file by:
    1. Adding 'from config import settings' import if not present
    2. Replacing localhost:8053 with settings.archon_intelligence_url

    Returns: (success, message)
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    content = file_path.read_text()
    original_content = content
    modified = False

    # Check if settings import already exists
    has_settings_import = "from config import settings" in content

    # Add settings import if not present
    if not has_settings_import and "localhost:8053" in content:
        # Find the imports section and add settings import
        import_patterns = [
            (r"(import \w+\s*\n)", r"\1\nfrom config import settings\n"),
            (r"(from [\w.]+ import [\w, ]+\s*\n)", r"\1from config import settings\n"),
        ]

        for pattern, replacement in import_patterns:
            if re.search(pattern, content):
                content = re.sub(pattern, replacement, content, count=1)
                modified = True
                break

        if not modified:
            # If no imports found, add at the beginning after docstring
            docstring_end = 0
            if content.startswith('"""') or content.startswith("'''"):
                quote = '"""' if content.startswith('"""') else "'''"
                docstring_end = content.find(quote, 3) + 3
                if docstring_end > 3:
                    content = (
                        content[:docstring_end]
                        + "\n\nfrom config import settings\n"
                        + content[docstring_end:]
                    )
                    modified = True

    # Replace localhost:8053 patterns
    replacements = [
        # Pattern 1: base_url="http://localhost:8053" in function calls
        (
            r'base_url="http://localhost:8053"',
            "base_url=str(settings.archon_intelligence_url)",
        ),
        # Pattern 2: base_url: str = "http://localhost:8053" in function signatures
        (r'base_url:\s*str\s*=\s*"http://localhost:8053"', "base_url: str = None"),
        # Pattern 3: url = "http://localhost:8053"
        (
            r'(\w+)\s*=\s*"http://localhost:8053"',
            r"\1 = str(settings.archon_intelligence_url)",
        ),
        # Pattern 4: "http://localhost:8053" standalone
        (r'"http://localhost:8053"', "str(settings.archon_intelligence_url)"),
    ]

    for pattern, replacement in replacements:
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            modified = True

    if modified and content != original_content:
        # Write back to file
        file_path.write_text(content)
        return True, f"✅ Migrated {file_path}"
    elif "localhost:8053" in content:
        return False, f"⚠️  Could not migrate {file_path} (manual review needed)"
    else:
        return True, f"✓ Already migrated {file_path}"


def main():
    """Run migration on all target files"""
    print("=== localhost:8053 → settings.archon_intelligence_url Migration ===\n")

    root = Path(__file__).parent.resolve()
    success_count = 0
    fail_count = 0

    for file_rel_path in FILES_TO_MIGRATE:
        file_path = root / file_rel_path
        success, message = migrate_file(file_path)
        print(message)

        if success:
            success_count += 1
        else:
            fail_count += 1

    print(f"\n=== Summary ===")
    print(f"✅ Successful: {success_count}")
    print(f"❌ Failed: {fail_count}")
    print(f"📊 Total: {success_count + fail_count}")

    if fail_count > 0:
        print("\n⚠️  Some files need manual review!")


if __name__ == "__main__":
    main()
