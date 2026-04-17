#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

ONEX_REGISTRY_ROOT="${ONEX_REGISTRY_ROOT:-${HOME}/Code/omni_home}"
if [[ ! -f "$ONEX_REGISTRY_ROOT/scripts/check_no_cloud_bus.sh" ]]; then
  echo "SKIP: check_no_cloud_bus.sh not found at ONEX_REGISTRY_ROOT=$ONEX_REGISTRY_ROOT" >&2
  exit 0
fi
exec bash "$ONEX_REGISTRY_ROOT/scripts/check_no_cloud_bus.sh" .
