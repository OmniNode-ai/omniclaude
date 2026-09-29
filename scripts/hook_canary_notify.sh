#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# hook_canary_notify.sh TITLE MESSAGE (OMN-20109)
#
# The hook canary's operator notifier. Two channels through the existing alert
# path, not a new one: the outcome-checked Slack sender every hook alert already
# uses (plugins/onex/hooks/scripts/alert-channel.sh, OMN-15600), and, on a host
# with a console, a local notification banner.
#
# Exit 0 means the SLACK message was delivered. A local banner alone is not
# delivery: the operator ruled on 2026-09-29 that an alarm which only prints
# where nobody is looking is worse than a failure, and the launchd and cron
# runtimes carry no Slack credential in their environment (OMN-20109). The
# credential is resolved by alert_channel_alarm (environment first, then a read
# of the operator env file), and one that cannot be resolved is a recorded
# delivery failure. Exit 1 says Slack did not carry the alarm even when the
# banner fired; the canary then reports the alarm undelivered and retries next
# cycle. It never exits 0 for a channel that was merely "not configured".
set -uo pipefail

title="${1:?usage: hook_canary_notify.sh TITLE MESSAGE}"
message="${2:?usage: hook_canary_notify.sh TITLE MESSAGE}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

slack_rc=1

# shellcheck disable=SC1091
source "${here}/../plugins/onex/hooks/scripts/alert-channel.sh"
if alert_channel_alarm "hook_canary" "${title}: ${message}"; then
  slack_rc=0
fi

if [[ -n "${ONEX_ALERT_LOCAL_NOTIFY_CMD:-}" ]]; then
  # The same override alert-channel.sh honors, so a test never raises a banner.
  "${ONEX_ALERT_LOCAL_NOTIFY_CMD}" "${title}: ${message}" >/dev/null 2>&1 || true
elif [[ -x /usr/bin/osascript ]]; then
  /usr/bin/osascript -e 'on run argv' \
    -e 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Basso"' \
    -e 'end run' "${title}" "${message}" >/dev/null 2>&1 || true
elif command -v notify-send >/dev/null 2>&1; then
  notify-send "${title}" "${message}" >/dev/null 2>&1 || true
fi

if [[ "${slack_rc}" -ne 0 ]]; then
  echo "hook_canary_notify: Slack did not carry the alarm: ${title}" >&2
fi
exit "${slack_rc}"
