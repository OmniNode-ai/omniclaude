#!/bin/bash
# Add py.typed markers to all package directories

set -e

# Ensure we run from the project root (where this script lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# All directories containing Python packages (discovered via find -name "__init__.py")
# Excludes: venv, .venv, htmlcov, __pycache__, and hidden directories
PACKAGE_DIRS=(
  "agents"
  "app"
  "claude_hooks"
  "claude-artifacts"
  "cli"
  "config"
  "generated_nodes"
  "omniclaude"
  "services"
  "shared_lib"
  "skills"
  "tests"
  "tools"
)

count_added=0
count_existing=0

# Build find arguments for existing directories only
find_args=()
for dir in "${PACKAGE_DIRS[@]}"; do
  if [ -d "$dir" ]; then
    find_args+=("$dir")
  fi
done

# Check if we have any directories to process
if [ ${#find_args[@]} -eq 0 ]; then
  echo "Error: No package directories found"
  exit 1
fi

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
done < <(find "${find_args[@]}" -type f -name "__init__.py" -not -path "*/.*" -not -path "*/__pycache__/*" 2>/dev/null)

# Calculate expected total from our counters
expected_total=$((count_added + count_existing))

# Count actual py.typed files (strip whitespace from wc output)
actual_total=$(find "${find_args[@]}" -name "py.typed" -not -path "*/.*" 2>/dev/null | wc -l | tr -d ' ')

echo ""
echo "Summary:"
echo "  py.typed markers added: $count_added"
echo "  Already existing: $count_existing"
echo "  Expected total: $expected_total"
echo "  Actual total: $actual_total"

# Validate counter accuracy
if [ "$expected_total" -ne "$actual_total" ]; then
  echo ""
  echo "WARNING: Counter mismatch detected!"
  echo "  This may indicate py.typed files in directories without __init__.py"
  echo "  or __init__.py files in unexpected locations."
  diff_count=$((actual_total - expected_total))
  if [ "$diff_count" -gt 0 ]; then
    echo "  Found $diff_count extra py.typed file(s)"
  else
    echo "  Missing $((-diff_count)) py.typed file(s)"
  fi
fi
