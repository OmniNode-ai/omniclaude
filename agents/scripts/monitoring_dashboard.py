#!/usr/bin/env python3
"""
Monitoring Dashboard Data Generator

Generates comprehensive dashboard data for Phase 7 monitoring including:
- Real-time metrics aggregation
- Health status visualization data
- Alert summaries
- Performance trends
- Component-specific dashboards

Usage:
    python monitoring_dashboard.py [--format json|html] [--output path]
    python monitoring_dashboard.py --format json > dashboard.json
    python monitoring_dashboard.py --format html --output dashboard.html

ONEX Pattern: Compute node (pure transformation of monitoring data)
Performance Target: <500ms dashboard generation
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.monitoring import (
    collect_all_metrics,
    get_monitoring_summary,
    get_active_alerts,
    export_prometheus_metrics,
    AlertSeverity,
)
from lib.health_checker import check_system_health, get_overall_health_status, HealthCheckStatus
from lib.alert_manager import get_alert_statistics


async def generate_dashboard_data(time_window_minutes: int = 60) -> Dict[str, Any]:
    """Generate comprehensive dashboard data.

    Args:
        time_window_minutes: Time window for metrics aggregation

    Returns:
        Dictionary containing all dashboard data
    """
    print(f"Generating dashboard data (time window: {time_window_minutes} minutes)...", file=sys.stderr)

    # Collect all metrics
    print("Collecting metrics from all subsystems...", file=sys.stderr)
    metrics = await collect_all_metrics(time_window_minutes)

    # Get monitoring summary
    print("Getting monitoring summary...", file=sys.stderr)
    monitoring_summary = get_monitoring_summary()

    # Check system health
    print("Checking system health...", file=sys.stderr)
    health_results = await check_system_health()

    # Get alert statistics
    print("Getting alert statistics...", file=sys.stderr)
    alert_stats = get_alert_statistics(hours=24)

    # Get active alerts by severity
    print("Fetching active alerts...", file=sys.stderr)
    active_alerts = {
        "critical": [
            {
                "id": a.alert_id,
                "message": a.message,
                "component": a.component,
                "metric": a.metric_name,
                "value": a.actual_value,
                "threshold": a.threshold,
                "created_at": a.created_at.isoformat(),
                "labels": a.labels,
            }
            for a in get_active_alerts(severity=AlertSeverity.CRITICAL)
        ],
        "warning": [
            {
                "id": a.alert_id,
                "message": a.message,
                "component": a.component,
                "metric": a.metric_name,
                "value": a.actual_value,
                "threshold": a.threshold,
                "created_at": a.created_at.isoformat(),
                "labels": a.labels,
            }
            for a in get_active_alerts(severity=AlertSeverity.WARNING)
        ],
        "info": [
            {
                "id": a.alert_id,
                "message": a.message,
                "component": a.component,
                "metric": a.metric_name,
                "value": a.actual_value,
                "threshold": a.threshold,
                "created_at": a.created_at.isoformat(),
                "labels": a.labels,
            }
            for a in get_active_alerts(severity=AlertSeverity.INFO)
        ],
    }

    # Build comprehensive dashboard
    dashboard = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "time_window_minutes": time_window_minutes,
        "overview": {
            "overall_health": get_overall_health_status().value,
            "total_components": len(health_results),
            "healthy_components": sum(1 for h in health_results.values() if h.healthy),
            "degraded_components": sum(
                1 for h in health_results.values() if not h.healthy and h.status == HealthCheckStatus.DEGRADED
            ),
            "critical_components": sum(
                1 for h in health_results.values() if not h.healthy and h.status == HealthCheckStatus.CRITICAL
            ),
            "active_alerts": monitoring_summary["alerts"]["active_count"],
            "critical_alerts": monitoring_summary["alerts"]["critical_count"],
            "warning_alerts": monitoring_summary["alerts"]["warning_count"],
        },
        "health": {
            "status": get_overall_health_status().value,
            "components": {
                name: {
                    "healthy": result.healthy,
                    "status": result.status.value,
                    "message": result.message,
                    "check_duration_ms": result.check_duration_ms,
                    "last_check": result.timestamp.isoformat(),
                    "metadata": result.metadata,
                    "error": result.error,
                }
                for name, result in health_results.items()
            },
        },
        "metrics": metrics,
        "alerts": {"summary": alert_stats, "active": active_alerts, "monitoring_summary": monitoring_summary["alerts"]},
        "components": {
            "template_cache": _build_template_cache_dashboard(metrics),
            "parallel_generation": _build_parallel_generation_dashboard(metrics),
            "mixin_learning": _build_mixin_learning_dashboard(metrics),
            "pattern_matching": _build_pattern_matching_dashboard(metrics),
            "event_processing": _build_event_processing_dashboard(metrics),
        },
    }

    print("Dashboard data generated successfully", file=sys.stderr)
    return dashboard


def _build_template_cache_dashboard(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Build template cache dashboard data.

    Args:
        metrics: Collected metrics data

    Returns:
        Template cache dashboard data
    """
    cache_data = metrics.get("template_cache", {})

    return {
        "overview": {
            "overall_hit_rate": cache_data.get("overall_hit_rate", 0.0),
            "avg_load_time_ms": cache_data.get("avg_load_time_ms", 0.0),
            "total_templates": cache_data.get("total_templates", 0),
        },
        "by_type": cache_data.get("by_type", []),
        "status": "healthy" if cache_data.get("overall_hit_rate", 0) >= 0.8 else "degraded",
    }


