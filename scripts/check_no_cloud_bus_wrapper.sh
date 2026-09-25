#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Reject unsuppressed cloud-bus port references in selected tracked files.
set -euo pipefail

paths=("$@")
full_scan=0
if [ "${#paths[@]}" -eq 0 ]; then
  full_scan=1
fi
for path in "${paths[@]}"; do
  if [ "$path" = ".pre-commit-config.yaml" ] || [ "$path" = "${BASH_SOURCE[0]}" ]; then
    full_scan=1
    break
  fi
done

violations=0
if [ "$full_scan" -eq 1 ]; then
  while IFS=: read -r path line_num line_text; do
    [ -n "$path" ] || continue
    if printf '%s\n' "$line_text" | grep -qE '#\s*cloud-bus-ok\s+OMN-[0-9]+'; then
      continue
    fi
    echo "VIOLATION: $path:$line_num:$line_text"
    violations=$((violations + 1))
  done < <(git grep -n '29092' -- '*.py' '*.ts' '*.tsx' '*.js' '*.sh' '*.yml' '*.yaml' '*.toml' ':!scripts/check_no_cloud_bus_wrapper.sh' ':!docs/history/**' ':!docs/historical-planning/**' ':!docs/deep-dives/**' ':!docs/plans/**' ':!docs/archive/**' ':!docs/velocity-reports/**' ':!docs/reference/**' ':!docs/architecture/**' ':!*docker-compose.e2e*' 2>/dev/null || true)
else
  for path in "${paths[@]}"; do
    [ -f "$path" ] || continue
    case "$path" in
      CLAUDE.md|MEMORY.md|CHANGELOG.md|docs/history/*|docs/historical-planning/*|docs/deep-dives/*|docs/plans/*|docs/archive/*|docs/velocity-reports/*|docs/reference/*|docs/architecture/*|*check_no_cloud_bus*|*docker-compose.e2e*) continue ;;
    esac
    while IFS=: read -r line_num line_text; do
      if printf '%s\n' "$line_text" | grep -qE '#\s*cloud-bus-ok\s+OMN-[0-9]+'; then
        continue
      fi
      echo "VIOLATION: $path:$line_num:$line_text"
      violations=$((violations + 1))
    done < <(grep -n '29092' "$path" 2>/dev/null || true)
  done
fi

if [ "$violations" -gt 0 ]; then
  echo "Found $violations unsuppressed cloud bus (29092) reference(s)."
  echo "To suppress, add on the same line: # cloud-bus-ok OMN-XXXX"
  exit 1
fi
