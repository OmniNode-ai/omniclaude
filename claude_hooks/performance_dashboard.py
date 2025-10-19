#!/usr/bin/env python3
"""
Performance Dashboard for Pattern Tracking

Provides real-time monitoring and visualization of pattern tracking performance.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles
from enhanced_pattern_tracker import EnhancedPatternTracker, get_enhanced_tracker


class PerformanceDashboard:
    """Real-time performance dashboard for pattern tracking."""

    def __init__(self, tracker: Optional[EnhancedPatternTracker] = None):
        self.tracker = tracker or get_enhanced_tracker()
        self.dashboard_file = (
            Path.home() / ".claude" / "hooks" / "logs" / "performance-dashboard.html"
        )
        self.metrics_file = (
            Path.home() / ".claude" / "hooks" / "logs" / "performance-metrics.jsonl"
        )
        self._running = False

    async def start_monitoring(self, interval_seconds: float = 5.0):
        """Start real-time monitoring dashboard."""
        self._running = True
        self.dashboard_file.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

        # Create dashboard HTML
        await self._create_dashboard_html()

        # Start monitoring loop
        await self._monitoring_loop(interval_seconds)

    async def stop_monitoring(self):
        """Stop monitoring."""
        self._running = False

    async def _create_dashboard_html(self):
        """Create HTML dashboard."""
        html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pattern Tracking Performance Dashboard</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .dashboard {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .metric-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .metric-title {
            font-size: 14px;
            color: #666;
            margin-bottom: 5px;
        }
        .metric-value {
            font-size: 24px;
            font-weight: bold;
            color: #333;
        }
        .success {
            color: #10b981;
        }
        .warning {
            color: #f59e0b;
        }
        .danger {
            color: #ef4444;
        }
        .chart-container {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .logs-section {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .log-entry {
            padding: 10px;
            border-bottom: 1px solid #eee;
            font-family: monospace;
            font-size: 12px;
        }
        .log-entry:last-child {
            border-bottom: none;
        }
        .timestamp {
            color: #666;
            margin-right: 10px;
        }
        .refresh-btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin-bottom: 20px;
        }
        .refresh-btn:hover {
            background: #5a67d8;
        }
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 5px;
        }
        .status-online {
            background-color: #10b981;
        }
        .status-offline {
            background-color: #ef4444;
        }
        .progress-bar {
            width: 100%;
            height: 20px;
            background-color: #e5e7eb;
            border-radius: 10px;
            overflow: hidden;
            margin: 5px 0;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #10b981, #3b82f6);
            transition: width 0.3s ease;
        }
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1>Pattern Tracking Performance Dashboard</h1>
            <p>Real-time monitoring of pattern tracking system performance</p>
        </div>

        <button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-title">System Status</div>
                <div class="metric-value">
                    <span class="status-indicator status-online"></span>
                    <span id="status">Online</span>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-title">Total Operations</div>
                <div class="metric-value" id="total-ops">0</div>
            </div>

            <div class="metric-card">
                <div class="metric-title">Success Rate</div>
                <div class="metric-value success" id="success-rate">0%</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="success-progress" style="width: 0%"></div>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-title">Avg Processing Time</div>
                <div class="metric-value" id="avg-time">0ms</div>
            </div>

            <div class="metric-card">
                <div class="metric-title">Cache Hit Rate</div>
                <div class="metric-value" id="cache-rate">0%</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="cache-progress" style="width: 0%"></div>
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-title">Memory Usage</div>
                <div class="metric-value" id="memory-usage">0MB</div>
            </div>

            <div class="metric-card">
                <div class="metric-title">Operations/Second</div>
                <div class="metric-value" id="ops-per-sec">0</div>
            </div>

            <div class="metric-card">
                <div class="metric-title">API Response Time</div>
                <div class="metric-value" id="api-time">0ms</div>
            </div>
        </div>

        <div class="chart-container">
            <h3>Recent Performance (Last 60 seconds)</h3>
            <div id="recent-metrics">
                <p>Loading performance data...</p>
            </div>
        </div>

        <div class="logs-section">
            <h3>Recent Logs</h3>
            <div id="logs-container">
                <p>Loading logs...</p>
            </div>
        </div>
    </div>

    <script>
        // Auto-refresh every 5 seconds
        setInterval(() => {
            location.reload();
        }, 5000);

        // Load and display metrics
        async function loadMetrics() {
            try {
                const response = await fetch('performance-data.json');
                const data = await response.json();

                if (data.metrics) {
                    document.getElementById('total-ops').textContent = data.metrics.total_operations;
                    document.getElementById('success-rate').textContent = data.metrics.get_success_rate?.toFixed(1) + '%' || '0%';
                    document.getElementById('success-progress').style.width = data.metrics.get_success_rate + '%';
                    document.getElementById('avg-time').textContent = data.metrics.avg_processing_time_ms?.toFixed(1) + 'ms' || '0ms';
                    document.getElementById('cache-rate').textContent = data.metrics.get_cache_hit_rate?.toFixed(1) + '%' || '0%';
                    document.getElementById('cache-progress').style.width = data.metrics.get_cache_hit_rate + '%';
                    document.getElementById('memory-usage').textContent = data.metrics.memory_usage_mb?.toFixed(1) + 'MB' || '0MB';
                }

                if (data.recent) {
                    document.getElementById('ops-per-sec').textContent = data.recent.operations_per_second?.toFixed(1) || '0';
                    document.getElementById('api-time').textContent = data.recent.avg_time_ms?.toFixed(1) + 'ms' || '0ms';
                }
            } catch (e) {
                console.error('Error loading metrics:', e);
            }
        }

        // Load metrics on page load
        loadMetrics();
    </script>
</body>
</html>
        """

        async with aiofiles.open(self.dashboard_file, "w") as f:
            await f.write(html_content)

        print(f"Dashboard created: {self.dashboard_file}")

    async def _monitoring_loop(self, interval_seconds: float):
        """Monitoring loop to collect and store metrics."""
        while self._running:
            try:
                # Collect metrics
                summary = self.tracker.get_performance_summary()

                # Store metrics
                await self._store_metrics(summary)

                # Update performance data file for dashboard
                await self._update_performance_data(summary)

                # Sleep for interval
                await asyncio.sleep(interval_seconds)

            except Exception as e:
                print(f"Error in monitoring loop: {e}")
                await asyncio.sleep(interval_seconds)

    async def _store_metrics(self, summary: Dict[str, Any]):
        """Store metrics in log file."""
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = {
            "timestamp": timestamp,
            "metrics": summary["metrics"].__dict__,
            "recent_performance": summary["recent_performance"],
            "cache_stats": summary["cache_stats"],
            "connection_pool": summary["connection_pool"],
            "batch_processing": summary["batch_processing"],
        }

        async with aiofiles.open(self.metrics_file, "a") as f:
            await f.write(json.dumps(log_entry) + "\n")

    async def _update_performance_data(self, summary: Dict[str, Any]):
        """Update performance data for dashboard."""
        performance_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "total_operations": summary["metrics"].total_operations,
                "get_success_rate": summary["metrics"].get_success_rate(),
                "avg_processing_time_ms": summary["metrics"].avg_processing_time_ms,
                "get_cache_hit_rate": summary["metrics"].get_cache_hit_rate(),
                "memory_usage_mb": summary["metrics"].memory_usage_mb,
                "avg_api_response_time_ms": summary["metrics"].avg_api_response_time_ms,
            },
            "recent": summary["recent_performance"],
            "cache_stats": summary["cache_stats"],
            "connection_pool": summary["connection_pool"],
            "batch_processing": summary["batch_processing"],
        }

        data_file = self.dashboard_file.parent / "performance-data.json"
        async with aiofiles.open(data_file, "w") as f:
            await f.write(json.dumps(performance_data, indent=2))

    async def generate_performance_report(
        self, duration_minutes: int = 60
    ) -> Dict[str, Any]:
        """Generate performance report for specified duration."""
        # Read metrics from log file
        metrics_data = []
        try:
            async with aiofiles.open(self.metrics_file, "r") as f:
                async for line in f:
                    if line.strip():
                        metrics_data.append(json.loads(line))
        except FileNotFoundError:
            return {"error": "No metrics data available"}

        # Filter by time window
        cutoff_time = datetime.now(timezone.utc).timestamp() - (duration_minutes * 60)
        recent_metrics = [
            m
            for m in metrics_data
            if datetime.fromisoformat(m["timestamp"]).timestamp() > cutoff_time
        ]

        if not recent_metrics:
            return {"error": f"No data available for last {duration_minutes} minutes"}

        # Calculate aggregate statistics
        total_ops = sum(m["metrics"]["total_operations"] for m in recent_metrics)
        total_success = sum(
            m["metrics"]["successful_operations"] for m in recent_metrics
        )
        total_failures = sum(m["metrics"]["failed_operations"] for m in recent_metrics)

        avg_processing_time = sum(
            m["metrics"]["avg_processing_time_ms"] for m in recent_metrics
        ) / len(recent_metrics)
        avg_cache_hit_rate = sum(
            m["metrics"]["get_cache_hit_rate"]() for m in recent_metrics
        ) / len(recent_metrics)

        return {
            "report_period_minutes": duration_minutes,
            "data_points": len(recent_metrics),
            "total_operations": total_ops,
            "successful_operations": total_success,
            "failed_operations": total_failures,
            "overall_success_rate": (
                (total_success / total_ops * 100) if total_ops > 0 else 0
            ),
            "average_processing_time_ms": avg_processing_time,
            "average_cache_hit_rate": avg_cache_hit_rate,
            "peak_memory_usage_mb": max(
                m["metrics"]["memory_usage_mb"] for m in recent_metrics
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def cleanup_old_metrics(self, retention_days: int = 7):
        """Clean up old metrics data."""
        cutoff_time = datetime.now(timezone.utc).timestamp() - (
            retention_days * 24 * 3600
        )

        try:
            # Read all data
            all_data = []
            async with aiofiles.open(self.metrics_file, "r") as f:
                async for line in f:
                    if line.strip():
                        all_data.append(json.loads(line))

            # Filter and rewrite
            recent_data = [
                d
                for d in all_data
                if datetime.fromisoformat(d["timestamp"]).timestamp() > cutoff_time
            ]

            async with aiofiles.open(self.metrics_file, "w") as f:
                for entry in recent_data:
                    await f.write(json.dumps(entry) + "\n")

            print(f"Cleaned up metrics data, kept {len(recent_data)} entries")

        except Exception as e:
            print(f"Error cleaning up metrics: {e}")


async def main():
    """Main function to start performance monitoring."""
    print("🚀 Starting Pattern Tracking Performance Dashboard...")

    # Create and start dashboard
    dashboard = PerformanceDashboard()

    try:
        await dashboard.start_monitoring(interval_seconds=5.0)
        print(f"✅ Dashboard started: {dashboard.dashboard_file}")
        print("📊 Open the HTML file in your browser to view metrics")
        print("⏹️  Press Ctrl+C to stop monitoring")

        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n⏹️  Stopping dashboard...")
        await dashboard.stop_monitoring()
        print("✅ Dashboard stopped")


if __name__ == "__main__":
    asyncio.run(main())
