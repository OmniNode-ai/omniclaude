#!/usr/bin/env bash
# Block silent inprocess fallback patterns in skill code (OMN-10723).
# Skills must dispatch through the event bus, not bypass it with direct handler calls.
set -euo pipefail

paths=("$@")
if [ "${#paths[@]}" -eq 0 ]; then
    paths=(plugins/onex/skills/)
fi
for path in "${paths[@]}"; do
    if [ "$path" = ".pre-commit-config.yaml" ] || [ "$path" = "${BASH_SOURCE[0]}" ]; then
        paths=(plugins/onex/skills/)
        break
    fi
done

if grep -rnH '_inprocess_fallback\|InProcessDelegationRunner\|inprocess_runner' \
    --include="*.py" "${paths[@]}" 2>/dev/null | grep -v '# fallback-removed'; then
    echo "ERROR: Silent inprocess fallback detected in skill code (OMN-10723)"
    echo "Skills must dispatch through the event bus, not bypass it with direct handler calls."
    exit 1
fi
