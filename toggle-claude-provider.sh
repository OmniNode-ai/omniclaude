#!/bin/bash

# Claude Code Provider Toggle Script
# Switches between Anthropic Claude and Z.ai GLM models
# Usage: ./toggle-provider.sh [claude|zai|status]

set -e

SETTINGS_FILE="$HOME/.claude/settings.json"
BACKUP_FILE="$HOME/.claude/settings.json.backup"
ZAI_API_KEY="0160cf7a325748efa11da4522a868d00.1nlfd4HCmj42NtHC"
ZAI_BASE_URL="https://api.z.ai/api/anthropic"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to check current provider
check_current_provider() {
    if grep -q "ANTHROPIC_BASE_URL.*z\.ai" "$SETTINGS_FILE" 2>/dev/null; then
        echo "zai"
    elif grep -q "ANTHROPIC_BASE_URL.*together\.xyz" "$SETTINGS_FILE" 2>/dev/null; then
        echo "together"
    elif grep -q "ANTHROPIC_BASE_URL.*openrouter\.ai" "$SETTINGS_FILE" 2>/dev/null; then
        echo "openrouter"
    elif grep -q "ANTHROPIC_BASE_URL.*generativelanguage\.googleapis\.com" "$SETTINGS_FILE" 2>/dev/null; then
        if grep -q "ANTHROPIC_DEFAULT_SONNET_MODEL.*gemini-2.5-flash" "$SETTINGS_FILE" 2>/dev/null; then
            echo "gemini-2.5-flash"
        elif grep -q "ANTHROPIC_DEFAULT_SONNET_MODEL.*gemini-1.5-pro" "$SETTINGS_FILE" 2>/dev/null; then
            echo "gemini-pro"
        else
            echo "gemini-flash"
        fi
    else
        echo "claude"
    fi
}

# Function to show status
show_status() {
    local current=$(check_current_provider)
    echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  Claude Code Provider Status${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"

    case "$current" in
        "zai")
            echo -e "Current Provider: ${GREEN}Z.ai GLM Models${NC}"
            echo -e "Base URL: ${ZAI_BASE_URL}"
            echo ""
            echo -e "${BLUE}Model Mapping:${NC}"
            echo "  • Haiku  → GLM-4.5-Air (5 concurrent)"
            echo "  • Sonnet → GLM-4.5    (20 concurrent)"
            echo "  • Opus   → GLM-4.6    (10 concurrent)"
            echo ""
            echo -e "${GREEN}Total Concurrent Capacity: 35 requests${NC}"
            ;;
        "gemini-pro"|"gemini-flash")
            echo -e "Current Provider: ${GREEN}Google Gemini${NC}"
            echo -e "Base URL: https://generativelanguage.googleapis.com/v1beta/anthropic"
            echo ""
            echo -e "${BLUE}Model Mapping:${NC}"
            case "$current" in
                "gemini-2.5-flash")
                    echo "  • Haiku  → gemini-2.5-flash (No rate limits)"
                    echo "  • Sonnet → gemini-2.5-flash (No rate limits)"
                    echo "  • Opus   → gemini-2.5-pro (No rate limits)"
                    ;;
                "gemini-pro")
                    echo "  • Haiku  → gemini-1.5-flash (No rate limits)"
                    echo "  • Sonnet → gemini-1.5-pro (No rate limits)"
                    echo "  • Opus   → gemini-1.5-pro (No rate limits)"
                    ;;
                "gemini-flash")
                    echo "  • Haiku  → gemini-1.5-flash (No rate limits)"
                    echo "  • Sonnet → gemini-1.5-flash (No rate limits)"
                    echo "  • Opus   → gemini-1.5-pro (No rate limits)"
                    ;;
            esac
            echo ""
            echo -e "${GREEN}No rate limits${NC}"
            ;;
        "together")
            echo -e "Current Provider: ${GREEN}Together AI${NC}"
            echo -e "Base URL: https://api.together.xyz/api/anthropic"
            echo ""
            echo -e "${BLUE}Model Mapping:${NC}"
            echo "  • Haiku  → Llama-3.1-8B-Instruct-Turbo"
            echo "  • Sonnet → Llama-3.1-70B-Instruct-Turbo"
            echo "  • Opus   → Llama-3.1-405B-Instruct-Turbo"
            echo ""
            echo -e "${GREEN}Variable rate limits apply${NC}"
            ;;
        "openrouter")
            echo -e "Current Provider: ${GREEN}OpenRouter${NC}"
            echo -e "Base URL: https://openrouter.ai/api/v1/anthropic"
            echo ""
            echo -e "${BLUE}Model Mapping:${NC}"
            echo "  • Haiku  → anthropic/claude-3.5-haiku"
            echo "  • Sonnet → anthropic/claude-3.5-sonnet"
            echo "  • Opus   → anthropic/claude-3-opus"
            echo ""
            echo -e "${GREEN}OpenRouter rate limits apply${NC}"
            ;;
        *)
            echo -e "Current Provider: ${GREEN}Anthropic Claude${NC}"
            echo -e "Models: Native Claude (Sonnet 4.5, Opus, Haiku)"
            echo -e "${BLUE}Standard Anthropic rate limits apply${NC}"
            ;;
    esac
    echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"
}

