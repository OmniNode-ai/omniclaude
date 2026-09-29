#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# hook_canary_notify.sh TITLE MESSAGE (OMN-20109)
#
# The hook canary's operator notifier. Two channels through the existing alert
# path, not a new one: the outcome-checked Slack sender every hook alert already
# uses (plugins/onex/hooks/scripts/alert-channel.sh, OMN-15600), and, on a host
# with a console, a local notification banner. Exit 0 only when at least one
# channel actually carried the alarm; exit 1 says nothing did, and the canary
# then retries next cycle and reports UNDELIVERED. It never exits 0 for a
# channel that was merely "not configured".
set -uo pipefail

title="${1:?usage: hook_canary_notify.sh TITLE MESSAGE}"
message="${2:?usage: hook_canary_notify.sh TITLE MESSAGE}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${HOME}/.omnibase/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env" 2>/dev/null || true
  set +a
fi

delivered=1

# shellcheck disable=SC1091
source "${here}/../plugins/onex/hooks/scripts/alert-channel.sh"
if alert_channel_send "hook_canary" "${title}: ${message}"; then
  delivered=0
fi

if [[ -x /usr/bin/osascript ]]; then
  if /usr/bin/osascript -e 'on run argv' \
    -e 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Basso"' \
    -e 'end run' "${title}" "${message}" >/dev/null 2>&1; then
    delivered=0
  fi
elif command -v notify-send >/dev/null 2>&1; then
  if notify-send "${title}" "${message}" >/dev/null 2>&1; then
    delivered=0
  fi
fi

if [[ "${delivered}" -ne 0 ]]; then
  echo "hook_canary_notify: no channel carried the alarm: ${title}" >&2
fi
exit "${delivered}"