def _build_parallel_generation_dashboard(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Build parallel generation dashboard data.

    Args:
        metrics: Collected metrics data

    Returns:
        Parallel generation dashboard data
    """
    parallel_data = metrics.get("parallel_generation", {})

    return {
        "overview": {
            "parallel_usage_rate": parallel_data.get("parallel_usage_rate", 0.0),
            "avg_speedup": parallel_data.get("avg_speedup", 0.0),
        },
        "by_phase": parallel_data.get("by_phase", []),
        "status": "healthy" if parallel_data.get("parallel_usage_rate", 0) >= 0.5 else "degraded",
    }


def _build_mixin_learning_dashboard(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Build mixin learning dashboard data.

    Args:
        metrics: Collected metrics data

    Returns:
        Mixin learning dashboard data
    """
    mixin_data = metrics.get("mixin_learning", {})

    return {
        "overview": {
            "overall_success_rate": mixin_data.get("overall_success_rate", 0.0),
            "avg_compatibility_score": mixin_data.get("avg_compatibility_score", 0.0),
        },
        "by_node_type": mixin_data.get("by_node_type", []),
        "status": "healthy" if mixin_data.get("overall_success_rate", 0) >= 0.9 else "degraded",
    }


def _build_pattern_matching_dashboard(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Build pattern matching dashboard data.

    Args:
        metrics: Collected metrics data

    Returns:
        Pattern matching dashboard data
    """
    pattern_data = metrics.get("pattern_matching", {})

    return {
        "overview": {
            "total_feedback": pattern_data.get("total_feedback_count", 0),
            "avg_confidence": pattern_data.get("avg_confidence", 0.0),
            "precision": pattern_data.get("precision", 0.0),
        },
        "by_pattern": pattern_data.get("by_pattern", []),
        "status": "healthy" if pattern_data.get("precision", 0) >= 0.85 else "degraded",
    }


def _build_event_processing_dashboard(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Build event processing dashboard data.

    Args:
        metrics: Collected metrics data

    Returns:
        Event processing dashboard data
    """
    event_data = metrics.get("event_processing", {})

    return {
        "overview": {
            "overall_success_rate": event_data.get("overall_success_rate", 0.0),
            "avg_latency_ms": event_data.get("avg_latency_ms", 0.0),
            "p95_latency_ms": event_data.get("p95_latency_ms", 0.0),
        },
        "by_event_type": event_data.get("by_event_type", []),
        "status": "healthy" if event_data.get("p95_latency_ms", 0) <= 200 else "degraded",
    }


def generate_html_dashboard(dashboard_data: Dict[str, Any]) -> str:
    """Generate HTML dashboard from data.

    Args:
        dashboard_data: Dashboard data dictionary

    Returns:
        HTML string
    """
    overview = dashboard_data["overview"]
    health = dashboard_data["health"]
    alerts = dashboard_data["alerts"]

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Phase 7 Monitoring Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            margin-bottom: 10px;
        }}
        .timestamp {{
            color: #666;
            font-size: 14px;
            margin-bottom: 30px;
        }}
        .overview {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .card h2 {{
            margin: 0 0 15px 0;
            font-size: 16px;
            color: #666;
            text-transform: uppercase;
            font-weight: 500;
        }}
        .metric {{
            font-size: 32px;
            font-weight: bold;
            color: #333;
        }}
        .status-healthy {{ color: #22c55e; }}
        .status-degraded {{ color: #f59e0b; }}
        .status-critical {{ color: #ef4444; }}
        .status-unknown {{ color: #6b7280; }}
        .component-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .component {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .component-name {{
            font-weight: 600;
            font-size: 18px;
            margin-bottom: 10px;
        }}
        .component-status {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
            text-transform: uppercase;
        }}
        .alert {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            border-left: 4px solid;
        }}
        .alert-critical {{ border-left-color: #ef4444; }}
        .alert-warning {{ border-left-color: #f59e0b; }}
        .alert-info {{ border-left-color: #3b82f6; }}
        .alert-message {{
            font-weight: 500;
            margin-bottom: 5px;
        }}
        .alert-details {{
            font-size: 14px;
            color: #666;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Phase 7 Monitoring Dashboard</h1>
        <div class="timestamp">Generated: {dashboard_data['generated_at']}</div>

        <div class="overview">
            <div class="card">
                <h2>Overall Health</h2>
                <div class="metric status-{overview['overall_health']}">{overview['overall_health'].upper()}</div>
            </div>
            <div class="card">
                <h2>Components</h2>
                <div class="metric">{overview['healthy_components']}/{overview['total_components']}</div>
                <div style="font-size: 14px; color: #666;">Healthy</div>
            </div>
            <div class="card">
                <h2>Active Alerts</h2>
                <div class="metric">{overview['active_alerts']}</div>
                <div style="font-size: 14px; color: #666;">{overview['critical_alerts']} Critical</div>
            </div>
        </div>

        <h2>Component Health</h2>
        <div class="component-grid">
"""

    # Add component health status
    for name, component in health["components"].items():
        status_class = f"status-{component['status']}"
        html += f"""
            <div class="component">
                <div class="component-name">{name.replace('_', ' ').title()}</div>
                <span class="component-status {status_class}">{component['status'].upper()}</span>
                <div style="margin-top: 10px; font-size: 14px; color: #666;">
                    {component['message']}
                </div>
            </div>
"""

    html += """
        </div>

        <h2>Active Alerts</h2>
"""

    # Add critical alerts
    if alerts["active"]["critical"]:
        html += "<h3 style='color: #ef4444;'>Critical</h3>"
        for alert in alerts["active"]["critical"]:
            html += f"""
            <div class="alert alert-critical">
                <div class="alert-message">{alert['message']}</div>
                <div class="alert-details">
                    Component: {alert['component']} | Metric: {alert['metric']} |
                    Value: {alert['value']:.2f} | Threshold: {alert['threshold']:.2f}
                </div>
            </div>
"""

    # Add warning alerts
    if alerts["active"]["warning"]:
        html += "<h3 style='color: #f59e0b;'>Warnings</h3>"
        for alert in alerts["active"]["warning"][:5]:  # Show first 5
            html += f"""
            <div class="alert alert-warning">
                <div class="alert-message">{alert['message']}</div>
                <div class="alert-details">
                    Component: {alert['component']} | Metric: {alert['metric']} |
                    Value: {alert['value']:.2f} | Threshold: {alert['threshold']:.2f}
                </div>
            </div>
"""

    if not alerts["active"]["critical"] and not alerts["active"]["warning"]:
        html += "<p style='color: #22c55e; font-weight: 500;'>No active alerts</p>"

    html += """
    </div>
</body>
</html>"""

    return html


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate Phase 7 monitoring dashboard data")
    parser.add_argument("--format", choices=["json", "html"], default="json", help="Output format (default: json)")
    parser.add_argument("--output", type=Path, help="Output file path (default: stdout)")
    parser.add_argument("--time-window", type=int, default=60, help="Time window in minutes for metrics (default: 60)")
    parser.add_argument("--prometheus", action="store_true", help="Output Prometheus-compatible metrics instead")

    args = parser.parse_args()

    if args.prometheus:
        # Export Prometheus metrics
        metrics = await export_prometheus_metrics()
        if args.output:
            args.output.write_text(metrics)
            print(f"Prometheus metrics written to {args.output}", file=sys.stderr)
        else:
            print(metrics)
        return

    # Generate dashboard data
    dashboard_data = await generate_dashboard_data(args.time_window)

    # Format output
    if args.format == "json":
        output = json.dumps(dashboard_data, indent=2)
    elif args.format == "html":
        output = generate_html_dashboard(dashboard_data)
    else:
        output = json.dumps(dashboard_data, indent=2)

    # Write output
    if args.output:
        args.output.write_text(output)
        print(f"Dashboard written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    asyncio.run(main())
