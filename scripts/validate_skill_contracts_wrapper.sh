#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Wrapper: delegates to the canonical validator in onex_change_control.
# CI checks out a sparse onex_change_control clone at that same relative
# path; local dev resolves the sibling clone via $OMNI_HOME.
# [OMN-6193 / OMN-14655]
#
# OMN-14655: fails loud (exit 1) when the sibling script cannot be resolved
# instead of silently skipping -- a skipped gate must be indistinguishable
# from a failing gate (CLAUDE.md Rule #8, fail-fast on missing env). The
# prior hardcoded /Volumes/PRO-G40 fallback violated CLAUDE.md Rule #6
# (no hardcoded absolute paths) and only ever resolved on one machine.
set -euo pipefail

SCRIPT="onex_change_control/scripts/validation/validate_skill_contracts.py"
if [[ ! -f "$SCRIPT" ]]; then
  : "${OMNI_HOME:?OMNI_HOME must be set to the omni_home registry root (contains onex_change_control/) so skill-contract-validation can resolve its canonical script}"
  SCRIPT="$OMNI_HOME/onex_change_control/scripts/validation/validate_skill_contracts.py"
fi
if [[ ! -f "$SCRIPT" ]]; then
  echo "ERROR: skill-contract-validation: validate_skill_contracts.py unresolved." >&2
  echo "  Checked: onex_change_control/scripts/validation/validate_skill_contracts.py (sparse checkout)" >&2
  echo "  Checked: \$OMNI_HOME/onex_change_control/scripts/validation/validate_skill_contracts.py" >&2
  echo "  Set OMNI_HOME so \$OMNI_HOME/onex_change_control is on the path." >&2
  exit 1
fi
exec python3 "$SCRIPT" --skills-root plugins/onex/skills "$@"
