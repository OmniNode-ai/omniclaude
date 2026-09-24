#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Claude Code Provider Toggle Script
# Switches scripts/../settings.json's ANTHROPIC_* env block between whatever
# providers the OPERATOR has listed in their own ~/.omninode/config/claude-providers.json.
#
# OMN-19393, plan task E4 (knowledge-base-internal
# beta/plans/2026-09-23-remove-hardcoded-model-config.md). This script used to
# hold every provider's base URL, API-key env-var name and model ids as
# literals below. They now live ONLY in the user's own config file -- an
# EXAMPLE copy ships at examples/config-overlays/claude-providers.example.json
# and is never read by this script. The self-hoster copies it to the path
# below and edits it; every value this script uses is read from that file at
# run time. This script defines the SHAPE (which five settings.json keys a
# provider entry maps to), never any provider's identity.
#
# Usage: ./toggle-claude-provider.sh [<provider-key>|status|list]

set -e

SETTINGS_FILE="$HOME/.claude/settings.json"
BACKUP_FILE="$HOME/.claude/settings.json.backup"
CONFIG_FILE="$HOME/.omninode/config/claude-providers.json"
EXAMPLE_CONFIG_PATH="examples/config-overlays/claude-providers.example.json"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

show_usage() {
    echo -e "${BLUE}Usage:${NC}"
    echo "  $0 <provider>    - Switch to the named provider (a key under .providers in the config file)"
    echo "  $0 status        - Show the current provider"
    echo "  $0 list          - List every provider the config file defines"
    echo ""
    echo -e "${BLUE}Config file:${NC} ${CONFIG_FILE}"
    echo "  Copy ${EXAMPLE_CONFIG_PATH} there and edit it to add or change providers."
}

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is not installed${NC}"
    echo "Install with: brew install jq"
    exit 1
fi

# Check if settings file exists
if [ ! -f "$SETTINGS_FILE" ]; then
    echo -e "${RED}Error: Settings file not found: $SETTINGS_FILE${NC}"
    exit 1
fi

# help/usage need no provider config; everything else does. Fail closed and
# name the example -- an absent user file is not "use built-in defaults", it
# is a refusal (plan task E4).
case "${1:-status}" in
    help|--help|-h)
        show_usage
        exit 0
        ;;
esac

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}Error: provider configuration file not found: ${CONFIG_FILE}${NC}"
    echo -e "${YELLOW}Copy the shipped example and edit it:${NC}"
    echo "  mkdir -p \"$(dirname "$CONFIG_FILE")\""
    echo "  cp ${EXAMPLE_CONFIG_PATH} \"$CONFIG_FILE\""
    exit 1
fi

if ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
    echo -e "${RED}Error: ${CONFIG_FILE} is not valid JSON${NC}"
    exit 1
fi

