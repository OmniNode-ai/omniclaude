#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-13098: wrapper for the skill-dispatch receipt-mode gate.
#
# Runs omnibase_core.validators.skill_dispatch_receipt_mode against the
# plugins/onex/skills tree, tolerating the not-yet-migrated skills listed in
# .onex_ratchets/skill_receipt_mode_allowlist.yaml. The gate FAILS if the
# allowlist grows, if a listed skill is migrated (stale entry) or removed, or
# if a new skill ships a dispatch command without receipt mode.
#
# Fails loud (exit 1) if the validator is not importable — a missing validator
# is a configuration error, not a reason to silently pass (matches the
# check-local-paths wrapper, OMN-9043).
set -euo pipefail

SKILLS_ROOT="plugins/onex/skills"
ALLOWLIST=".onex_ratchets/skill_receipt_mode_allowlist.yaml"

if ! uv run python -c "import omnibase_core.validators.skill_dispatch_receipt_mode" 2>/dev/null; then
    echo "ERROR: skill-dispatch-receipt-mode: omnibase_core.validators.skill_dispatch_receipt_mode is not importable." >&2
    echo "  Run 'uv sync' to install omnibase_core, or check that omnibase_core is in your dependencies." >&2
    exit 1
fi

exec uv run python -m omnibase_core.validators.skill_dispatch_receipt_mode \
    --skills-root "$SKILLS_ROOT" \
    --allowlist "$ALLOWLIST"
