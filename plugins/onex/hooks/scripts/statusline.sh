#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# ONEX Status Line - 4-line layout:
# Line 1: Model | tokens used/total | % used <fullused> | % remain <fullremain> | thinking: on/off
# Line 2: current: <progressbar> % | weekly: <progressbar> % | extra: <progressbar> $used/$limit
# Line 3: resets <time> | resets <datetime> | resets <date>
# Line 4: health + PR status (from background caches)

set -f  # disable globbing

input=$(cat)

if [ -z "$input" ]; then
    printf "Claude"
    exit 0
fi

# ANSI colors matching oh-my-posh theme
blue='\033[38;2;0;153;255m'
orange='\033[38;2;255;176;85m'
green='\033[38;2;0;160;0m'
cyan='\033[38;2;46;149;153m'
red='\033[38;2;255;85;85m'
yellow='\033[38;2;230;200;0m'
white='\033[38;2;220;220;220m'
dim='\033[2m'
reset='\033[0m'

# ===== Tool detection flags =====
HAS_GH=false
HAS_NC=false
HAS_JQ=false
HAS_TIMEOUT=false
command -v gh      >/dev/null 2>&1 && HAS_GH=true
command -v nc      >/dev/null 2>&1 && HAS_NC=true
command -v jq      >/dev/null 2>&1 && HAS_JQ=true
command -v timeout >/dev/null 2>&1 && HAS_TIMEOUT=true

# ===== Cache & lock constants =====
HEALTH_CACHE="/tmp/omniclaude-health-cache.json"
PR_CACHE="/tmp/omniclaude-pr-cache.json"
HEALTH_TTL=30    # seconds
PR_TTL=300       # 5 minutes
HEALTH_LOCK_DIR="/tmp/omniclaude-health.lock"
PR_LOCK_DIR="/tmp/omniclaude-pr.lock"

# 10 repos in the omni_home registry
OMNI_REPOS=(
    omniclaude
    omnibase_core
    omnibase_infra
    omnibase_spi
    omnidash
    omniintelligence
    omnimemory
    omninode_infra
    omniweb
    onex_change_control
)

# ===== check_cache(file, ttl) =====
# Reads cache file, checks freshness via mtime, validates JSON.
# Prints cache contents to stdout if fresh and valid; returns 0.
# Returns 1 if stale, missing, or invalid JSON.
check_cache() {
    local file="$1"
    local ttl="$2"

    [ -f "$file" ] || return 1

    local mtime now age
    mtime=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null)
    [ -z "$mtime" ] && return 1

    now=$(date +%s)
    age=$(( now - mtime ))
    [ "$age" -ge "$ttl" ] && return 1

    # Validate JSON
    if $HAS_JQ; then
        local data
        data=$(jq -e . "$file" 2>/dev/null) || return 1
        printf '%s' "$data"
        return 0
    else
        # Without jq, just return contents (best-effort)
        cat "$file" 2>/dev/null
        return 0
    fi
}

