#!/usr/bin/env python3
"""
Debug Loop Health Check - Execution Script

Performs comprehensive health check of debug loop infrastructure:
- PostgreSQL database connectivity
- STF table status and count
- Model catalog status and count
- Latest STF timestamp
- System readiness status

Usage:
    python3 execute.py

Output:
    Formatted health status with traffic light indicators (🟢/🟡/🔴)
    Structured JSON for programmatic consumption

Exit Codes:
    0 - All systems healthy
    1 - One or more components degraded
    2 - Critical failure (database unreachable)
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add project root to path for imports - dynamic path resolution
# This skill is typically in ~/.claude/skills/debug-loop/debug-loop-health/
# We need to find the omniclaude repository root
if os.environ.get("OMNICLAUDE_PATH"):
    REPO_ROOT = Path(os.environ.get("OMNICLAUDE_PATH"))
    sys.path.insert(0, str(REPO_ROOT))
else:
    # Try common locations
    for candidate in [
        Path.home() / "Code" / "omniclaude",
        Path("/Users") / os.environ.get("USER", "unknown") / "Code" / "omniclaude",
    ]:
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            break
    else:
        print(
            "❌ Cannot find omniclaude repository. Set OMNICLAUDE_PATH environment variable."
        )
        sys.exit(2)

try:
    import asyncpg
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError as e:
    print(f"❌ Missing required dependency: {e}")
    print("\nInstall with: pip install asyncpg rich")
    sys.exit(2)

# Import config after dependencies check
try:
    from config import settings
except ImportError as e:
    print(f"❌ Cannot import config module: {e}")
    print("Ensure config module is available in omniclaude")
    sys.exit(2)


class DebugLoopHealthCheck:
    """
    Debug loop infrastructure health checker.

    Verifies PostgreSQL connectivity and checks critical tables for
    debug loop functionality.
    """

    def __init__(self):
        """Initialize health checker with environment configuration."""
        # Database configuration from Pydantic Settings
        self.db_host = settings.postgres_host
        self.db_port = settings.postgres_port
        self.db_name = settings.postgres_database
        self.db_user = settings.postgres_user
        self.db_password = settings.postgres_password

        # Rich console for formatted output
        self.console = Console()

        # Health status tracking
        self.health_data: Dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "database": {"status": "unknown", "details": {}},
            "stf_table": {"status": "unknown", "details": {}},
            "model_catalog": {"status": "unknown", "details": {}},
            "overall_status": "unknown",
        }

    async def check_database_connectivity(self) -> bool:
        """
        Test PostgreSQL database connection.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Verify password is set
            if not self.db_password:
                self.health_data["database"]["status"] = "error"
                self.health_data["database"]["details"] = {
                    "error": "POSTGRES_PASSWORD not set in environment",
                    "hint": "Run: source .env",
                }
                return False

            # Attempt connection
            conn = await asyncpg.connect(
                host=self.db_host,
                port=int(self.db_port),
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                timeout=10,
            )

            # Test query
            version = await conn.fetchval("SELECT version()")

            await conn.close()

            # Success
            self.health_data["database"]["status"] = "healthy"
            self.health_data["database"]["details"] = {
                "host": self.db_host,
                "port": self.db_port,
                "database": self.db_name,
                "version": version.split(",")[0] if version else "unknown",
            }
            return True

        except asyncpg.InvalidPasswordError:
            self.health_data["database"]["status"] = "error"
            self.health_data["database"]["details"] = {
                "error": "Authentication failed - invalid password",
                "hint": "Verify POSTGRES_PASSWORD in .env",
            }
            return False

        except asyncpg.CannotConnectNowError:
            self.health_data["database"]["status"] = "error"
            self.health_data["database"]["details"] = {
                "error": "Connection refused",
                "hint": f"Verify PostgreSQL is running at {self.db_host}:{self.db_port}",
            }
            return False

        except Exception as e:
            self.health_data["database"]["status"] = "error"
            self.health_data["database"]["details"] = {
                "error": str(e),
                "type": type(e).__name__,
            }
            return False

    async def check_stf_table(self) -> bool:
        """
        Check debug_transform_functions table status.

        Returns:
            True if table accessible and has data, False otherwise
        """
        try:
            conn = await asyncpg.connect(
                host=self.db_host,
                port=int(self.db_port),
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                timeout=10,
            )

            # Check table exists and get count
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM debug_transform_functions"
            )

            # Get latest STF creation time
            latest_created = await conn.fetchval(
                """
                SELECT created_at
                FROM debug_transform_functions
                ORDER BY created_at DESC
                LIMIT 1
                """
            )

            await conn.close()

            # Success
            status = "healthy" if count > 0 else "warning"
            self.health_data["stf_table"]["status"] = status
            self.health_data["stf_table"]["details"] = {
                "count": count,
                "latest_created": (
                    latest_created.isoformat() if latest_created else None
                ),
                "has_templates": count > 0,
            }
            return True

        except asyncpg.UndefinedTableError:
            self.health_data["stf_table"]["status"] = "error"
            self.health_data["stf_table"]["details"] = {
                "error": "Table does not exist",
                "hint": "May need to run database migrations",
            }
            return False

        except Exception as e:
            self.health_data["stf_table"]["status"] = "error"
            self.health_data["stf_table"]["details"] = {
                "error": str(e),
                "type": type(e).__name__,
            }
            return False

    async def check_model_catalog(self) -> bool:
        """
        Check model_price_catalog table status.

        Returns:
            True if table accessible and has data, False otherwise
        """
        try:
            conn = await asyncpg.connect(
                host=self.db_host,
                port=int(self.db_port),
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                timeout=10,
            )

            # Check table exists and get count
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM model_price_catalog WHERE is_active = true"
            )

            # Get active providers
            providers = await conn.fetch(
                """
                SELECT DISTINCT provider, COUNT(*) as model_count
                FROM model_price_catalog
                WHERE is_active = true
                GROUP BY provider
                ORDER BY provider
                """
            )

            await conn.close()

            # Success
            status = "healthy" if count > 0 else "warning"
            self.health_data["model_catalog"]["status"] = status
            self.health_data["model_catalog"]["details"] = {
                "active_models": count,
                "providers": [dict(p) for p in providers] if providers else [],
                "has_models": count > 0,
            }
            return True

        except asyncpg.UndefinedTableError:
            self.health_data["model_catalog"]["status"] = "error"
            self.health_data["model_catalog"]["details"] = {
                "error": "Table does not exist",
                "hint": "May need to run database migrations",
            }
            return False

        except Exception as e:
            self.health_data["model_catalog"]["status"] = "error"
            self.health_data["model_catalog"]["details"] = {
                "error": str(e),
                "type": type(e).__name__,
            }
            return False

    async def run_health_check(self) -> Dict[str, Any]:
        """
        Run complete health check.

        Returns:
            Health status dictionary with all component results
        """
        # Check database connectivity
        db_ok = await self.check_database_connectivity()

        if not db_ok:
            # If database is unreachable, skip other checks
            self.health_data["overall_status"] = "error"
            return self.health_data

        # Check STF table
        stf_ok = await self.check_stf_table()

        # Check model catalog
        model_ok = await self.check_model_catalog()

        # Determine overall status
        if all([db_ok, stf_ok, model_ok]):
            if (
                self.health_data["stf_table"]["status"] == "healthy"
                and self.health_data["model_catalog"]["status"] == "healthy"
            ):
                self.health_data["overall_status"] = "healthy"
            else:
                self.health_data["overall_status"] = "warning"
        else:
            self.health_data["overall_status"] = "error"

        return self.health_data

    def format_output(self) -> None:
        """
        Format and display health check results with Rich library.
        """
        # Determine overall status emoji
        status_emoji = {
            "healthy": "🟢",
            "warning": "🟡",
            "error": "🔴",
            "unknown": "⚪",
        }

        overall_emoji = status_emoji.get(self.health_data["overall_status"], "⚪")

        # Create title
        title = Text()
        title.append(f"{overall_emoji} Debug Loop Health Check", style="bold white")

        # Create table
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Component", style="cyan", width=20)
        table.add_column("Status", style="white")

        # Database row
        db_status = self.health_data["database"]["status"]
        db_emoji = status_emoji.get(db_status, "⚪")
        if db_status == "healthy":
            details = self.health_data["database"]["details"]
            db_text = (
                f"Connected ({details['host']}:{details['port']}/{details['database']})"
            )
        elif db_status == "error":
            details = self.health_data["database"]["details"]
            db_text = f"Error: {details.get('error', 'Unknown')}"
        else:
            db_text = "Unknown"

        table.add_row("PostgreSQL", f"{db_emoji} {db_text}")

        # STF table row
        stf_status = self.health_data["stf_table"]["status"]
        stf_emoji = status_emoji.get(stf_status, "⚪")
        if stf_status in ["healthy", "warning"]:
            details = self.health_data["stf_table"]["details"]
            count = details.get("count", 0)
            stf_text = f"{count} template{'s' if count != 1 else ''} available"
            if count == 0:
                stf_text += " (empty but accessible)"
        elif stf_status == "error":
            details = self.health_data["stf_table"]["details"]
            stf_text = f"Error: {details.get('error', 'Unknown')}"
        else:
            stf_text = "Unknown"

        table.add_row("STF Table", f"{stf_emoji} {stf_text}")

        # Model catalog row
        model_status = self.health_data["model_catalog"]["status"]
        model_emoji = status_emoji.get(model_status, "⚪")
        if model_status in ["healthy", "warning"]:
            details = self.health_data["model_catalog"]["details"]
            count = details.get("active_models", 0)
            model_text = f"{count} active model{'s' if count != 1 else ''}"
            providers = details.get("providers", [])
            if providers:
                provider_names = [p["provider"] for p in providers]
                model_text += f" ({', '.join(provider_names)})"
        elif model_status == "error":
            details = self.health_data["model_catalog"]["details"]
            model_text = f"Error: {details.get('error', 'Unknown')}"
        else:
            model_text = "Unknown"

        table.add_row("Model Catalog", f"{model_emoji} {model_text}")

        # Latest STF timestamp row
        if stf_status in ["healthy", "warning"] and self.health_data["stf_table"][
            "details"
        ].get("latest_created"):
            latest = datetime.fromisoformat(
                self.health_data["stf_table"]["details"]["latest_created"]
            )
            now = datetime.now(UTC)
            delta = now - latest

            # Format time delta
            if delta.total_seconds() < 60:
                time_ago = "just now"
            elif delta.total_seconds() < 3600:
                minutes = int(delta.total_seconds() / 60)
                time_ago = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
            elif delta.total_seconds() < 86400:
                hours = int(delta.total_seconds() / 3600)
                time_ago = f"{hours} hour{'s' if hours != 1 else ''} ago"
            else:
                days = int(delta.total_seconds() / 86400)
                time_ago = f"{days} day{'s' if days != 1 else ''} ago"

            table.add_row(
                "Latest STF",
                f"🕐 Created {time_ago} ({latest.strftime('%Y-%m-%d %H:%M UTC')})",
            )

        # Overall status row
        overall_text = self.health_data["overall_status"].upper()
        if self.health_data["overall_status"] == "healthy":
            overall_style = "bold green"
        elif self.health_data["overall_status"] == "warning":
            overall_style = "bold yellow"
        else:
            overall_style = "bold red"

        table.add_row(
            "System Status",
            Text(f"{overall_emoji} {overall_text}", style=overall_style),
        )

        # Display panel with table
        panel = Panel(
            table,
            title=title,
            border_style="blue",
            padding=(1, 2),
        )

        self.console.print()
        self.console.print(panel)

        # Add footer message
        if self.health_data["overall_status"] == "healthy":
            self.console.print("\n✨ Ready for debugging! 🚀\n", style="bold green")
        elif self.health_data["overall_status"] == "warning":
            self.console.print(
                "\n⚠️  System functional but some components are degraded\n",
                style="bold yellow",
            )
        else:
            self.console.print(
                "\n❌ System not ready - fix errors before debugging\n",
                style="bold red",
            )


async def main():
    """Main entry point for health check execution."""
    checker = DebugLoopHealthCheck()

    try:
        # Run health check
        health_data = await checker.run_health_check()

        # Display formatted output
        checker.format_output()

        # Output structured JSON to stderr for programmatic consumption
        print(json.dumps(health_data, indent=2), file=sys.stderr)

        # Exit with appropriate code
        if health_data["overall_status"] == "healthy":
            sys.exit(0)
        elif health_data["overall_status"] == "warning":
            sys.exit(1)
        else:
            sys.exit(2)

    except KeyboardInterrupt:
        print("\n\n❌ Health check interrupted by user", file=sys.stderr)
        sys.exit(130)

    except Exception as e:
        print(f"\n❌ Unexpected error during health check: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
