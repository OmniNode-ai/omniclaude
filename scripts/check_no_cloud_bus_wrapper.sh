#!/usr/bin/env bash
OMNI_HOME="${OMNI_HOME:-${HOME}/Code/omni_home}"
if [[ ! -f "$OMNI_HOME/scripts/check_no_cloud_bus.sh" ]]; then
  echo "SKIP: check_no_cloud_bus.sh not found at OMNI_HOME=$OMNI_HOME" >&2
  exit 0
fi
exec bash "$OMNI_HOME/scripts/check_no_cloud_bus.sh" .
