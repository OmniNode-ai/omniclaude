#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =============================================================================
# Alert channel delivery — outcome-checked, fail-loud (OMN-15600)
# =============================================================================
# Single sender shared by every shell alert path in the plugin. Replaces the
# three duplicated, fire-and-forget `curl ... >/dev/null 2>&1` blocks that lived
# in common.sh (slack_notify, notify_hook_degraded) and error-guard.sh.
#
# Why this file exists
# --------------------
# Those three call sites branched only on whether SLACK_WEBHOOK_URL was
# non-empty and discarded the HTTP outcome. The webhook in the canonical env
# had been revoked (Slack answers HTTP 404 / `no_service`), so every hook-health
# alert delivered to nothing while looking identical to a healthy send. The only
# thing that would have reported broken alerting was the alerting.
#
# Three states, not two
# ---------------------
#   0  delivered            — a channel accepted the message
#   1  configured but DEAD   — a channel was configured and none delivered.
#                              Recorded on a durable log AND raised as a local
#                              notification on this machine.
#   2  not configured        — nothing to send through; silent no-op.
# State 1 is the state that did not exist before OMN-15600.
#
# Channel: Slack Web API with a bot token (webhook-independent). The incoming
# webhook (SLACK_WEBHOOK_URL) was retired — it was revoked and never
# regenerated, `#omninode-notifications` already receives live traffic via the
# bot token, and the operator directive is no new Slack app/webhook. Do not
# reintroduce a SLACK_WEBHOOK_URL read here.
#
# Dependencies: curl only. No Python, no jq, no common.sh — error-guard.sh
# sources this before common.sh and some hooks never source common.sh at all.
#
# Usage:
#   source "$(dirname "${BASH_SOURCE[0]}")/alert-channel.sh"
#   alert_channel_send "daemon_startup" "Emit daemon failed to start"
# =============================================================================

# Idempotent source guard — several hooks source both error-guard.sh and
# common.sh, each of which pulls this in.
if [[ -n "${_ONEX_ALERT_CHANNEL_SOURCED:-}" ]]; then
    return 0 2>/dev/null || true
fi
_ONEX_ALERT_CHANNEL_SOURCED=1

_ALERT_CHANNEL_HOST="${HOSTNAME:-$(hostname -s 2>/dev/null || echo unknown)}"

# -----------------------------------------------------------------------------
# Durable failure log
# -----------------------------------------------------------------------------
# Default lives beside the canonical env file so an operator finds it in the
# place they already look. ONEX_ALERT_DELIVERY_LOG overrides it.
alert_channel_failure_log() {
    if [[ -n "${ONEX_ALERT_DELIVERY_LOG:-}" ]]; then
        printf '%s' "${ONEX_ALERT_DELIVERY_LOG}"
    else
        printf '%s' "${HOME}/.omnibase/alert_delivery_failures.log"
    fi
}

# -----------------------------------------------------------------------------
# Local (on-this-machine) fallback notification
# -----------------------------------------------------------------------------
# Mirrors the pattern proven by the Steel battery notifier: a durable log alone
# is not a notification — somebody has to be told at the console. Resolution
# order: explicit override, macOS osascript, Linux notify-send.
alert_channel_local_notifier_cmd() {
    if [[ -n "${ONEX_ALERT_LOCAL_NOTIFY_CMD:-}" ]]; then
        printf '%s' "${ONEX_ALERT_LOCAL_NOTIFY_CMD}"
        return 0
    fi
    if [[ -x /usr/bin/osascript ]]; then
        printf '%s' /usr/bin/osascript
        return 0
    fi
    if command -v notify-send >/dev/null 2>&1; then
        command -v notify-send
        return 0
    fi
    return 1
}

alert_channel_notify_local() {
    local summary="$1"
    local cmd
    cmd="$(alert_channel_local_notifier_cmd)" || return 1
    [[ -n "$cmd" ]] || return 1

    case "$cmd" in
        */osascript)
            # AppleScript string literals: escape backslashes first, then quotes.
            local esc
            esc=$(printf '%s' "$summary" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
            "$cmd" -e "display notification \"${esc}\" with title \"OmniClaude alerting BROKEN\" subtitle \"alert delivery failed\" sound name \"Sosumi\"" \
                >/dev/null 2>&1 || return 1
            ;;
        */notify-send)
            "$cmd" "OmniClaude alerting BROKEN" "$summary" >/dev/null 2>&1 || return 1
            ;;
        *)
            "$cmd" "$summary" >/dev/null 2>&1 || return 1
            ;;
    esac
    return 0
}

