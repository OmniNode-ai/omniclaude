#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# QPM Label Setup - Create qpm-accelerate label on all queue-enabled repos
set -euo pipefail

REPOS=(
    OmniNode-ai/omnibase_core
    OmniNode-ai/omnibase_infra
    OmniNode-ai/omniclaude
    OmniNode-ai/omniintelligence
    OmniNode-ai/omnimemory
    OmniNode-ai/omnidash
)

failed=0
for repo in "${REPOS[@]}"; do
    echo "Creating qpm-accelerate label on $repo..."
    if ! gh label create "qpm-accelerate" \
        --repo "$repo" \
        --description "QPM: promote this PR ahead in merge queue" \
        --color "0E8A16" \
        --force; then
        echo "  failed to create/update label on $repo" >&2
        failed=$((failed + 1))
    fi
done

if [ "$failed" -gt 0 ]; then
    echo "Completed with $failed failure(s)." >&2
    exit 1
fi

echo "Done. Verify: gh label list --repo OmniNode-ai/omnibase_core | grep qpm"