# Function to switch to Z.ai
switch_to_zai() {
    echo -e "${YELLOW}Switching to Z.ai GLM models with optimized rate limits...${NC}"

    # Backup current settings
    cp "$SETTINGS_FILE" "$BACKUP_FILE"
    echo -e "${GREEN}✓${NC} Backed up settings to $BACKUP_FILE"

    # Use jq to modify the JSON with proper model mapping
    local temp_file=$(mktemp)
    jq --arg base_url "$ZAI_BASE_URL" \
       --arg api_key "$ZAI_API_KEY" \
       '.env.ANTHROPIC_BASE_URL = $base_url |
        .env.ANTHROPIC_AUTH_TOKEN = $api_key |
        .env.ANTHROPIC_DEFAULT_HAIKU_MODEL = "glm-4.5-air" |
        .env.ANTHROPIC_DEFAULT_SONNET_MODEL = "glm-4.5" |
        .env.ANTHROPIC_DEFAULT_OPUS_MODEL = "glm-4.6"' \
       "$SETTINGS_FILE" > "$temp_file"

    mv "$temp_file" "$SETTINGS_FILE"
    echo -e "${GREEN}✓${NC} Configured Z.ai provider with model mapping"
    echo -e "${GREEN}✓${NC} API Key: ${ZAI_API_KEY:0:8}...${ZAI_API_KEY: -4}"
    echo ""
    echo -e "${BLUE}Z.ai GLM Models Active with Rate Limits:${NC}"
    echo "  • GLM-4.6 (Opus equivalent)    - 10 concurrent requests"
    echo "  • GLM-4.5 (Sonnet equivalent)   - 20 concurrent requests"
    echo "  • GLM-4.5-Air (Haiku equivalent) - 5 concurrent requests"
    echo ""
    echo -e "${GREEN}Optimized for high concurrency!${NC}"
    echo -e "${YELLOW}Note:${NC} Restart Claude Code for changes to take effect"
}

# Function to switch to Claude
switch_to_claude() {
    echo -e "${YELLOW}Switching to Anthropic Claude models...${NC}"

    # Backup current settings
    cp "$SETTINGS_FILE" "$BACKUP_FILE"
    echo -e "${GREEN}✓${NC} Backed up settings to $BACKUP_FILE"

    # Use jq to remove Z.ai configuration and model mappings
    local temp_file=$(mktemp)
    jq 'del(.env.ANTHROPIC_BASE_URL) |
        del(.env.ANTHROPIC_AUTH_TOKEN) |
        del(.env.ANTHROPIC_DEFAULT_HAIKU_MODEL) |
        del(.env.ANTHROPIC_DEFAULT_SONNET_MODEL) |
        del(.env.ANTHROPIC_DEFAULT_OPUS_MODEL)' \
       "$SETTINGS_FILE" > "$temp_file"

    mv "$temp_file" "$SETTINGS_FILE"
    echo -e "${GREEN}✓${NC} Removed Z.ai configuration and model mappings"
    echo ""
    echo -e "${BLUE}Anthropic Claude Models Active:${NC}"
    echo "  • Claude Sonnet 4.5 (Default)"
    echo "  • Claude Opus (Premium)"
    echo "  • Claude Haiku (Fast)"
    echo ""
    echo -e "${YELLOW}Note:${NC} Restart Claude Code for changes to take effect"
}

