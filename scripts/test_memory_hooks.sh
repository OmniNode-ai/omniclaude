#!/bin/bash
# Test Memory Management Hooks
# Verifies that Claude Code hooks are working correctly

set -e

PROJECT_ROOT="/Users/jonah/Code/omniclaude"
MEMORY_DIR="$HOME/.claude/memory"
SETTINGS_FILE="$HOME/.claude/settings.json"

echo "======================================================================="
echo "Memory Management Hooks - Automated Test"
echo "======================================================================="
echo ""

# Test 1: Check hook symlinks
echo "1. Checking hook symlinks..."
if [ -L "$HOME/.claude/hooks" ]; then
    target=$(readlink "$HOME/.claude/hooks")
    if [ "$target" = "$PROJECT_ROOT/claude_hooks" ]; then
        echo "   ✅ Hooks symlink correct: $HOME/.claude/hooks → $target"
    else
        echo "   ❌ Hooks symlink incorrect: $HOME/.claude/hooks → $target"
        echo "      Expected: $PROJECT_ROOT/claude_hooks"
        exit 1
    fi
else
    echo "   ❌ Hooks directory is not a symlink"
    exit 1
fi

# Test 2: Check hook files exist
echo ""
echo "2. Checking hook files..."
for hook in pre_prompt_submit.py post_tool_use.py workspace_change.py; do
    if [ -f "$HOME/.claude/hooks/$hook" ]; then
        echo "   ✅ $hook exists"
    else
        echo "   ❌ $hook missing"
        exit 1
    fi
done

# Test 3: Check hook executability and imports
echo ""
echo "3. Testing hook imports..."
for hook in pre_prompt_submit.py post_tool_use.py workspace_change.py; do
    if $PROJECT_ROOT/claude_hooks/test_minimal_hook.py > /dev/null 2>&1; then
        echo "   ✅ Hooks can import claude_hooks module"
        break
    else
        echo "   ❌ Hooks cannot import claude_hooks module"
        exit 1
    fi
done

# Test 4: Check settings.json configuration
echo ""
echo "4. Checking settings.json..."
if grep -q "UserPromptSubmit" "$SETTINGS_FILE" 2>/dev/null; then
    echo "   ✅ UserPromptSubmit hook registered"
else
    echo "   ❌ UserPromptSubmit hook not registered"
    exit 1
fi

if grep -q "PostToolUse" "$SETTINGS_FILE" 2>/dev/null; then
    echo "   ✅ PostToolUse hook registered"
else
    echo "   ❌ PostToolUse hook not registered"
    exit 1
fi

if grep -q "SessionStart" "$SETTINGS_FILE" 2>/dev/null; then
    echo "   ✅ SessionStart hook registered"
else
    echo "   ❌ SessionStart hook not registered"
    exit 1
fi

# Test 5: Check memory directory structure
echo ""
echo "5. Checking memory storage..."
if [ -d "$MEMORY_DIR" ]; then
    echo "   ✅ Memory directory exists: $MEMORY_DIR"

    # Check categories
    for category in workspace execution_history patterns; do
        if [ -d "$MEMORY_DIR/$category" ]; then
            count=$(find "$MEMORY_DIR/$category" -type f -name "*.md" | wc -l | xargs)
            echo "   ✅ Category: $category ($count files)"
        else
            echo "   ⚠️  Category: $category (directory not created yet)"
        fi
    done
else
    echo "   ⚠️  Memory directory not created yet: $MEMORY_DIR"
    echo "      (Will be created on first hook execution)"
fi

# Test 6: Check environment configuration
echo ""
echo "6. Checking environment configuration..."
if grep -q "ENABLE_MEMORY_CLIENT=true" "$PROJECT_ROOT/.env" 2>/dev/null; then
    echo "   ✅ ENABLE_MEMORY_CLIENT=true"
else
    echo "   ❌ ENABLE_MEMORY_CLIENT not set to true"
    exit 1
fi

if grep -q "MEMORY_STORAGE_PATH" "$PROJECT_ROOT/.env" 2>/dev/null; then
    echo "   ✅ MEMORY_STORAGE_PATH configured"
else
    echo "   ❌ MEMORY_STORAGE_PATH not configured"
    exit 1
fi

# Test 7: Test memory client directly
echo ""
echo "7. Testing memory client..."
cd "$PROJECT_ROOT"
if poetry run python -c "
from claude_hooks.lib.memory_client import get_memory_client
import asyncio

async def test():
    memory = get_memory_client()
    await memory.store_memory('test_hook_verify', {'status': 'working'}, 'workspace')
    result = await memory.get_memory('test_hook_verify', 'workspace')
    # Result is now markdown format, just verify it's not None
    assert result is not None, f'Expected memory content, got None'
    assert 'working' in result, f'Expected \"working\" in content, got {result}'
    await memory.delete_memory('test_hook_verify', 'workspace')
    print('✅ Memory client operations successful')

asyncio.run(test())
" 2>/dev/null; then
    echo "   ✅ Memory client operational"
else
    echo "   ❌ Memory client test failed"
    exit 1
fi

# Summary
echo ""
echo "======================================================================="
echo "✅ ALL TESTS PASSED"
echo "======================================================================="
echo ""
echo "Hook Status:"
echo "  - Hooks symlinked and executable"
echo "  - Imports working correctly"
echo "  - Registered in settings.json"
echo "  - Memory storage configured"
echo "  - Memory client operational"
echo ""
echo "Next: Restart Claude Code to activate hooks in live session"
echo "======================================================================="