# ===== acquire_lock(dir) =====
# Atomic mkdir-based locking with stale PID detection.
# Returns 0 if lock acquired, 1 if another process holds it.
acquire_lock() {
    local lock_dir="$1"

    if mkdir "$lock_dir" 2>/dev/null; then
        echo $$ > "$lock_dir/pid"
        return 0
    fi

    # Check for stale lock (PID no longer running)
    if [ -f "$lock_dir/pid" ]; then
        local lock_pid
        lock_pid=$(cat "$lock_dir/pid" 2>/dev/null)
        if [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" 2>/dev/null; then
            # Stale lock -- remove and retry once
            rm -rf "$lock_dir"
            if mkdir "$lock_dir" 2>/dev/null; then
                echo $$ > "$lock_dir/pid"
                return 0
            fi
        fi
    fi

    return 1
}

# ===== release_lock(dir) =====
release_lock() {
    local lock_dir="$1"
    rm -rf "$lock_dir"
}

# ===== check_port(port) =====
# TCP port probe with timeout -> nc -> /dev/tcp fallback chain.
# Returns 0 if port is open, 1 otherwise.
check_port() {
    local port="$1"

    # Prefer: timeout + nc (most reliable)
    if $HAS_TIMEOUT && $HAS_NC; then
        timeout 1 nc -z 127.0.0.1 "$port" >/dev/null 2>&1
        return $?
    fi

    # Fallback: nc without timeout
    if $HAS_NC; then
        nc -z -w 1 127.0.0.1 "$port" >/dev/null 2>&1
        return $?
    fi

    # Last resort: bash /dev/tcp
    (echo >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1
    return $?
}

# ===== refresh_health_bg() =====
# Probes pg:5436, rp:19092, vk:16379, rt:8085, intel:8053, phx:6006 + BUS_ID.
# Writes /tmp/omniclaude-health-cache.json. Runs in background subshell.
refresh_health_bg() {
    (
        # EXIT trap for lock cleanup
        trap 'release_lock "$HEALTH_LOCK_DIR"' EXIT

        if ! acquire_lock "$HEALTH_LOCK_DIR"; then
            return 0
        fi

        local pg="" rp="" vk="" rt="" intel="" phx=""

        # Core infrastructure (expected to be running)
        check_port 5436  && pg="ok"    || pg="down"
        check_port 19092 && rp="ok"    || rp="down"
        check_port 16379 && vk="ok"    || vk="down"

        # Runtime services (absence is normal -- empty string when down)
        check_port 8085  && rt="ok"    || rt=""
        check_port 8053  && intel="ok" || intel=""
        check_port 6006  && phx="ok"   || phx=""

        # BUS_ID from environment (session-scoped, set by bus-cloud/bus-local)
        local bus_id="${BUS_ID:-local}"

        # Write JSON cache
        if $HAS_JQ; then
            jq -n \
                --arg pg "$pg" \
                --arg rp "$rp" \
                --arg vk "$vk" \
                --arg rt "$rt" \
                --arg intel "$intel" \
                --arg phx "$phx" \
                --arg bus "$bus_id" \
                --arg ts "$(date +%s)" \
                '{pg:$pg, rp:$rp, vk:$vk, rt:$rt, intel:$intel, phx:$phx, bus:$bus, ts:($ts|tonumber)}' \
                > "$HEALTH_CACHE.tmp" 2>/dev/null
        else
            # Fallback without jq
            printf '{"pg":"%s","rp":"%s","vk":"%s","rt":"%s","intel":"%s","phx":"%s","bus":"%s","ts":%s}\n' \
                "$pg" "$rp" "$vk" "$rt" "$intel" "$phx" "$bus_id" "$(date +%s)" \
                > "$HEALTH_CACHE.tmp" 2>/dev/null
        fi

        mv -f "$HEALTH_CACHE.tmp" "$HEALTH_CACHE" 2>/dev/null
    ) &
}

# ===== refresh_prs_bg() =====
# Queries gh pr list for 10 repos; writes /tmp/omniclaude-pr-cache.json.
# Stale-ok: if gh fails and cache exists, keep stale cache.
refresh_prs_bg() {
    $HAS_GH || return 0

    (
        # EXIT trap for lock cleanup
        trap 'release_lock "$PR_LOCK_DIR"' EXIT

        if ! acquire_lock "$PR_LOCK_DIR"; then
            return 0
        fi

        local all_prs="[]"
        local repo org="OmniNode-ai"

        for repo in "${OMNI_REPOS[@]}"; do
            local pr_json
            pr_json=$(gh pr list \
                --repo "$org/$repo" \
                --state open \
                --json number,title,author,headRefName,updatedAt,isDraft,reviewDecision \
                --limit 20 \
                2>/dev/null) || continue

            # Skip empty results
            [ -z "$pr_json" ] || [ "$pr_json" = "[]" ] && continue

            # Tag each PR with its repo name
            if $HAS_JQ; then
                pr_json=$(echo "$pr_json" | jq --arg repo "$repo" '[.[] | . + {repo: $repo}]' 2>/dev/null) || continue
                all_prs=$(echo "$all_prs" "$pr_json" | jq -s '.[0] + .[1]' 2>/dev/null) || continue
            fi
        done

        # Build final cache object
        local cache_obj
        if $HAS_JQ; then
            cache_obj=$(echo "$all_prs" | jq --arg ts "$(date +%s)" '{prs: ., ts: ($ts|tonumber)}' 2>/dev/null)
        else
            cache_obj="{\"prs\":$all_prs,\"ts\":$(date +%s)}"
        fi

        if [ -n "$cache_obj" ]; then
            echo "$cache_obj" > "$PR_CACHE.tmp" 2>/dev/null
            mv -f "$PR_CACHE.tmp" "$PR_CACHE" 2>/dev/null
        fi
        # Stale-ok: if we failed, existing cache file stays untouched
    ) &
}

# Format token counts (e.g., 50k / 200k)
format_tokens() {
    local num=$1
    if [ "$num" -ge 1000000 ]; then
        awk "BEGIN {printf \"%.1fm\", $num / 1000000}"
    elif [ "$num" -ge 1000 ]; then
        awk "BEGIN {printf \"%.0fk\", $num / 1000}"
    else
        printf "%d" "$num"
    fi
}

# Format number with commas (e.g., 134,938)
format_commas() {
    printf "%'d" "$1"
}

# Build a colored progress bar
# Usage: build_bar <pct> <width>
build_bar() {
    local pct=$1
    local width=$2
    [ "$pct" -lt 0 ] 2>/dev/null && pct=0
    [ "$pct" -gt 100 ] 2>/dev/null && pct=100

    local filled=$(( pct * width / 100 ))
    local empty=$(( width - filled ))

    # Color based on usage level
    local bar_color
    if [ "$pct" -ge 90 ]; then bar_color="$red"
    elif [ "$pct" -ge 70 ]; then bar_color="$yellow"
    elif [ "$pct" -ge 50 ]; then bar_color="$orange"
    else bar_color="$green"
    fi

    local filled_str="" empty_str=""
    for ((i=0; i<filled; i++)); do filled_str+="●"; done
    for ((i=0; i<empty; i++)); do empty_str+="○"; done

    printf "${bar_color}${filled_str}${dim}${empty_str}${reset}"
}

# ===== Extract data from JSON =====
model_name=$(echo "$input" | jq -r '.model.display_name // "Claude"')

# Context window
size=$(echo "$input" | jq -r '.context_window.context_window_size // 200000')
[ "$size" -eq 0 ] 2>/dev/null && size=200000

# Token usage
input_tokens=$(echo "$input" | jq -r '.context_window.current_usage.input_tokens // 0')
cache_create=$(echo "$input" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0')
cache_read=$(echo "$input" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0')
current=$(( input_tokens + cache_create + cache_read ))

used_tokens=$(format_tokens $current)
total_tokens=$(format_tokens $size)

if [ "$size" -gt 0 ]; then
    pct_used=$(( current * 100 / size ))
else
    pct_used=0
fi
pct_remain=$(( 100 - pct_used ))

used_comma=$(format_commas $current)
remain_comma=$(format_commas $(( size - current )))

# Check thinking status
thinking_on=false
settings_path="$HOME/.claude/settings.json"
if [ -f "$settings_path" ]; then
    thinking_val=$(jq -r '.alwaysThinkingEnabled // false' "$settings_path" 2>/dev/null)
    [ "$thinking_val" = "true" ] && thinking_on=true
fi

# ===== LINE 1: Model | tokens | % used | % remain | thinking =====
line1=""
line1+="${blue}${model_name}${reset}"
line1+=" ${dim}|${reset} "
line1+="${orange}${used_tokens} / ${total_tokens}${reset}"
line1+=" ${dim}|${reset} "
line1+="${green}${pct_used}% used ${orange}${used_comma}${reset}"
line1+=" ${dim}|${reset} "
line1+="${cyan}${pct_remain}% remain ${blue}${remain_comma}${reset}"
line1+=" ${dim}|${reset} "
line1+="thinking: "
if $thinking_on; then
    line1+="${orange}On${reset}"
else
    line1+="${dim}Off${reset}"
fi

# ===== Cross-platform OAuth token resolution =====
# Tries credential sources in order: env var -> macOS Keychain -> Linux creds file -> GNOME Keyring
get_oauth_token() {
    local token=""

    # 1. Explicit env var override
    if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
        echo "$CLAUDE_CODE_OAUTH_TOKEN"
        return 0
    fi

    # 2. macOS Keychain
    if command -v security >/dev/null 2>&1; then
        local blob
        blob=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null)
        if [ -n "$blob" ]; then
            token=$(echo "$blob" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
            if [ -n "$token" ] && [ "$token" != "null" ]; then
                echo "$token"
                return 0
            fi
        fi
    fi

    # 3. Linux credentials file
    local creds_file="${HOME}/.claude/.credentials.json"
    if [ -f "$creds_file" ]; then
        token=$(jq -r '.claudeAiOauth.accessToken // empty' "$creds_file" 2>/dev/null)
        if [ -n "$token" ] && [ "$token" != "null" ]; then
            echo "$token"
            return 0
        fi
    fi

    # 4. GNOME Keyring via secret-tool
    if command -v secret-tool >/dev/null 2>&1; then
        local blob
        blob=$(timeout 2 secret-tool lookup service "Claude Code-credentials" 2>/dev/null)
        if [ -n "$blob" ]; then
            token=$(echo "$blob" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
            if [ -n "$token" ] && [ "$token" != "null" ]; then
                echo "$token"
                return 0
            fi
        fi
    fi

    echo ""
}

# ===== LINE 2 & 3: Usage limits with progress bars (cached) =====
cache_file="/tmp/claude/statusline-usage-cache.json"
cache_max_age=60  # seconds between API calls
mkdir -p /tmp/claude

needs_refresh=true
usage_data=""

# Check cache
if [ -f "$cache_file" ]; then
    cache_mtime=$(stat -c %Y "$cache_file" 2>/dev/null || stat -f %m "$cache_file" 2>/dev/null)
    now=$(date +%s)
    cache_age=$(( now - cache_mtime ))
    if [ "$cache_age" -lt "$cache_max_age" ]; then
        needs_refresh=false
        usage_data=$(cat "$cache_file" 2>/dev/null)
    fi
fi

# Fetch fresh data if cache is stale
if $needs_refresh; then
    token=$(get_oauth_token)
    if [ -n "$token" ] && [ "$token" != "null" ]; then
        response=$(curl -s --max-time 5 \
            -H "Accept: application/json" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $token" \
            -H "anthropic-beta: oauth-2025-04-20" \
            -H "User-Agent: claude-code/2.1.34" \
            "https://api.anthropic.com/api/oauth/usage" 2>/dev/null)
        if [ -n "$response" ] && echo "$response" | jq . >/dev/null 2>&1; then
            usage_data="$response"
            echo "$response" > "$cache_file"
        fi
    fi
    # Fall back to stale cache
    if [ -z "$usage_data" ] && [ -f "$cache_file" ]; then
        usage_data=$(cat "$cache_file" 2>/dev/null)
    fi
fi

# Cross-platform ISO to epoch conversion
iso_to_epoch() {
    local iso_str="$1"

    # Try GNU date first (Linux)
    local epoch
    epoch=$(date -d "${iso_str}" +%s 2>/dev/null)
    if [ -n "$epoch" ]; then
        echo "$epoch"
        return 0
    fi

    # BSD date (macOS) - handle various ISO 8601 formats
    local stripped="${iso_str%%.*}"
    stripped="${stripped%%Z}"
    stripped="${stripped%%+*}"
    stripped="${stripped%%-[0-9][0-9]:[0-9][0-9]}"

    if [[ "$iso_str" == *"Z"* ]] || [[ "$iso_str" == *"+00:00"* ]] || [[ "$iso_str" == *"-00:00"* ]]; then
        epoch=$(env TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%S" "$stripped" +%s 2>/dev/null)
    else
        epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$stripped" +%s 2>/dev/null)
    fi

    if [ -n "$epoch" ]; then
        echo "$epoch"
        return 0
    fi

    return 1
}

# Format ISO reset time to compact local time
format_reset_time() {
    local iso_str="$1"
    local style="$2"
    [ -z "$iso_str" ] || [ "$iso_str" = "null" ] && return

    local epoch
    epoch=$(iso_to_epoch "$iso_str")
    [ -z "$epoch" ] && return

    case "$style" in
        time)
            date -j -r "$epoch" +"%l:%M%p" 2>/dev/null | sed 's/^ //' | tr '[:upper:]' '[:lower:]' || \
            date -d "@$epoch" +"%l:%M%P" 2>/dev/null | sed 's/^ //'
            ;;
        datetime)
            date -j -r "$epoch" +"%b %-d, %l:%M%p" 2>/dev/null | sed 's/  / /g; s/^ //' | tr '[:upper:]' '[:lower:]' || \
            date -d "@$epoch" +"%b %-d, %l:%M%P" 2>/dev/null | sed 's/  / /g; s/^ //'
            ;;
        *)
            date -j -r "$epoch" +"%b %-d" 2>/dev/null | tr '[:upper:]' '[:lower:]' || \
            date -d "@$epoch" +"%b %-d" 2>/dev/null
            ;;
    esac
}

# Pad column to fixed width (ignoring ANSI codes)
pad_column() {
    local text="$1"
    local visible_len=$2
    local col_width=$3
    local padding=$(( col_width - visible_len ))
    if [ "$padding" -gt 0 ]; then
        printf "%s%*s" "$text" "$padding" ""
    else
        printf "%s" "$text"
    fi
}

line2=""
line3=""
sep=" ${dim}|${reset} "

if [ -n "$usage_data" ] && echo "$usage_data" | jq -e . >/dev/null 2>&1; then
    bar_width=10
    col1w=23
    col2w=22

    # ---- 5-hour (current) ----
    five_hour_pct=$(echo "$usage_data" | jq -r '.five_hour.utilization // 0' | awk '{printf "%.0f", $1}')
    five_hour_reset_iso=$(echo "$usage_data" | jq -r '.five_hour.resets_at // empty')
    five_hour_reset=$(format_reset_time "$five_hour_reset_iso" "time")
    five_hour_bar=$(build_bar "$five_hour_pct" "$bar_width")

    col1_bar_vis_len=$(( 9 + bar_width + 1 + ${#five_hour_pct} + 1 ))
    col1_bar="${white}current:${reset} ${five_hour_bar} ${cyan}${five_hour_pct}%${reset}"
    col1_bar=$(pad_column "$col1_bar" "$col1_bar_vis_len" "$col1w")

    col1_reset_plain="resets ${five_hour_reset}"
    col1_reset="${white}resets ${five_hour_reset}${reset}"
    col1_reset=$(pad_column "$col1_reset" "${#col1_reset_plain}" "$col1w")

    # ---- 7-day (weekly) ----
    seven_day_pct=$(echo "$usage_data" | jq -r '.seven_day.utilization // 0' | awk '{printf "%.0f", $1}')
    seven_day_reset_iso=$(echo "$usage_data" | jq -r '.seven_day.resets_at // empty')
    seven_day_reset=$(format_reset_time "$seven_day_reset_iso" "datetime")
    seven_day_bar=$(build_bar "$seven_day_pct" "$bar_width")

    col2_bar_vis_len=$(( 8 + bar_width + 1 + ${#seven_day_pct} + 1 ))
    col2_bar="${white}weekly:${reset} ${seven_day_bar} ${cyan}${seven_day_pct}%${reset}"
    col2_bar=$(pad_column "$col2_bar" "$col2_bar_vis_len" "$col2w")

    col2_reset_plain="resets ${seven_day_reset}"
    col2_reset="${white}resets ${seven_day_reset}${reset}"
    col2_reset=$(pad_column "$col2_reset" "${#col2_reset_plain}" "$col2w")

    # ---- Extra usage ----
    col3_bar=""
    col3_reset=""
    extra_enabled=$(echo "$usage_data" | jq -r '.extra_usage.is_enabled // false')
    if [ "$extra_enabled" = "true" ]; then
        extra_pct=$(echo "$usage_data" | jq -r '.extra_usage.utilization // 0' | awk '{printf "%.0f", $1}')
        extra_used=$(echo "$usage_data" | jq -r '.extra_usage.used_credits // 0' | awk '{printf "%.2f", $1/100}')
        extra_limit=$(echo "$usage_data" | jq -r '.extra_usage.monthly_limit // 0' | awk '{printf "%.2f", $1/100}')
        extra_bar=$(build_bar "$extra_pct" "$bar_width")

        # Next month 1st for reset date (macOS compatible)
        extra_reset=$(date -v+1m -v1d +"%b %-d" | tr '[:upper:]' '[:lower:]')

        col3_bar="${white}extra:${reset} ${extra_bar} ${cyan}\${extra_used}/\${extra_limit}${reset}"
        col3_reset="${white}resets ${extra_reset}${reset}"
    fi

    # Assemble line 2: bars row
    line2="${col1_bar}${sep}${col2_bar}"
    [ -n "$col3_bar" ] && line2+="${sep}${col3_bar}"

    # Assemble line 3: resets row
    line3="${col1_reset}${sep}${col2_reset}"
    [ -n "$col3_reset" ] && line3+="${sep}${col3_reset}"
fi

# Output all lines
printf "%b" "$line1"
[ -n "$line2" ] && printf "\n%b" "$line2"
[ -n "$line3" ] && printf "\n%b" "$line3"

exit 0