# Function to show usage
show_usage() {
    echo -e "${BLUE}Usage:${NC}"
    echo "  $0 claude        - Switch to Anthropic Claude models"
    echo "  $0 zai           - Switch to Z.ai GLM models with optimized concurrency"
    echo "  $0 together      - Switch to Together AI models"
    echo "  $0 openrouter    - Switch to OpenRouter models"
    echo "  $0 gemini-pro      - Switch to Google Gemini Pro models"
    echo "  $0 gemini-flash    - Switch to Google Gemini Flash models"
    echo "  $0 gemini-2.5-flash - Switch to Google Gemini 2.5 Flash models"
    echo "  $0 status        - Show current provider status"
    echo "  $0 list          - List all available providers"
    echo ""
    echo -e "${BLUE}Examples:${NC}"
    echo "  $0 zai           # Switch to Z.ai for 35 total concurrent requests"
    echo "  $0 gemini-pro      # Switch to Google Gemini Pro for quality"
    echo "  $0 gemini-flash    # Switch to Google Gemini Flash for speed"
    echo "  $0 gemini-2.5-flash # Switch to Google Gemini 2.5 Flash for latest capabilities"
    echo "  $0 claude        # Switch back to native Claude models"
    echo "  $0 status        # Check current provider and model mapping"
    echo ""
    echo -e "${BLUE}Rate Limits:${NC}"
    echo "  Z.ai: GLM-4.5-Air (5), GLM-4.5 (20), GLM-4.6 (10)"
    echo "  Gemini Flash: No rate limits"
    echo "  Gemini Pro: No rate limits"
    echo "  Gemini 2.5 Flash: No rate limits"
    echo "  Claude: Standard Anthropic limits"
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

# Function to switch to Gemini Pro
switch_to_gemini_pro() {
    echo -e "${YELLOW}Switching to Google Gemini Pro models...${NC}"

    # Backup current settings
    cp "$SETTINGS_FILE" "$BACKUP_FILE"
    echo -e "${GREEN}✓${NC} Backed up settings to $BACKUP_FILE"

    # Use jq to modify the JSON with proper model mapping
    local temp_file=$(mktemp)
    jq --arg base_url "https://generativelanguage.googleapis.com/v1beta/anthropic" \
       --arg api_key "AIzaSyDaaj2noZRNefE7aRLoc5xmbMDpvrz8LzU" \
       '.env.ANTHROPIC_BASE_URL = $base_url |
        .env.ANTHROPIC_AUTH_TOKEN = $api_key |
        .env.ANTHROPIC_DEFAULT_HAIKU_MODEL = "gemini-1.5-flash" |
        .env.ANTHROPIC_DEFAULT_SONNET_MODEL = "gemini-1.5-pro" |
        .env.ANTHROPIC_DEFAULT_OPUS_MODEL = "gemini-1.5-pro"' \
       "$SETTINGS_FILE" > "$temp_file"

    mv "$temp_file" "$SETTINGS_FILE"
    echo -e "${GREEN}✓${NC} Configured Google Gemini Pro provider"
    echo ""
    echo -e "${BLUE}Google Gemini Models Active:${NC}"
    echo "  • Gemini 1.5 Flash (Haiku equivalent) - 15 concurrent requests"
    echo "  • Gemini 1.5 Pro (Sonnet/Opus equivalent) - 2 concurrent requests"
    echo ""
    echo -e "${GREEN}Total Concurrent Capacity: 17 requests${NC}"
    echo -e "${YELLOW}Note:${NC} Restart Claude Code for changes to take effect"
}

# Function to switch to Gemini Flash
switch_to_gemini_flash() {
    echo -e "${YELLOW}Switching to Google Gemini Flash models (optimized for speed)...${NC}"

    # Backup current settings
    cp "$SETTINGS_FILE" "$BACKUP_FILE"
    echo -e "${GREEN}✓${NC} Backed up settings to $BACKUP_FILE"

    # Use jq to modify the JSON with proper model mapping
    local temp_file=$(mktemp)
    jq --arg base_url "https://generativelanguage.googleapis.com/v1beta/anthropic" \
       --arg api_key "AIzaSyDaaj2noZRNefE7aRLoc5xmbMDpvrz8LzU" \
       '.env.ANTHROPIC_BASE_URL = $base_url |
        .env.ANTHROPIC_AUTH_TOKEN = $api_key |
        .env.ANTHROPIC_DEFAULT_HAIKU_MODEL = "gemini-1.5-flash" |
        .env.ANTHROPIC_DEFAULT_SONNET_MODEL = "gemini-1.5-flash" |
        .env.ANTHROPIC_DEFAULT_OPUS_MODEL = "gemini-1.5-pro"' \
       "$SETTINGS_FILE" > "$temp_file"

    mv "$temp_file" "$SETTINGS_FILE"
    echo -e "${GREEN}✓${NC} Configured Google Gemini Flash provider"
    echo ""
    echo -e "${BLUE}Google Gemini Flash Models Active:${NC}"
    echo "  • Gemini 1.5 Flash (Haiku/Sonnet equivalent)"
    echo "  • Gemini 1.5 Pro (Opus equivalent)"
    echo ""
    echo -e "${GREEN}No rate limits - optimized for speed!${NC}"
    echo -e "${YELLOW}Note:${NC} Restart Claude Code for changes to take effect"
}

# Function to switch to Gemini 2.5 Flash
switch_to_gemini_2_5_flash() {
    echo -e "${YELLOW}Switching to Google Gemini 2.5 Flash models (latest capabilities)...${NC}"

    # Backup current settings
    cp "$SETTINGS_FILE" "$BACKUP_FILE"
    echo -e "${GREEN}✓${NC} Backed up settings to $BACKUP_FILE"

    # Use jq to modify the JSON with proper model mapping
    local temp_file=$(mktemp)
    jq --arg base_url "https://generativelanguage.googleapis.com/v1beta/anthropic" \
       --arg api_key "AIzaSyDaaj2noZRNefE7aRLoc5xmbMDpvrz8LzU" \
       '.env.ANTHROPIC_BASE_URL = $base_url |
        .env.ANTHROPIC_AUTH_TOKEN = $api_key |
        .env.ANTHROPIC_DEFAULT_HAIKU_MODEL = "gemini-2.5-flash" |
        .env.ANTHROPIC_DEFAULT_SONNET_MODEL = "gemini-2.5-flash" |
        .env.ANTHROPIC_DEFAULT_OPUS_MODEL = "gemini-2.5-pro"' \
       "$SETTINGS_FILE" > "$temp_file"

    mv "$temp_file" "$SETTINGS_FILE"
    echo -e "${GREEN}✓${NC} Configured Google Gemini 2.5 Flash provider"
    echo ""
    echo -e "${BLUE}Google Gemini 2.5 Flash Models Active:${NC}"
    echo "  • Gemini 2.5 Flash (Haiku/Sonnet equivalent)"
    echo "  • Gemini 2.5 Pro (Opus equivalent)"
    echo ""
    echo -e "${GREEN}No rate limits - latest capabilities!${NC}"
    echo -e "${YELLOW}Note:${NC} Restart Claude Code for changes to take effect"
}

# Function to switch provider from config
switch_provider_from_config() {
    local provider="$1"
    local config_file="$(dirname "$0")/claude-providers.json"

    if [ ! -f "$config_file" ]; then
        echo -e "${RED}Error: Provider configuration file not found: $config_file${NC}"
        exit 1
    fi

    # Extract provider configuration
    local provider_config=$(jq -r ".providers[\"$provider\"]" "$config_file")

    if [ "$provider_config" = "null" ]; then
        echo -e "${RED}Error: Provider '$provider' not found in configuration${NC}"
        exit 1
    fi

    # Extract values
    local name=$(echo "$provider_config" | jq -r '.name')
    local base_url=$(echo "$provider_config" | jq -r '.base_url')
    local api_key=$(echo "$provider_config" | jq -r '.api_key')
    local haiku_model=$(echo "$provider_config" | jq -r '.models.haiku')
    local sonnet_model=$(echo "$provider_config" | jq -r '.models.sonnet')
    local opus_model=$(echo "$provider_config" | jq -r '.models.opus')

    echo -e "${YELLOW}Switching to $name...${NC}"

    # Backup current settings
    cp "$SETTINGS_FILE" "$BACKUP_FILE"
    echo -e "${GREEN}✓${NC} Backed up settings to $BACKUP_FILE"

    # Build jq command based on provider
    local jq_args="--arg base_url \"$base_url\" --arg api_key \"$api_key\""
    local jq_filter='.env.ANTHROPIC_BASE_URL = $base_url | .env.ANTHROPIC_AUTH_TOKEN = $api_key'

    if [ "$base_url" != "null" ]; then
        jq_filter="$jq_filter | .env.ANTHROPIC_DEFAULT_HAIKU_MODEL = \"$haiku_model\" | .env.ANTHROPIC_DEFAULT_SONNET_MODEL = \"$sonnet_model\" | .env.ANTHROPIC_DEFAULT_OPUS_MODEL = \"$opus_model\""
    else
        jq_filter="del(.env.ANTHROPIC_BASE_URL) | del(.env.ANTHROPIC_AUTH_TOKEN) | del(.env.ANTHROPIC_DEFAULT_HAIKU_MODEL) | del(.env.ANTHROPIC_DEFAULT_SONNET_MODEL) | del(.env.ANTHROPIC_DEFAULT_OPUS_MODEL)"
    fi

    # Apply configuration
    local temp_file=$(mktemp)
    eval "jq $jq_args '$jq_filter' \"$SETTINGS_FILE\" > \"$temp_file\""
    mv "$temp_file" "$SETTINGS_FILE"

    echo -e "${GREEN}✓${NC} Configured $name provider"
    echo -e "${YELLOW}Note:${NC} Restart Claude Code for changes to take effect"
}

# Function to list all providers
list_providers() {
    local config_file="$(dirname "$0")/claude-providers.json"

    if [ ! -f "$config_file" ]; then
        echo -e "${RED}Error: Provider configuration file not found: $config_file${NC}"
        exit 1
    fi

    echo -e "${BLUE}Available Providers:${NC}"
    echo ""

    # List all providers from config
    jq -r '.providers | to_entries[] | "  \(.key): \(.value.name) - \(.value.description)"' "$config_file"

    echo ""
    echo -e "${BLUE}Usage:${NC}"
    echo "  $0 <provider_name>    # Switch to specified provider"
    echo "  $0 status             # Show current provider"
    echo "  $0 list               # Show this list"
}

# Main logic
case "${1:-status}" in
    zai)
        current=$(check_current_provider)
        if [ "$current" = "zai" ]; then
            echo -e "${YELLOW}Already using Z.ai provider${NC}"
            show_status
        else
            switch_to_zai
            show_status
        fi
        ;;
    claude)
        current=$(check_current_provider)
        if [ "$current" = "claude" ]; then
            echo -e "${YELLOW}Already using Claude provider${NC}"
            show_status
        else
            switch_to_claude
            show_status
        fi
        ;;
    gemini-pro)
        current=$(check_current_provider)
        if [ "$current" = "gemini-pro" ]; then
            echo -e "${YELLOW}Already using Google Gemini Pro provider${NC}"
            show_status
        else
            switch_to_gemini_pro
            show_status
        fi
        ;;
    gemini-flash)
        current=$(check_current_provider)
        if [ "$current" = "gemini-flash" ]; then
            echo -e "${YELLOW}Already using Google Gemini Flash provider${NC}"
            show_status
        else
            switch_to_gemini_flash
            show_status
        fi
        ;;
    gemini-2.5-flash)
        current=$(check_current_provider)
        if [ "$current" = "gemini-2.5-flash" ]; then
            echo -e "${YELLOW}Already using Google Gemini 2.5 Flash provider${NC}"
            show_status
        else
            switch_to_gemini_2_5_flash
            show_status
        fi
        ;;
    together|openrouter)
        current=$(check_current_provider)
        if [ "$current" = "$1" ]; then
            echo -e "${YELLOW}Already using $1 provider${NC}"
            show_status
        else
            switch_provider_from_config "$1"
            show_status
        fi
        ;;
    list)
        list_providers
        ;;
    status)
        show_status
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        echo -e "${RED}Error: Invalid argument '$1'${NC}"
        echo ""
        show_usage
        exit 1
        ;;
esac
