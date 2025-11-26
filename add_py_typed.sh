#!/bin/bash
# Add py.typed markers to all package directories

set -e

# Ensure we run from the project root (where this script lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

count_added=0
count_existing=0

# Use mapfile to collect all __init__.py files into an array
# This avoids potential subshell scope issues with variable updates
mapfile -t init_files < <(find agents/ claude_hooks/ config/ services/ -type f -name "__init__.py" -not -path "*/.*")

for init_file in "${init_files[@]}"; do
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
done

echo ""
echo "Summary:"
echo "  py.typed markers added: $count_added"
echo "  Already existing: $count_existing"
echo ""
echo "Total py.typed markers:"
find agents/ claude_hooks/ config/ services/ -name "py.typed" | wc -l