# Record a delivery failure loudly: durable log line + local notification.
# Never returns non-zero — reporting a broken channel must not break a hook.
#
# Usage: alert_channel_record_failure <category> <detail>
alert_channel_record_failure() {
    local category="$1"
    local detail="$2"
    local log_file stamp
    log_file="$(alert_channel_failure_log)"
    mkdir -p "$(dirname "$log_file")" 2>/dev/null || true
    stamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "unknown")"

    printf '%s [alert-channel][%s] DELIVERY FAILED category=%s %s\n' \
        "$stamp" "$_ALERT_CHANNEL_HOST" "$category" "$detail" \
        >> "$log_file" 2>/dev/null || true

    # Rate-limit the console banner so a persistently dead channel does not
    # raise one on every hook invocation. The log line above is never suppressed.
    local rate_dir="${ONEX_ALERT_LOCAL_NOTIFY_RATE_DIR:-${TMPDIR:-/tmp}/omniclaude-alert-channel}"
    mkdir -p "$rate_dir" 2>/dev/null || true
    local rate_file="${rate_dir}/local-notify.last"
    local window="${ONEX_ALERT_LOCAL_NOTIFY_WINDOW_SECONDS:-900}"
    local now
    now=$(date -u +%s 2>/dev/null) || now=0

    if [[ -f "$rate_file" ]]; then
        local last_sent
        last_sent=$(cat "$rate_file" 2>/dev/null) || last_sent=0
        [[ "$last_sent" =~ ^[0-9]+$ ]] || last_sent=0
        if (( now - last_sent < window )); then
            printf '%s   local-notify: SUPPRESSED (within %ss window)\n' \
                "$stamp" "$window" >> "$log_file" 2>/dev/null || true
            return 0
        fi
    fi
    printf '%s' "$now" > "$rate_file" 2>/dev/null || true

    if alert_channel_notify_local "Slack alert delivery failed (${category}) on ${_ALERT_CHANNEL_HOST}. See ${log_file}"; then
        printf '%s   local-notify: OK\n' "$stamp" >> "$log_file" 2>/dev/null || true
    else
        printf '%s   local-notify: FAILED (no local notifier available)\n' \
            "$stamp" >> "$log_file" 2>/dev/null || true
    fi
    return 0
}

# JSON-escape a message body: backslashes first, then quotes, then control chars.
alert_channel_json_escape() {
    printf '%s' "$1" \
        | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' \
        | tr '\n' ' ' | tr '\r' ' ' | tr '\t' ' '
}

# Extract Slack's `"error":"..."` field from a Web API response body, if present.
_alert_channel_slack_error() {
    printf '%s' "$1" \
        | sed -n 's/.*"error"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        | head -1
}

# -----------------------------------------------------------------------------
# alert_channel_send <category> <text>
# -----------------------------------------------------------------------------
# Returns 0 delivered / 1 configured-but-dead / 2 not configured.
# Never prints a credential: the webhook URL is passed via --url (kept out of
# `ps`) and only HTTP status codes and Slack error slugs reach the log.
alert_channel_send() {
    local category="$1"
    local text="$2"
    local bot_token="${SLACK_BOT_TOKEN:-}"
    local channel_id="${SLACK_CHANNEL_ID:-}"
    local connect_timeout="${ONEX_ALERT_CURL_CONNECT_TIMEOUT:-1}"
    local max_time="${ONEX_ALERT_CURL_MAX_TIME:-2}"

    # Nothing configured at all — genuinely nothing to report.
    if [[ -z "$bot_token" || -z "$channel_id" ]]; then
        return 2
    fi

    if ! command -v curl >/dev/null 2>&1; then
        alert_channel_record_failure "$category" "curl unavailable on PATH"
        return 1
    fi

    local escaped detail=""
    escaped="$(alert_channel_json_escape "$text")"

    # --- Slack Web API via bot token — the sole delivery channel --------------
    # Webhook-independent: survives a webhook revocation, which is the exact
    # failure OMN-15600 was filed for. SLACK_WEBHOOK_URL is retired; there is
    # no fallback channel.
    if [[ -n "$bot_token" && -n "$channel_id" ]]; then
        local api_base resp code body compact
        api_base="${SLACK_API_BASE_URL:-https://slack.com/api}"
        resp=$(curl -sS --connect-timeout "$connect_timeout" --max-time "$max_time" \
            -o - -w $'\n%{http_code}' \
            -H "Authorization: Bearer ${bot_token}" \
            -H 'Content-Type: application/json; charset=utf-8' \
            -d "{\"channel\": \"${channel_id}\", \"text\": \"${escaped}\"}" \
            --url "${api_base}/chat.postMessage" 2>/dev/null) || resp=""
        code="${resp##*$'\n'}"
        body="${resp%$'\n'*}"
        compact="${body// /}"
        # Slack answers HTTP 200 with {"ok":false,"error":"..."} for a revoked
        # token — a status-code-only check would score that as delivered.
        if [[ "$code" == "200" && "$compact" == *'"ok":true'* ]]; then
            return 0
        fi
        local slack_err
        slack_err="$(_alert_channel_slack_error "$body")"
        detail="${detail}chat.postMessage=HTTP_${code:-000}${slack_err:+ slack_error=${slack_err}}; "
    fi

    alert_channel_record_failure "$category" "${detail}message=${text:0:160}"
    return 1
}
