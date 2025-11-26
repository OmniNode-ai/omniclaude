#!/bin/bash
# Add py.typed markers to all package directories

set -e

# Ensure we run from the project root (where this script lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

count_added=0
count_existing=0

# Use process substitution to avoid subshell scope issues with variable updates
# The while loop reads directly from the process substitution, keeping variables in main shell
# This pattern works on bash 3.2+ (including macOS default bash)
while IFS= read -r init_file; do
  # Skip empty entries (handles case where find returns nothing)
  [[ -z "$init_file" ]] && continue

  dir=$(dirname "$init_file")
  if [ ! -f "$dir/py.typed" ]; then
    touch "$dir/py.typed"
    echo "Added py.typed to $dir"
    count_added=$((count_added + 1))
  else
    echo "  Already exists: $dir/py.typed"
    count_existing=$((count_existing + 1))
  fi
done < <(find agents/ claude_hooks/ config/ services/ -type f -name "__init__.py" -not -path "*/.*")

echo ""
echo "Summary:"
echo "  py.typed markers added: $count_added"
echo "  Already existing: $count_existing"
echo ""
echo "Total py.typed markers:"
find agents/ claude_hooks/ config/ services/ -name "py.typed" | wc -l
