#!/Users/jonah/Library/Caches/pypoetry/virtualenvs/omniclaude-agents-kzVi5DqF-py3.12/bin/python
"""Minimal test hook"""
import sys
from pathlib import Path

# Add project root to path - MUST use .resolve() to follow symlinks!
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

print(f"project_root: {project_root}", file=sys.stderr)
print(f"sys.path[0]: {sys.path[0]}", file=sys.stderr)

# Try the import
try:
    from claude_hooks.lib.memory_client import get_memory_client
    print("✅ Import successful!", file=sys.stderr)
    print("OK")
except Exception as e:
    print(f"❌ Import failed: {e}", file=sys.stderr)
    sys.exit(1)
