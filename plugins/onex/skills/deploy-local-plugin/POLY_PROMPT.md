# Deploy Local Plugin — Poly Worker Prompt

Deploy the local plugin source to the Claude Code plugin cache for testing.

## Arguments

- `EXECUTE`: "true" if `--execute` flag provided, otherwise dry-run
- `NO_VERSION_BUMP`: "true" if `--no-version-bump` flag provided

## Steps

### 1. Read Current State

```bash
PLUGIN_JSON="${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json"
CURRENT_VERSION=$(jq -r '.version' "$PLUGIN_JSON")
CACHE_BASE="$HOME/.claude/plugins/cache/omninode-tools/onex"
```

### 2. Calculate New Version

```bash
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

if [[ "$NO_VERSION_BUMP" != "true" ]]; then
    NEW_PATCH=$((PATCH + 1))
    NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
else
    NEW_VERSION="$CURRENT_VERSION"
fi
```

### 3. Preview Changes (Dry Run)

```bash
echo "=== Plugin Deployment Preview ==="
echo ""
echo "Version: $CURRENT_VERSION -> $NEW_VERSION"
echo "Source:  ${CLAUDE_PLUGIN_ROOT}"
echo "Target:  ${CACHE_BASE}/${NEW_VERSION}"
echo ""
echo "Components to sync:"
echo "  commands/:      $(ls -1 ${CLAUDE_PLUGIN_ROOT}/commands/*.md 2>/dev/null | wc -l | tr -d ' ') files"
echo "  skills/:        $(ls -1d ${CLAUDE_PLUGIN_ROOT}/skills/*/ 2>/dev/null | wc -l | tr -d ' ') directories"
echo "  agents/configs: $(ls -1 ${CLAUDE_PLUGIN_ROOT}/agents/configs/*.yaml 2>/dev/null | wc -l | tr -d ' ') files"
echo "  hooks/:         $(ls -1 ${CLAUDE_PLUGIN_ROOT}/hooks/ 2>/dev/null | wc -l | tr -d ' ') items"
echo "  .claude-plugin: plugin.json + metadata"
```

### 4. Execute Deployment

```bash
if [[ "$EXECUTE" == "true" ]]; then
    TARGET="${CACHE_BASE}/${NEW_VERSION}"

    if [[ "$NO_VERSION_BUMP" != "true" ]]; then
        jq --arg v "$NEW_VERSION" '.version = $v' "$PLUGIN_JSON" > "${PLUGIN_JSON}.tmp"
        mv "${PLUGIN_JSON}.tmp" "$PLUGIN_JSON"
        echo "Updated plugin.json version to $NEW_VERSION"
    fi

    mkdir -p "$TARGET"

    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/commands/" "${TARGET}/commands/"
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/skills/" "${TARGET}/skills/"
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/agents/" "${TARGET}/agents/"
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/hooks/" "${TARGET}/hooks/"
    rsync -av --delete "${CLAUDE_PLUGIN_ROOT}/.claude-plugin/" "${TARGET}/.claude-plugin/"

    cp "${CLAUDE_PLUGIN_ROOT}/.env.example" "${TARGET}/" 2>/dev/null || true
    cp "${CLAUDE_PLUGIN_ROOT}/README.md" "${TARGET}/" 2>/dev/null || true
    cp "${CLAUDE_PLUGIN_ROOT}/ENVIRONMENT_VARIABLES.md" "${TARGET}/" 2>/dev/null || true

    echo ""
    echo "Deployment complete!"
fi
```

### 5. Update Registry

```bash
REGISTRY="$HOME/.claude/plugins/installed_plugins.json"

if [[ -f "$REGISTRY" && "$EXECUTE" == "true" ]]; then
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
    jq --arg ts "$TIMESTAMP" --arg v "$NEW_VERSION" --arg p "$TARGET" '
        .plugins["onex@omninode-tools"][0].lastUpdated = $ts |
        .plugins["onex@omninode-tools"][0].version = $v |
        .plugins["onex@omninode-tools"][0].installPath = $p
    ' "$REGISTRY" > "${REGISTRY}.tmp"
    mv "${REGISTRY}.tmp" "$REGISTRY"
    echo "Updated installed_plugins.json"
fi
```

## Verification

After deployment, verify:

```bash
cat ~/.claude/plugins/cache/omninode-tools/onex/*/plugin.json | jq -r '.version' | sort -V | tail -1
ls -1 ~/.claude/plugins/cache/omninode-tools/onex/*/commands/*.md | wc -l
```

## Error Handling

| Error | Behavior |
|-------|----------|
| Missing plugin.json | Report error, abort |
| Target exists (same version) | Warn, overwrite with rsync --delete |
| Registry update fails | Warn but continue |
| Permission denied | Report error with suggested fix |