# Return the provider key whose (base_url, models.sonnet) pair matches the
# settings file's current values, or "unknown" when none match (a provider
# not in this config file, or the file's own default when settings.json has
# no override set at all).
check_current_provider() {
    local current_base current_sonnet default_provider match
    current_base=$(jq -r '.env.ANTHROPIC_BASE_URL // ""' "$SETTINGS_FILE")
    current_sonnet=$(jq -r '.env.ANTHROPIC_DEFAULT_SONNET_MODEL // ""' "$SETTINGS_FILE")
    default_provider=$(jq -r '.settings.default_provider // ""' "$CONFIG_FILE")

    if [ -z "$current_base" ]; then
        # No override set: this is whichever provider the config calls its
        # default (normally the one with base_url: null).
        if [ -n "$default_provider" ]; then
            echo "$default_provider"
        else
            echo "unknown"
        fi
        return
    fi

    match=$(jq -r --arg base "$current_base" --arg sonnet "$current_sonnet" '
        .providers
        | to_entries[]
        | select(.value.base_url == $base and .value.models.sonnet == $sonnet)
        | .key
    ' "$CONFIG_FILE" | head -n1)

    if [ -n "$match" ]; then
        echo "$match"
    else
        echo "unknown"
    fi
}

show_status() {
    local current entry name description haiku sonnet opus base_url
    current=$(check_current_provider)
    echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  Claude Code Provider Status${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"

    if [ "$current" = "unknown" ]; then
        echo -e "Current Provider: ${YELLOW}unknown (not listed in ${CONFIG_FILE})${NC}"
        echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"
        return
    fi

    entry=$(jq -c --arg key "$current" '.providers[$key]' "$CONFIG_FILE")
    name=$(echo "$entry" | jq -r '.name')
    description=$(echo "$entry" | jq -r '.description // ""')
    base_url=$(echo "$entry" | jq -r '.base_url // "(default, no override)"')
    haiku=$(echo "$entry" | jq -r '.models.haiku // "-"')
    sonnet=$(echo "$entry" | jq -r '.models.sonnet // "-"')
    opus=$(echo "$entry" | jq -r '.models.opus // "-"')

    echo -e "Current Provider: ${GREEN}${name}${NC} (${current})"
    [ -n "$description" ] && echo -e "${description}"
    echo -e "Base URL: ${base_url}"
    echo ""
    echo -e "${BLUE}Model Mapping:${NC}"
    echo "  • Haiku  → ${haiku}"
    echo "  • Sonnet → ${sonnet}"
    echo "  • Opus   → ${opus}"
    echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"
}

list_providers() {
    echo -e "${BLUE}Providers in ${CONFIG_FILE}:${NC}"
    echo ""
    jq -r '.providers | to_entries[] | "  \(.key): \(.value.name) - \(.value.description // "")"' "$CONFIG_FILE"
    echo ""
    show_usage
}

# Apply the named provider's config-file entry to settings.json. A null (or
# absent) base_url removes the override block entirely, which is how the
# config file's own "anthropic" entry switches back to native Claude.
switch_provider() {
    local provider="$1"
    local entry name base_url api_key_env api_key haiku sonnet opus temp_file

    entry=$(jq -c --arg key "$provider" '.providers[$key] // empty' "$CONFIG_FILE")
    if [ -z "$entry" ]; then
        echo -e "${RED}Error: provider '${provider}' is not defined in ${CONFIG_FILE}${NC}"
        list_providers
        exit 1
    fi

    name=$(echo "$entry" | jq -r '.name')
    base_url=$(echo "$entry" | jq -r '.base_url // empty')

    cp "$SETTINGS_FILE" "$BACKUP_FILE"
    echo -e "${GREEN}✓${NC} Backed up settings to $BACKUP_FILE"
    temp_file=$(mktemp)

    if [ -z "$base_url" ]; then
        echo -e "${YELLOW}Switching to ${name} (no override; native Claude auth)...${NC}"
        jq 'del(.env.ANTHROPIC_BASE_URL) |
            del(.env.ANTHROPIC_AUTH_TOKEN) |
            del(.env.ANTHROPIC_DEFAULT_HAIKU_MODEL) |
            del(.env.ANTHROPIC_DEFAULT_SONNET_MODEL) |
            del(.env.ANTHROPIC_DEFAULT_OPUS_MODEL)' \
            "$SETTINGS_FILE" > "$temp_file"
    else
        api_key_env=$(echo "$entry" | jq -r '.api_key_env // empty')
        if [ -z "$api_key_env" ]; then
            echo -e "${RED}Error: provider '${provider}' has a base_url but no api_key_env in ${CONFIG_FILE}${NC}"
            rm -f "$temp_file"
            exit 1
        fi
        # api_key_env names the env var to read, indirectly (${!api_key_env}
        # below). It comes from the user's own config file, so before that
        # indirect expansion runs it must be a bare shell identifier -- never
        # whatever string happens to be in the file. This is a validation
        # gate, not a defense against arbitrary code execution (bash
        # indirect expansion cannot itself run a command): a malformed value
        # would otherwise surface as an opaque "bad substitution" error deep
        # inside the expansion instead of a named refusal here.
        if ! [[ "$api_key_env" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
            echo -e "${RED}Error: api_key_env '${api_key_env}' for provider '${provider}' is not a valid environment-variable name in ${CONFIG_FILE}${NC}"
            rm -f "$temp_file"
            exit 1
        fi
        api_key="${!api_key_env:-}"
        if [ -z "$api_key" ]; then
            echo -e "${RED}Error: environment variable ${api_key_env} is not set (required for provider '${provider}')${NC}"
            rm -f "$temp_file"
            exit 1
        fi
        haiku=$(echo "$entry" | jq -r '.models.haiku // empty')
        sonnet=$(echo "$entry" | jq -r '.models.sonnet // empty')
        opus=$(echo "$entry" | jq -r '.models.opus // empty')
        echo -e "${YELLOW}Switching to ${name}...${NC}"
        jq --arg base_url "$base_url" --arg api_key "$api_key" \
           --arg haiku "$haiku" --arg sonnet "$sonnet" --arg opus "$opus" \
           '.env.ANTHROPIC_BASE_URL = $base_url |
            .env.ANTHROPIC_AUTH_TOKEN = $api_key |
            .env.ANTHROPIC_DEFAULT_HAIKU_MODEL = $haiku |
            .env.ANTHROPIC_DEFAULT_SONNET_MODEL = $sonnet |
            .env.ANTHROPIC_DEFAULT_OPUS_MODEL = $opus' \
           "$SETTINGS_FILE" > "$temp_file"
    fi

    mv "$temp_file" "$SETTINGS_FILE"
    echo -e "${GREEN}✓${NC} Configured ${name} provider"
    echo -e "${YELLOW}Note:${NC} Restart Claude Code for changes to take effect"
}

case "${1:-status}" in
    status)
        show_status
        ;;
    list)
        list_providers
        ;;
    "")
        show_status
        ;;
    *)
        current=$(check_current_provider)
        if [ "$current" = "$1" ]; then
            echo -e "${YELLOW}Already using ${1} provider${NC}"
            show_status
        else
            switch_provider "$1"
            show_status
        fi
        ;;
esac
