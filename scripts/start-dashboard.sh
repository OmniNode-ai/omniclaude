#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Start OmniClaude Web Dashboard
# Opens browser and starts server

echo "🎯 Starting OmniClaude Web Dashboard..."
echo ""

# Start server in background
cd claude_hooks/tools && python3 dashboard_web.py &
SERVER_PID=$!

# Wait for server to start
sleep 2

# Open browser
if command -v open &> /dev/null; then
    # macOS
    open http://localhost:8000
elif command -v xdg-open &> /dev/null; then
    # Linux
    xdg-open http://localhost:8000
else
    echo "Dashboard running at: http://localhost:8000"
fi

echo ""
echo "Dashboard is running at: http://localhost:8000"
echo "Press Ctrl+C to stop the server"
echo ""

# Wait for Ctrl+C
trap "echo ''; echo 'Stopping dashboard...'; kill $SERVER_PID; exit 0" INT
wait $SERVER_PID
