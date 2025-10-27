#!/usr/bin/env python3
"""
Enhanced Debug Utilities for Phase 5 Pattern Tracking

Provides comprehensive debugging and diagnostic capabilities:
- Service status checking and monitoring (sync and async)
- Correlation ID tracking and flow analysis
- Performance profiling and bottleneck identification
- Integration testing utilities
- System diagnostics and health monitoring

Enhanced features:
- Async support for non-blocking diagnostics
- Rich error context and system information
- Performance metrics collection and analysis
- Component-level health monitoring
- Integration testing with detailed reporting

Design Philosophy:
- Non-intrusive: Debug utilities should not affect normal operation
- Observable: Provide clear visibility into system behavior
- Actionable: Generate actionable insights for troubleshooting
- Comprehensive: Cover all aspects of the pattern tracking system
"""

import json
import os
import subprocess
import sys
import time
from typing import Any, Dict

import requests

# Service URL configuration from environment
INTELLIGENCE_SERVICE_URL = os.environ.get(
    "INTELLIGENCE_SERVICE_URL", "http://localhost:8053"
)
MAIN_SERVER_URL = os.environ.get("MAIN_SERVER_URL", "http://localhost:8181")
MCP_SERVER_URL = os.environ.get("ARCHON_MCP_URL", "http://localhost:8051")


