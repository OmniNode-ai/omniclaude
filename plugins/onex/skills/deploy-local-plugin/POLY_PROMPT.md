# Deploy Local Plugin — Poly Worker Prompt

Deploy the local plugin source to the Claude Code plugin cache for testing.

## Arguments

- `EXECUTE`: "true" if `--execute` flag provided, otherwise dry-run
- `NO_VERSION_BUMP`: "true" if `--no-version-bump` flag provided

## Steps

### 1. Run deploy.sh

The `deploy.sh` script in this skill directory handles the full deployment lifecycle:
- Version bump (patch increment)
- rsync of all plugin components to cache
- Registry update (`installed_plugins.json`) with safety check
- `known_marketplaces.json` update (directory-source only)
- `settings.json` statusLine path update
- Namespace symlink creation (`~/.claude/{commands,skills,agents}/onex`)

Build the command from the arguments:

```bash
DEPLOY_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/deploy-local-plugin/deploy.sh"

CMD="$DEPLOY_SCRIPT"
if [[ "$EXECUTE" == "true" ]]; then
    CMD="$CMD --execute"
fi
if [[ "$NO_VERSION_BUMP" == "true" ]]; then
    CMD="$CMD --no-version-bump"
fi

bash $CMD
```

### 2. Verify Deployment (if --execute was used)

After deployment, verify the specific deployed version:

```bash
if [[ "$EXECUTE" == "true" ]]; then
    # Read the version that was just deployed from the source plugin.json
    PLUGIN_JSON="${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json"
    DEPLOYED_VERSION=$(jq -r '.version' "$PLUGIN_JSON")
    TARGET="$HOME/.claude/plugins/cache/omninode-tools/onex/${DEPLOYED_VERSION}"

    echo "Verifying deployment of version ${DEPLOYED_VERSION}..."

    # Check plugin.json exists in target
    cat "${TARGET}/.claude-plugin/plugin.json" | jq -r '.version'

    # Check component counts
    ls -1 "${TARGET}/commands/"*.md 2>/dev/null | wc -l
    ls -1 "${TARGET}/agents/configs/"*.yaml 2>/dev/null | wc -l
fi
```

### 3. Report Result

Report the deployment outcome:
- If dry-run: show what would happen (deploy.sh already displays this)
- If executed: confirm version deployed and component counts

## Error Handling

| Error | Behavior |
|-------|----------|
| Missing plugin.json | deploy.sh reports error, abort |
| Missing jq or rsync | deploy.sh reports error, abort |
| Target exists (same version) | Warn, overwrite with rsync --delete |
| Registry update fails | Warn but continue |
| Permission denied | Report error with suggested fix |
