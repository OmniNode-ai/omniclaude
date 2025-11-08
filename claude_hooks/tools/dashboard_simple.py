#!/usr/bin/env python3
"""
Simple Web Dashboard
Lightweight web interface for OmniClaude system monitoring
"""

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Use simple http.server for minimal dependencies
from http.server import BaseHTTPRequestHandler, HTTPServer

from system_dashboard_md import SystemDashboard


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and datetime objects"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class DashboardHandler(BaseHTTPRequestHandler):
    """Simple HTTP request handler for dashboard"""

    def log_message(self, format, *args):
        """Suppress request logging"""
        pass

    def do_GET(self):
        """Handle GET requests"""
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(self.get_dashboard_html().encode())

        elif self.path == "/api/dashboard":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = self.get_dashboard_data()
            self.wfile.write(json.dumps(data, cls=DecimalEncoder).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def get_dashboard_data(self):
        """Get dashboard data"""
        dashboard = SystemDashboard()

        health = dashboard.get_system_health()
        top_agents = dashboard.get_top_agents()
        recent_routing = dashboard.get_recent_routing_decisions(limit=10)
        issues = dashboard.get_system_issues()

        # Calculate health score
        # Use explicit None check to preserve zero values
        avg_conf_raw = health.get("avg_confidence")
        avg_conf = float(avg_conf_raw if avg_conf_raw is not None else 0)
        routing_health = min(100, avg_conf * 100)

        total_events_raw = health.get("total_events")
        total_events = int(total_events_raw if total_events_raw is not None else 0)
        processed_events_raw = health.get("processed_events")
        processed_events = int(
            processed_events_raw if processed_events_raw is not None else 0
        )
        hook_health = (
            100 if total_events == 0 else (100 * processed_events / total_events)
        )

        hit_rate_raw = health.get("hit_rate")
        cache_health = float(hit_rate_raw if hit_rate_raw is not None else 0)
        overall_score = routing_health * 0.5 + hook_health * 0.3 + cache_health * 0.2

        # Format recent activity
        activity = []
        for item in recent_routing:
            activity.append(
                {
                    "selected_agent": item["selected_agent"],
                    "confidence_score": float(item["confidence_score"]),
                    "routing_time_ms": int(item["routing_time_ms"] or 0),
                    "created_at": item["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        return {
            "health": {
                **health,
                "score": overall_score,
            },
            "top_agents": top_agents,
            "recent_activity": activity,
            "issues": issues,
        }

    def get_dashboard_html(self):
        """Get dashboard HTML"""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎯 OmniClaude System Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .health-excellent { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
        .health-good { background: linear-gradient(135deg, #84cc16 0%, #65a30d 100%); }
        .health-fair { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); }
        .health-poor { background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); }
        .metric-card { transition: transform 0.2s; }
        .metric-card:hover { transform: translateY(-2px); }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .live-indicator { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
    </style>
</head>
<body class="bg-gray-900 text-gray-100">
    <div class="container mx-auto px-4 py-6 max-w-7xl">
        <!-- Header -->
        <div class="flex justify-between items-center mb-6">
            <div>
                <h1 class="text-4xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-500">
                    🎯 OmniClaude Dashboard
                </h1>
                <p class="text-gray-400 mt-1">Real-time system monitoring</p>
            </div>
            <div class="flex items-center space-x-2">
                <div class="live-indicator w-3 h-3 bg-green-500 rounded-full"></div>
                <span class="text-sm text-gray-400">Auto-refresh</span>
                <span class="text-sm text-gray-500" id="last-update">--:--:--</span>
            </div>
        </div>

        <!-- System Health -->
        <div id="health-card" class="mb-6 rounded-lg shadow-xl p-6 text-white">
            <h2 class="text-2xl font-bold mb-2">System Health</h2>
            <div class="flex items-center space-x-4">
                <div class="text-6xl font-bold" id="health-score">--</div>
                <div>
                    <div class="text-xl" id="health-status">Loading...</div>
                    <div class="text-sm opacity-75">Health Score</div>
                </div>
            </div>
        </div>

        <!-- Quick Metrics Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
            <div class="metric-card bg-gray-800 rounded-lg shadow-lg p-4">
                <div class="text-gray-400 text-sm mb-1">Routing Decisions</div>
                <div class="text-3xl font-bold text-cyan-400" id="metric-decisions">0</div>
                <div class="text-xs text-gray-500 mt-1">Last 24h</div>
            </div>
            <div class="metric-card bg-gray-800 rounded-lg shadow-lg p-4">
                <div class="text-gray-400 text-sm mb-1">Avg Confidence</div>
                <div class="text-3xl font-bold text-green-400" id="metric-confidence">0%</div>
                <div class="text-xs text-gray-500 mt-1">Detection accuracy</div>
            </div>
            <div class="metric-card bg-gray-800 rounded-lg shadow-lg p-4">
                <div class="text-gray-400 text-sm mb-1">Avg Routing Time</div>
                <div class="text-3xl font-bold text-yellow-400" id="metric-routing">0ms</div>
                <div class="text-xs text-gray-500 mt-1">Response time</div>
            </div>
            <div class="metric-card bg-gray-800 rounded-lg shadow-lg p-4">
                <div class="text-gray-400 text-sm mb-1">Hook Events</div>
                <div class="text-3xl font-bold text-blue-400" id="metric-hooks">0</div>
                <div class="text-xs text-gray-500 mt-1"><span id="metric-hooks-pending">0</span> pending</div>
            </div>
            <div class="metric-card bg-gray-800 rounded-lg shadow-lg p-4">
                <div class="text-gray-400 text-sm mb-1">Cache Hit Rate</div>
                <div class="text-3xl font-bold text-purple-400" id="metric-cache">0%</div>
                <div class="text-xs text-gray-500 mt-1">Performance</div>
            </div>
        </div>

        <!-- Two Column Layout -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Left Column -->
            <div class="space-y-6">
                <!-- System Issues -->
                <div class="bg-gray-800 rounded-lg shadow-xl p-6">
                    <h3 class="text-xl font-bold mb-4 flex items-center">
                        ⚠️ System Issues
                        <span class="ml-2 text-sm font-normal text-gray-400" id="issue-count">(0)</span>
                    </h3>
                    <div id="issues-list" class="space-y-3">
                        <div class="text-gray-400 text-sm">Loading...</div>
                    </div>
                </div>

                <!-- Top Agents -->
                <div class="bg-gray-800 rounded-lg shadow-xl p-6">
                    <h3 class="text-xl font-bold mb-4">🤖 Top Agents</h3>
                    <div id="top-agents-list" class="space-y-2">
                        <div class="text-gray-400 text-sm">Loading...</div>
                    </div>
                </div>
            </div>

            <!-- Right Column -->
            <div class="space-y-6">
                <!-- Recent Activity -->
                <div class="bg-gray-800 rounded-lg shadow-xl p-6">
                    <h3 class="text-xl font-bold mb-4">📅 Recent Activity</h3>
                    <div id="activity-list" class="space-y-2 max-h-96 overflow-y-auto">
                        <div class="text-gray-400 text-sm">Loading...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function updateDashboard() {
            fetch('/api/dashboard')
                .then(r => r.json())
                .then(data => {
                    // Update health
                    const health = data.health || {};
                    const score = health.score || 0;
                    document.getElementById('health-score').textContent = score.toFixed(1);

                    const healthCard = document.getElementById('health-card');
                    healthCard.className = 'mb-6 rounded-lg shadow-xl p-6 text-white ' +
                        (score >= 90 ? 'health-excellent' :
                         score >= 75 ? 'health-good' :
                         score >= 60 ? 'health-fair' : 'health-poor');

                    const status = score >= 90 ? '🟢 EXCELLENT' :
                                  score >= 75 ? '🟡 GOOD' :
                                  score >= 60 ? '🟠 FAIR' : '🔴 POOR';
                    document.getElementById('health-status').textContent = status;

                    // Update metrics
                    document.getElementById('metric-decisions').textContent = health.total_decisions || 0;
                    document.getElementById('metric-confidence').textContent =
                        ((health.avg_confidence || 0) * 100).toFixed(1) + '%';
                    document.getElementById('metric-routing').textContent =
                        (health.avg_routing_ms || 0).toFixed(0) + 'ms';
                    document.getElementById('metric-hooks').textContent = health.total_events || 0;
                    document.getElementById('metric-hooks-pending').textContent = health.pending_events || 0;
                    document.getElementById('metric-cache').textContent =
                        (health.hit_rate || 0).toFixed(1) + '%';

                    // Update issues
                    const issues = data.issues || [];
                    document.getElementById('issue-count').textContent = `(${issues.length})`;

                    if (issues.length === 0) {
                        document.getElementById('issues-list').innerHTML =
                            '<div class="text-green-400 text-sm">✅ All systems operational</div>';
                    } else {
                        const issuesHtml = issues.slice(0, 5).map(issue => {
                            const color = issue.severity === 'critical' ? 'red' :
                                         issue.severity === 'warning' ? 'yellow' : 'blue';
                            const icon = issue.severity === 'critical' ? '🔴' :
                                        issue.severity === 'warning' ? '🟠' : '🔵';
                            return `
                                <div class="border-l-4 border-${color}-500 pl-3 py-2">
                                    <div class="text-${color}-400 font-semibold text-sm">
                                        ${icon} ${issue.category}
                                    </div>
                                    <div class="text-gray-300 text-xs mt-1">${issue.issue}</div>
                                </div>
                            `;
                        }).join('');
                        document.getElementById('issues-list').innerHTML = issuesHtml;
                    }

                    // Update top agents
                    const agents = data.top_agents || [];
                    if (agents.length === 0) {
                        document.getElementById('top-agents-list').innerHTML =
                            '<div class="text-gray-400 text-sm">No agent activity</div>';
                    } else {
                        const agentsHtml = agents.slice(0, 5).map(agent => `
                            <div class="flex justify-between items-center py-2 border-b border-gray-700">
                                <div class="flex-1">
                                    <div class="text-sm font-semibold text-gray-200">${agent.selected_agent}</div>
                                    <div class="text-xs text-gray-500">${agent.selections} selections</div>
                                </div>
                                <div class="text-right">
                                    <div class="text-sm text-green-400">${(agent.avg_confidence * 100).toFixed(1)}%</div>
                                    <div class="text-xs text-gray-500">${agent.avg_routing_ms.toFixed(0)}ms</div>
                                </div>
                            </div>
                        `).join('');
                        document.getElementById('top-agents-list').innerHTML = agentsHtml;
                    }

                    // Update recent activity
                    const activity = data.recent_activity || [];
                    if (activity.length === 0) {
                        document.getElementById('activity-list').innerHTML =
                            '<div class="text-gray-400 text-sm">No recent activity</div>';
                    } else {
                        const activityHtml = activity.slice(0, 10).map(item => {
                            const conf = (item.confidence_score * 100).toFixed(0);
                            const confColor = conf >= 95 ? 'green' : conf >= 85 ? 'yellow' : 'red';
                            return `
                                <div class="flex justify-between items-center py-2 border-b border-gray-700 text-sm">
                                    <div class="flex-1">
                                        <div class="text-gray-300">${item.selected_agent}</div>
                                        <div class="text-xs text-gray-500">${item.created_at}</div>
                                    </div>
                                    <div class="flex space-x-3">
                                        <span class="text-${confColor}-400 font-semibold">${conf}%</span>
                                        <span class="text-gray-500">${item.routing_time_ms}ms</span>
                                    </div>
                                </div>
                            `;
                        }).join('');
                        document.getElementById('activity-list').innerHTML = activityHtml;
                    }

                    // Update timestamp
                    const now = new Date();
                    document.getElementById('last-update').textContent =
                        now.toLocaleTimeString('en-US', { hour12: false });
                })
                .catch(err => {
                    console.error('Error fetching dashboard:', err);
                    document.querySelector('.live-indicator').classList.remove('bg-green-500');
                    document.querySelector('.live-indicator').classList.add('bg-red-500');
                });
        }

        // Initial load
        updateDashboard();

        // Auto-refresh every 5 seconds
        setInterval(updateDashboard, 5000);
    </script>
</body>
</html>
"""


def run_server(port=8000):
    """Run the dashboard server"""
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print("🎯 OmniClaude Web Dashboard")
    print("=" * 50)
    print(f"Server running at http://localhost:{port}")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
