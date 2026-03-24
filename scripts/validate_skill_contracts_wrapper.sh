#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Wrapper: delegates to canonical validator in onex_change_control.
# CI uses sparse-checkout; local dev uses omni_home path.
# [OMN-6193]

SCRIPT="onex_change_control/scripts/validation/validate_skill_contracts.py"
if [ ! -f "$SCRIPT" ]; then
  SCRIPT="/Volumes/PRO-G40/Code/omni_home/onex_change_control/scripts/validation/validate_skill_contracts.py"  # local-path-ok
fi
if [ ! -f "$SCRIPT" ]; then
  echo "WARN: validate_skill_contracts.py not found, skipping" >&2
  exit 0  # non-blocking in local dev if path unavailable
fi
exec python3 "$SCRIPT" --skills-root plugins/onex/skills "$@"
