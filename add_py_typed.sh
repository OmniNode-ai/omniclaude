#!/bin/bash
# Add py.typed markers to all package directories

set -e

count_added=0
count_existing=0

while IFS= read -r init_file; do
  dir=$(dirname "$init_file")
  if [ ! -f "$dir/py.typed" ]; then
    touch "$dir/py.typed"
    echo "✓ Added py.typed to $dir"
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
