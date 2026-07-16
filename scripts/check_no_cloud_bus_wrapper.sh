#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Wrapper: delegates to the canonical cloud-bus guard owned by omnibase_infra
# (scripts/validation/check_no_cloud_bus.sh). OMN-14655: fails loud (exit 1)
# when the sibling script cannot be resolved instead of silently skipping --
# a skipped gate must be indistinguishable from a failing gate (CLAUDE.md
# Rule #8, fail-fast on missing env). The prior default
# (${HOME}/Code/omni_home/scripts/check_no_cloud_bus.sh) never resolved: the
# script has always lived under omnibase_infra/scripts/validation/, not
# directly under the registry root's scripts/.
set -euo pipefail

: "${OMNI_HOME:?OMNI_HOME must be set to the omni_home registry root (contains omnibase_infra/) so no-cloud-bus can resolve its canonical script}"

SCRIPT="$OMNI_HOME/omnibase_infra/scripts/validation/check_no_cloud_bus.sh"
if [[ ! -f "$SCRIPT" ]]; then
  echo "ERROR: no-cloud-bus: canonical script not found at $SCRIPT" >&2
  echo "  Ensure \$OMNI_HOME/omnibase_infra is a valid checkout (bash omnibase_infra/scripts/pull-all.sh)." >&2
  exit 1
fi
exec bash "$SCRIPT" .
