#!/usr/bin/env bash
# Block silent inprocess fallback patterns in skill code (OMN-10723).
# Skills must dispatch through the event bus, not bypass it with direct handler calls.
set -euo pipefail

if grep -rn '_inprocess_fallback\|InProcessDelegationRunner\|inprocess_runner' \
    plugins/onex/skills/ --include="*.py" | grep -v '# fallback-removed'; then
    echo "ERROR: Silent inprocess fallback detected in skill code (OMN-10723)"
    echo "Skills must dispatch through the event bus, not bypass it with direct handler calls."
    exit 1
fi