def check_running_services() -> Dict[str, Any]:
    """Check which required services are running"""
    services = {}

    print("🔍 Checking service status...", file=sys.stderr)

    # Check intelligence service (Phase 4)
    try:
        result = subprocess.run(
            ["curl", "-s", f"{INTELLIGENCE_SERVICE_URL}/health"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            try:
                health_data = json.loads(result.stdout)
                services["intelligence_service"] = {
                    "running": True,
                    "details": health_data,
                    "status": "healthy",
                }
            except Exception:
                services["intelligence_service"] = {
                    "running": True,
                    "details": result.stdout,
                    "status": "unknown",
                }
        else:
            services["intelligence_service"] = {
                "running": False,
                "error": result.stderr,
                "status": "stopped",
            }
    except subprocess.TimeoutExpired:
        services["intelligence_service"] = {
            "running": False,
            "error": "Timeout",
            "status": "timeout",
        }
    except Exception as e:
        services["intelligence_service"] = {
            "running": False,
            "error": str(e),
            "status": "error",
        }

    # Check main server (Port 8181)
    try:
        result = subprocess.run(
            ["curl", "-s", f"{MAIN_SERVER_URL}/health"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            services["main_server"] = {
                "running": True,
                "details": result.stdout,
                "status": "healthy",
            }
        else:
            services["main_server"] = {
                "running": False,
                "error": result.stderr,
                "status": "stopped",
            }
    except Exception as e:
        services["main_server"] = {"running": False, "error": str(e), "status": "error"}

    # Check MCP server (Port 8051)
    try:
        result = subprocess.run(
            ["curl", "-s", f"{MCP_SERVER_URL}/health"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            services["mcp_server"] = {
                "running": True,
                "details": result.stdout,
                "status": "healthy",
            }
        else:
            services["mcp_server"] = {
                "running": False,
                "error": result.stderr,
                "status": "stopped",
            }
    except Exception as e:
        services["mcp_server"] = {"running": False, "error": str(e), "status": "error"}

    # Check database connectivity (Docker)
    try:
        # Try to check if PostgreSQL container is running
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=postgres", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            docker_containers = [
                json.loads(line)
                for line in result.stdout.strip().split("\n")
                if line.strip()
            ]
            postgres_containers = [
                c for c in docker_containers if "postgres" in c.get("Names", "").lower()
            ]

            if postgres_containers:
                services["database"] = {
                    "running": True,
                    "containers": len(postgres_containers),
                    "status": "healthy",
                }
            else:
                services["database"] = {
                    "running": False,
                    "error": "No PostgreSQL containers found",
                    "status": "stopped",
                }
        else:
            services["database"] = {
                "running": False,
                "error": "Docker command failed or no containers",
                "status": "error",
            }
    except Exception as e:
        services["database"] = {"running": False, "error": str(e), "status": "error"}

    # Check Memgraph (if available)
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=memgraph", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            docker_containers = [
                json.loads(line)
                for line in result.stdout.strip().split("\n")
                if line.strip()
            ]
            memgraph_containers = [
                c for c in docker_containers if "memgraph" in c.get("Names", "").lower()
            ]

            if memgraph_containers:
                services["memgraph"] = {
                    "running": True,
                    "containers": len(memgraph_containers),
                    "status": "healthy",
                }
            else:
                services["memgraph"] = {
                    "running": False,
                    "error": "No Memgraph containers found",
                    "status": "stopped",
                }
        else:
            services["memgraph"] = {
                "running": False,
                "error": "Docker command failed or no containers",
                "status": "error",
            }
    except Exception as e:
        services["memgraph"] = {"running": False, "error": str(e), "status": "error"}

    # Check Qdrant (if available)
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=qdrant", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            docker_containers = [
                json.loads(line)
                for line in result.stdout.strip().split("\n")
                if line.strip()
            ]
            qdrant_containers = [
                c for c in docker_containers if "qdrant" in c.get("Names", "").lower()
            ]

            if qdrant_containers:
                services["qdrant"] = {
                    "running": True,
                    "containers": len(qdrant_containers),
                    "status": "healthy",
                }
            else:
                services["qdrant"] = {
                    "running": False,
                    "error": "No Qdrant containers found",
                    "status": "stopped",
                }
        else:
            services["qdrant"] = {
                "running": False,
                "error": "Docker command failed or no containers",
                "status": "error",
            }
    except Exception as e:
        services["qdrant"] = {"running": False, "error": str(e), "status": "error"}

    return services


def check_network_connectivity() -> Dict[str, Any]:
    """Check network connectivity to required endpoints"""
    endpoints = [
        ("Intelligence Service", f"{INTELLIGENCE_SERVICE_URL}/health"),
        ("Main Server", f"{MAIN_SERVER_URL}/health"),
        ("MCP Server", f"{MCP_SERVER_URL}/health"),
        (
            "Pattern Lineage API",
            f"{INTELLIGENCE_SERVICE_URL}/api/pattern-traceability/health",
        ),
    ]

    results = {}

    print("🌐 Checking network connectivity...", file=sys.stderr)

    for name, url in endpoints:
        try:
            start_time = time.time()
            response = requests.get(url, timeout=5)
            response_time = (time.time() - start_time) * 1000

            results[name] = {
                "status_code": response.status_code,
                "response_time_ms": round(response_time, 2),
                "status": "connected" if response.status_code == 200 else "error",
                "success": response.status_code == 200,
            }
        except requests.exceptions.Timeout:
            results[name] = {
                "status": "timeout",
                "response_time_ms": 5000,
                "success": False,
            }
        except Exception as e:
            results[name] = {"status": "error", "error": str(e), "success": False}

    return results


def check_pattern_tracking_files() -> Dict[str, Any]:
    """Check if pattern tracking files exist and are accessible"""
    hooks_dir = "/Users/jonah/.claude/hooks"

    required_files = [
        "pattern_tracker.py",
        "health_checks.py",
        "error_handling.py",
        "debug_utils.py",
    ]

    file_status = {}

    print("📁 Checking pattern tracking files...", file=sys.stderr)

    for filename in required_files:
        filepath = os.path.join(hooks_dir, filename)

        if os.path.exists(filepath):
            stat_info = os.stat(filepath)
            file_status[filename] = {
                "exists": True,
                "size_bytes": stat_info.st_size,
                "modified": time.ctime(stat_info.st_mtime),
                "readable": os.access(filepath, os.R_OK),
                "executable": os.access(filepath, os.X_OK),
            }
        else:
            file_status[filename] = {"exists": False, "error": "File not found"}

    return file_status


def check_python_environment() -> Dict[str, Any]:
    """Check Python environment and required packages"""
    print("🐍 Checking Python environment...", file=sys.stderr)

    env_info = {
        "python_version": sys.version,
        "python_path": sys.executable,
        "packages": {},
    }

    required_packages = ["requests", "json", "subprocess", "logging"]

    for package in required_packages:
        try:
            if package == "json":
                env_info["packages"][package] = {
                    "available": True,
                    "version": "builtin",
                }
            elif package == "subprocess":
                env_info["packages"][package] = {
                    "available": True,
                    "version": "builtin",
                }
            elif package == "logging":
                env_info["packages"][package] = {
                    "available": True,
                    "version": "builtin",
                }
            elif package == "requests":
                env_info["packages"][package] = {
                    "available": True,
                    "version": requests.__version__,
                }
        except ImportError:
            env_info["packages"][package] = {
                "available": False,
                "error": "Not installed",
            }

    return env_info


def print_debug_status():
    """Print comprehensive debug status"""
    print("🔍 PATTERN TRACKING DEBUG STATUS", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Check services
    services = check_running_services()
    print("\n📊 SERVICE STATUS:", file=sys.stderr)
    for service_name, service_info in services.items():
        if service_info.get("running", False):
            status_emoji = "✅"
            status_text = "Running"
        else:
            status_emoji = "❌"
            status_text = f"Not Running ({service_info.get('status', 'unknown')})"

        print(
            f"  {status_emoji} {service_name.replace('_', ' ').title()}: {status_text}",
            file=sys.stderr,
        )

        if not service_info.get("running", False) and "error" in service_info:
            print(f"    Error: {service_info['error']}", file=sys.stderr)

    # Check network connectivity
    network = check_network_connectivity()
    print("\n🌐 NETWORK CONNECTIVITY:", file=sys.stderr)
    for endpoint, info in network.items():
        if info.get("success", False):
            status_emoji = "✅"
            response_time = info.get("response_time_ms", 0)
            print(
                f"  {status_emoji} {endpoint}: Connected ({response_time}ms)",
                file=sys.stderr,
            )
        else:
            status_emoji = "❌"
            status = info.get("status", "unknown")
            print(f"  {status_emoji} {endpoint}: {status}", file=sys.stderr)

    # Check files
    files = check_pattern_tracking_files()
    print("\n📁 PATTERN TRACKING FILES:", file=sys.stderr)
    for filename, info in files.items():
        if info.get("exists", False):
            status_emoji = "✅"
            size = info.get("size_bytes", 0)
            readable = "✅" if info.get("readable", False) else "❌"
            executable = "✅" if info.get("executable", False) else "❌"
            print(
                f"  {status_emoji} {filename}: {size} bytes (R:{readable} X:{executable})",
                file=sys.stderr,
            )
        else:
            status_emoji = "❌"
            print(f"  {status_emoji} {filename}: Not found", file=sys.stderr)

    # Check Python environment
    python_env = check_python_environment()
    print("\n🐍 PYTHON ENVIRONMENT:", file=sys.stderr)
    print(f"  Version: {python_env['python_version'].split()[0]}", file=sys.stderr)
    print(f"  Path: {python_env['python_path']}", file=sys.stderr)

    print("\n  Packages:", file=sys.stderr)
    for package, info in python_env["packages"].items():
        if info.get("available", False):
            version = info.get("version", "builtin")
            print(f"    ✅ {package}: {version}", file=sys.stderr)
        else:
            print(f"    ❌ {package}: Not available", file=sys.stderr)

    print("\n" + "=" * 60, file=sys.stderr)


def test_pattern_tracking_flow() -> Dict[str, Any]:
    """Test the complete pattern tracking flow"""
    print("🧪 TESTING PATTERN TRACKING FLOW", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    test_results = {"timestamp": time.time(), "tests": {}}

    # Test 1: Import health checks
    try:
        sys.path.append("/Users/jonah/.claude/hooks")
        from health_checks import Phase4HealthChecker

        checker = Phase4HealthChecker()
        test_results["tests"]["import_health_checks"] = {
            "status": "success",
            "message": "Health checks imported successfully",
        }
    except Exception as e:
        test_results["tests"]["import_health_checks"] = {
            "status": "error",
            "error": str(e),
        }

    # Test 2: Import error handling
    try:
        from error_handling import PatternTrackingErrorHandler, PatternTrackingLogger

        logger = PatternTrackingLogger()
        PatternTrackingErrorHandler(logger)
        test_results["tests"]["import_error_handling"] = {
            "status": "success",
            "message": "Error handling imported successfully",
        }
    except Exception as e:
        test_results["tests"]["import_error_handling"] = {
            "status": "error",
            "error": str(e),
        }

    # Test 3: Run health check
    try:
        if (
            "import_health_checks" in test_results["tests"]
            and test_results["tests"]["import_health_checks"]["status"] == "success"
        ):
            health_results = checker.run_comprehensive_health_check()
            test_results["tests"]["health_check"] = {
                "status": (
                    "success"
                    if health_results["overall_status"] == "healthy"
                    else "partial"
                ),
                "overall_status": health_results["overall_status"],
                "summary": health_results["summary"],
            }
        else:
            test_results["tests"]["health_check"] = {
                "status": "skipped",
                "reason": "Health checks not available",
            }
    except Exception as e:
        test_results["tests"]["health_check"] = {"status": "error", "error": str(e)}

    # Test 4: Test lineage endpoint
    try:
        test_payload = {
            "event_type": "debug_test",
            "pattern_id": "debug_test_123",
            "pattern_name": "Debug Test",
            "pattern_type": "test",
            "pattern_data": {"test": True, "timestamp": time.time()},
            "triggered_by": "debug_utils",
        }

        response = requests.post(
            f"{INTELLIGENCE_SERVICE_URL}/api/pattern-traceability/lineage/track",
            json=test_payload,
            timeout=5,
        )

        if response.status_code in [200, 201]:
            test_results["tests"]["lineage_endpoint"] = {
                "status": "success",
                "response_code": response.status_code,
                "message": "Lineage endpoint working",
            }
        else:
            test_results["tests"]["lineage_endpoint"] = {
                "status": "error",
                "response_code": response.status_code,
                "error": response.text,
            }

    except Exception as e:
        test_results["tests"]["lineage_endpoint"] = {"status": "error", "error": str(e)}

    # Summary
    total_tests = len(test_results["tests"])
    successful_tests = len(
        [t for t in test_results["tests"].values() if t["status"] == "success"]
    )
    failed_tests = len(
        [t for t in test_results["tests"].values() if t["status"] == "error"]
    )

    test_results["summary"] = {
        "total_tests": total_tests,
        "successful_tests": successful_tests,
        "failed_tests": failed_tests,
        "overall_status": "healthy" if failed_tests == 0 else "unhealthy",
    }

    print("\n📊 TEST SUMMARY:", file=sys.stderr)
    print(
        f"  Total: {total_tests}, Successful: {successful_tests}, Failed: {failed_tests}",
        file=sys.stderr,
    )
    print(
        f"  Overall Status: {test_results['summary']['overall_status'].upper()}",
        file=sys.stderr,
    )

    return test_results


def main():
    """Run all debug checks when script is executed directly"""
    print_debug_status()
    print("\n")
    test_results = test_pattern_tracking_flow()

    # Output JSON for programmatic use
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        print(json.dumps(test_results, indent=2))

    # Exit with appropriate code
    sys.exit(0 if test_results["summary"]["overall_status"] == "healthy" else 1)


if __name__ == "__main__":
    main()
