#!/usr/bin/env python3
"""
Agent Execution History Browser

Interactive CLI tool to browse agent manifest injection history with
complete traceability and debug intelligence analysis.

Features:
- List recent agent executions with performance metrics
- Drill down into complete manifest details
- View debug intelligence (what worked/failed)
- Search and filter by agent, date range, correlation ID
- Export manifest JSON for analysis
- Rich terminal UI with fallback to basic formatting

Usage:
    python3 agent_history_browser.py
    python3 agent_history_browser.py --agent test-agent
    python3 agent_history_browser.py --limit 100
    python3 agent_history_browser.py --correlation-id a2f33abd-34c2-4d63-bfe7-2cb14ded13fd

Database:
    Queries PostgreSQL database 'omninode_bridge' table 'agent_manifest_injections'
    Connection via environment variables or defaults to 192.168.86.200:5436

Created: 2025-10-27
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Error: psycopg2 not installed. Install with: pip install psycopg2-binary")
    sys.exit(1)

# Try to import rich for nice formatting
try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class AgentHistoryBrowser:
    """
    Interactive browser for agent execution history.

    Provides list view, detail view, search, and export capabilities
    for agent manifest injection records stored in PostgreSQL.
    """

    def __init__(
        self,
        db_host: Optional[str] = None,
        db_port: Optional[int] = None,
        db_name: Optional[str] = None,
        db_user: Optional[str] = None,
        db_password: Optional[str] = None,
    ):
        """
        Initialize browser with database connection.

        Args:
            db_host: PostgreSQL host (default: env POSTGRES_HOST or 192.168.86.200)
            db_port: PostgreSQL port (default: env POSTGRES_PORT or 5436)
            db_name: Database name (default: env POSTGRES_DATABASE or omninode_bridge)
            db_user: Database user (default: env POSTGRES_USER or postgres)
            db_password: Database password (default: env POSTGRES_PASSWORD)
        """
        # Try to load .env file first
        self._load_env_file()

        self.db_host = db_host or os.environ.get("POSTGRES_HOST", "192.168.86.200")
        self.db_port = db_port or int(os.environ.get("POSTGRES_PORT", "5436"))
        self.db_name = db_name or os.environ.get("POSTGRES_DATABASE", "omninode_bridge")
        self.db_user = db_user or os.environ.get("POSTGRES_USER", "postgres")
        self.db_password = db_password or os.environ.get("POSTGRES_PASSWORD")

        if not self.db_password:
            raise ValueError(
                "Database password not found! Set POSTGRES_PASSWORD environment variable or add to .env file."
            )

        self.console = Console() if RICH_AVAILABLE else None
        self.conn = None

    def _load_env_file(self):
        """Load environment variables from .env file if it exists."""
        # Look for .env in current directory and parent directories
        current_dir = Path.cwd()
        for _ in range(5):  # Check up to 5 levels up
            env_file = current_dir / ".env"
            if env_file.exists():
                try:
                    with open(env_file) as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, value = line.split("=", 1)
                                key = key.strip()
                                value = value.strip().strip('"').strip("'")
                                # Only set if not already in environment
                                if key not in os.environ:
                                    os.environ[key] = value
                    return
                except Exception:
                    # Silently fail - .env is optional
                    pass
            current_dir = current_dir.parent

    def connect(self) -> bool:
        """
        Connect to database.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.conn = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                dbname=self.db_name,
                user=self.db_user,
                password=self.db_password,
            )
            return True
        except Exception as e:
            self._print_error(f"Failed to connect to database: {e}")
            return False

    def disconnect(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def list_recent_runs(
        self,
        limit: int = 50,
        agent_name: Optional[str] = None,
        since_hours: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        List recent agent executions.

        Args:
            limit: Maximum number of runs to return
            agent_name: Filter by agent name (partial match)
            since_hours: Only show runs from last N hours

        Returns:
            List of agent run records
        """
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = """
            SELECT
                correlation_id,
                agent_name,
                created_at,
                patterns_count,
                total_query_time_ms,
                debug_intelligence_successes,
                debug_intelligence_failures,
                generation_source,
                is_fallback,
                manifest_size_bytes
            FROM agent_manifest_injections
            WHERE 1=1
        """
        params = []

        # Add filters
        if agent_name:
            query += " AND agent_name ILIKE %s"
            params.append(f"%{agent_name}%")

        if since_hours:
            query += " AND created_at >= NOW() - INTERVAL '%s hours'"
            params.append(since_hours)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        runs = cursor.fetchall()
        cursor.close()

        return [dict(run) for run in runs]

    def get_run_detail(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get complete details for a specific agent run.

        Args:
            correlation_id: Correlation ID of the run

        Returns:
            Complete run record or None if not found
        """
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = """
            SELECT *
            FROM agent_manifest_injections
            WHERE correlation_id = %s
        """

        cursor.execute(query, (correlation_id,))
        run = cursor.fetchone()
        cursor.close()

        return dict(run) if run else None

    def display_list_view(
        self,
        runs: List[Dict[str, Any]],
        show_numbers: bool = True,
    ):
        """
        Display list of runs in table format.

        Args:
            runs: List of run records
            show_numbers: Show selection numbers
        """
        if not runs:
            self._print_warning("No agent runs found matching criteria.")
            return

        if RICH_AVAILABLE:
            self._display_list_rich(runs, show_numbers)
        else:
            self._display_list_basic(runs, show_numbers)

    def _display_list_rich(self, runs: List[Dict[str, Any]], show_numbers: bool):
        """Display list using rich formatting."""
        table = Table(
            title="Recent Agent Runs",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )

        if show_numbers:
            table.add_column("#", style="dim", width=4)
        table.add_column("Correlation ID", style="magenta", width=36)
        table.add_column("Agent Name", style="green", width=25)
        table.add_column("Time", style="yellow", width=20)
        table.add_column("Patterns", justify="right", width=8)
        table.add_column("Query Time", justify="right", width=10)
        table.add_column("Debug Intel", justify="center", width=12)

        for idx, run in enumerate(runs, 1):
            time_ago = self._format_time_ago(run["created_at"])
            patterns = str(run["patterns_count"])
            query_time = f"{run['total_query_time_ms']}ms"

            # Format debug intelligence as success/failure
            successes = run.get("debug_intelligence_successes", 0)
            failures = run.get("debug_intelligence_failures", 0)
            debug_intel = f"✓{successes}/✗{failures}"

            # Color code based on fallback status
            agent_style = "red" if run.get("is_fallback") else "green"

            row = []
            if show_numbers:
                row.append(str(idx))
            row.extend(
                [
                    str(run["correlation_id"])[:36],
                    Text(run["agent_name"], style=agent_style),
                    time_ago,
                    patterns,
                    query_time,
                    debug_intel,
                ]
            )

            table.add_row(*row)

        self.console.print(table)
        self.console.print(f"\nTotal: {len(runs)} agent runs\n", style="dim")

    def _display_list_basic(self, runs: List[Dict[str, Any]], show_numbers: bool):
        """Display list using basic formatting."""
        print("=" * 120)
        print("RECENT AGENT RUNS")
        print("=" * 120)
        print()

        # Header
        header = []
        if show_numbers:
            header.append("#".ljust(4))
        header.extend(
            [
                "Correlation ID".ljust(36),
                "Agent Name".ljust(25),
                "Time".ljust(20),
                "Patterns".rjust(8),
                "Query Time".rjust(10),
                "Debug Intel".center(12),
            ]
        )
        print(" | ".join(header))
        print("-" * 120)

        # Rows
        for idx, run in enumerate(runs, 1):
            time_ago = self._format_time_ago(run["created_at"])
            patterns = str(run["patterns_count"]).rjust(8)
            query_time = f"{run['total_query_time_ms']}ms".rjust(10)

            successes = run.get("debug_intelligence_successes", 0)
            failures = run.get("debug_intelligence_failures", 0)
            debug_intel = f"✓{successes}/✗{failures}".center(12)

            agent_marker = "⚠" if run.get("is_fallback") else " "

            row = []
            if show_numbers:
                row.append(str(idx).ljust(4))
            row.extend(
                [
                    str(run["correlation_id"])[:36].ljust(36),
                    (agent_marker + run["agent_name"])[:25].ljust(25),
                    time_ago.ljust(20),
                    patterns,
                    query_time,
                    debug_intel,
                ]
            )
            print(" | ".join(row))

        print()
        print(f"Total: {len(runs)} agent runs")
        print()

    def display_detail_view(self, run: Dict[str, Any]):
        """
        Display complete details for a run.

        Args:
            run: Complete run record
        """
        if RICH_AVAILABLE:
            self._display_detail_rich(run)
        else:
            self._display_detail_basic(run)

    def _display_detail_rich(self, run: Dict[str, Any]):
        """Display detail view using rich formatting."""
        # Header panel
        header_text = f"""
[bold cyan]Correlation ID:[/] {run['correlation_id']}
[bold cyan]Agent:[/] {run['agent_name']}
[bold cyan]Timestamp:[/] {run['created_at'].strftime('%Y-%m-%d %H:%M:%S %Z')}
[bold cyan]Source:[/] {run['generation_source']} {'[red](fallback)[/]' if run['is_fallback'] else '[green](full)[/]'}
"""
        self.console.print(
            Panel(header_text, title="Agent Execution Details", border_style="cyan")
        )

        # Performance metrics
        query_times = run.get("query_times", {})
        perf_table = Table(title="Performance Metrics", box=box.SIMPLE)
        perf_table.add_column("Section", style="cyan")
        perf_table.add_column("Time (ms)", justify="right", style="yellow")

        for section, time_ms in query_times.items():
            perf_table.add_row(section.replace("_", " ").title(), str(time_ms))

        perf_table.add_row("[bold]Total[/]", f"[bold]{run['total_query_time_ms']}[/]")
        self.console.print(perf_table)
        print()

        # Content summary
        summary_table = Table(title="Manifest Content", box=box.SIMPLE)
        summary_table.add_column("Category", style="cyan")
        summary_table.add_column("Count", justify="right", style="green")

        summary_table.add_row("Patterns", str(run["patterns_count"]))
        summary_table.add_row(
            "Infrastructure Services", str(run.get("infrastructure_services", 0))
        )
        summary_table.add_row("Models", str(run.get("models_count", 0)))
        summary_table.add_row(
            "Database Schemas", str(run.get("database_schemas_count", 0))
        )
        summary_table.add_row(
            "Manifest Size", f"{run.get('manifest_size_bytes') or 0:,} bytes"
        )

        self.console.print(summary_table)
        print()

        # Debug intelligence
        successes = run.get("debug_intelligence_successes", 0)
        failures = run.get("debug_intelligence_failures", 0)

        if successes > 0 or failures > 0:
            debug_text = f"""
[bold green]✓ Successful Approaches:[/] {successes} examples
[bold red]✗ Failed Approaches:[/] {failures} examples to avoid
"""
            self.console.print(
                Panel(debug_text, title="Debug Intelligence", border_style="yellow")
            )

            # Show actual debug intelligence if available
            manifest_snapshot = run.get("full_manifest_snapshot", {})
            if isinstance(manifest_snapshot, dict):
                debug_intel = manifest_snapshot.get("debug_intelligence", {})
                workflows = debug_intel.get("similar_workflows", {})

                if workflows:
                    successes_list = workflows.get("successes", [])
                    failures_list = workflows.get("failures", [])

                    if successes_list:
                        self.console.print(
                            "\n[bold green]Successful Approaches (what worked):[/]"
                        )
                        for workflow in successes_list[:5]:
                            tool = workflow.get("tool_name", "unknown")
                            reasoning = workflow.get("reasoning", "")[:80]
                            self.console.print(f"  • [green]{tool}[/]: {reasoning}")

                    if failures_list:
                        self.console.print(
                            "\n[bold red]Failed Approaches (avoid retrying):[/]"
                        )
                        for workflow in failures_list[:5]:
                            tool = workflow.get("tool_name", "unknown")
                            error = workflow.get("error", "")[:80]
                            self.console.print(f"  • [red]{tool}[/]: {error}")
            print()

        # Formatted manifest preview
        formatted_text = run.get("formatted_manifest_text", "")
        if formatted_text:
            # Show first 20 lines
            all_lines = formatted_text.split("\n")
            lines = all_lines[:20]
            preview = "\n".join(lines)
            if len(all_lines) > 20:
                remaining = len(all_lines) - 20
                preview += f"\n... ({remaining} more lines)"

            self.console.print(
                Panel(
                    preview,
                    title="Formatted Manifest Preview",
                    border_style="dim",
                    subtitle="[dim](first 20 lines)[/]",
                )
            )

    def _display_detail_basic(self, run: Dict[str, Any]):
        """Display detail view using basic formatting."""
        print("=" * 80)
        print("AGENT EXECUTION DETAILS")
        print("=" * 80)
        print(f"Correlation ID: {run['correlation_id']}")
        print(f"Agent: {run['agent_name']}")
        print(f"Timestamp: {run['created_at'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(
            f"Source: {run['generation_source']} {'(fallback)' if run['is_fallback'] else '(full)'}"
        )
        print()

        # Performance metrics
        print("PERFORMANCE METRICS:")
        query_times = run.get("query_times", {})
        for section, time_ms in query_times.items():
            print(f"  {section.replace('_', ' ').title()}: {time_ms}ms")
        print(f"  Total Time: {run['total_query_time_ms']}ms")
        print()

        # Content summary
        print("MANIFEST CONTENT:")
        print(f"  Patterns: {run['patterns_count']}")
        print(f"  Infrastructure Services: {run.get('infrastructure_services', 0)}")
        print(f"  Models: {run.get('models_count', 0)}")
        print(f"  Database Schemas: {run.get('database_schemas_count', 0)}")
        print(f"  Manifest Size: {run.get('manifest_size_bytes') or 0:,} bytes")
        print()

        # Debug intelligence
        successes = run.get("debug_intelligence_successes", 0)
        failures = run.get("debug_intelligence_failures", 0)

        if successes > 0 or failures > 0:
            print("DEBUG INTELLIGENCE:")
            print(f"  ✓ Successful Approaches: {successes} examples")
            print(f"  ✗ Failed Approaches: {failures} examples to avoid")

            # Show actual debug intelligence if available
            manifest_snapshot = run.get("full_manifest_snapshot", {})
            if isinstance(manifest_snapshot, dict):
                debug_intel = manifest_snapshot.get("debug_intelligence", {})
                workflows = debug_intel.get("similar_workflows", {})

                if workflows:
                    successes_list = workflows.get("successes", [])
                    failures_list = workflows.get("failures", [])

                    if successes_list:
                        print("\n  Successful Approaches (what worked):")
                        for workflow in successes_list[:5]:
                            tool = workflow.get("tool_name", "unknown")
                            reasoning = workflow.get("reasoning", "")[:80]
                            print(f"    • {tool}: {reasoning}")

                    if failures_list:
                        print("\n  Failed Approaches (avoid retrying):")
                        for workflow in failures_list[:5]:
                            tool = workflow.get("tool_name", "unknown")
                            error = workflow.get("error", "")[:80]
                            print(f"    • {tool}: {error}")
            print()

        # Formatted manifest preview
        formatted_text = run.get("formatted_manifest_text", "")
        if formatted_text:
            print("FORMATTED MANIFEST PREVIEW:")
            print("-" * 80)
            all_lines = formatted_text.split("\n")
            lines = all_lines[:20]
            for line in lines:
                print(line)
            if len(all_lines) > 20:
                remaining = len(all_lines) - 20
                print(f"... ({remaining} more lines)")
            print("-" * 80)

    def export_manifest(self, run: Dict[str, Any], output_path: str) -> bool:
        """
        Export manifest to JSON file.

        Args:
            run: Run record to export
            output_path: Output file path

        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert datetime objects to ISO format strings
            export_data = {}
            for key, value in run.items():
                if isinstance(value, datetime):
                    export_data[key] = value.isoformat()
                elif isinstance(value, UUID):
                    export_data[key] = str(value)
                else:
                    export_data[key] = value

            with open(output_path, "w") as f:
                json.dump(export_data, f, indent=2, default=str)

            self._print_success(f"Manifest exported to: {output_path}")
            return True

        except Exception as e:
            self._print_error(f"Failed to export manifest: {e}")
            return False

    def run_interactive(
        self,
        initial_agent: Optional[str] = None,
        initial_limit: int = 50,
    ):
        """
        Run interactive browser session.

        Args:
            initial_agent: Initial agent filter
            initial_limit: Initial limit for list view
        """
        if not self.connect():
            return

        try:
            agent_filter = initial_agent
            limit = initial_limit

            while True:
                # Clear screen and show header
                self._show_header()

                # List recent runs
                runs = self.list_recent_runs(
                    limit=limit,
                    agent_name=agent_filter,
                )

                self.display_list_view(runs, show_numbers=True)

                # Show commands
                self._show_commands(agent_filter, limit)

                # Get user input
                if RICH_AVAILABLE:
                    command = Prompt.ask("\nCommand", default="q")
                else:
                    command = input("\nCommand [q]: ").strip() or "q"

                # Process command
                if command.lower() in ["q", "quit", "exit"]:
                    break
                elif command.lower() in ["h", "help"]:
                    self._show_help()
                elif command.lower().startswith("search "):
                    agent_filter = command[7:].strip()
                    if RICH_AVAILABLE:
                        self.console.print(
                            f"Filtering by agent: {agent_filter}", style="yellow"
                        )
                    else:
                        print(f"Filtering by agent: {agent_filter}")
                elif command.lower() == "clear":
                    agent_filter = None
                    if RICH_AVAILABLE:
                        self.console.print("Filter cleared", style="yellow")
                    else:
                        print("Filter cleared")
                elif command.lower().startswith("limit "):
                    try:
                        limit = int(command[6:].strip())
                        if RICH_AVAILABLE:
                            self.console.print(f"Limit set to: {limit}", style="yellow")
                        else:
                            print(f"Limit set to: {limit}")
                    except ValueError:
                        self._print_error("Invalid limit value")
                elif command.lower().startswith("export "):
                    try:
                        idx = int(command[7:].strip())
                        if 1 <= idx <= len(runs):
                            run = runs[idx - 1]
                            detail = self.get_run_detail(str(run["correlation_id"]))
                            if detail:
                                filename = f"manifest_{run['correlation_id']}.json"
                                self.export_manifest(detail, filename)
                        else:
                            self._print_error(f"Invalid selection: {idx}")
                    except ValueError:
                        self._print_error("Invalid export command")
                elif command.isdigit():
                    idx = int(command)
                    if 1 <= idx <= len(runs):
                        run = runs[idx - 1]
                        detail = self.get_run_detail(str(run["correlation_id"]))
                        if detail:
                            self._show_header()
                            self.display_detail_view(detail)
                            if RICH_AVAILABLE:
                                Prompt.ask("\nPress Enter to return", default="")
                            else:
                                input("\nPress Enter to return...")
                    else:
                        self._print_error(f"Invalid selection: {idx}")
                else:
                    self._print_error(f"Unknown command: {command}")

        finally:
            self.disconnect()

    def _show_header(self):
        """Show browser header."""
        if RICH_AVAILABLE:
            self.console.clear()
            header = Text()
            header.append("=" * 80 + "\n", style="cyan")
            header.append("AGENT EXECUTION HISTORY BROWSER\n", style="bold cyan")
            header.append("=" * 80, style="cyan")
            self.console.print(header)
            print()
        else:
            print("\n" * 2)
            print("=" * 80)
            print("AGENT EXECUTION HISTORY BROWSER")
            print("=" * 80)
            print()

    def _show_commands(self, current_filter: Optional[str], current_limit: int):
        """Show available commands."""
        filter_info = f" (filtering: {current_filter})" if current_filter else ""

        if RICH_AVAILABLE:
            commands = f"""
[bold]Commands:[/]
  [cyan][number][/]           View detailed history for agent run
  [cyan]search [name][/]      Filter by agent name{filter_info}
  [cyan]clear[/]              Clear filter
  [cyan]limit [N][/]          Set list limit (current: {current_limit})
  [cyan]export [number][/]    Export manifest JSON
  [cyan]h, help[/]            Show help
  [cyan]q, quit[/]            Quit browser
"""
            self.console.print(Panel(commands, border_style="dim"))
        else:
            print("\nCommands:")
            print("  [number]           View detailed history for agent run")
            print(f"  search [name]      Filter by agent name{filter_info}")
            print("  clear              Clear filter")
            print(f"  limit [N]          Set list limit (current: {current_limit})")
            print("  export [number]    Export manifest JSON")
            print("  h, help            Show help")
            print("  q, quit            Quit browser")

    def _show_help(self):
        """Show detailed help."""
        if RICH_AVAILABLE:
            self.console.clear()

        help_text = """
AGENT EXECUTION HISTORY BROWSER - HELP

This tool allows you to browse and analyze agent manifest injection history
stored in the PostgreSQL database. Each record represents a complete snapshot
of what an agent received at execution time.

COMMANDS:

  [number]
    View detailed information about a specific agent run.
    Example: Type "1" to view details for the first run in the list.

  search [agent-name]
    Filter the list to show only runs from a specific agent.
    Supports partial matching (case-insensitive).
    Example: search test-agent

  clear
    Remove the current agent filter to show all runs.

  limit [N]
    Change the number of runs displayed in the list.
    Example: limit 100

  export [number]
    Export the complete manifest for a run to a JSON file.
    The file will be saved as "manifest_[correlation-id].json"
    Example: export 1

  h, help
    Show this help message.

  q, quit, exit
    Exit the browser.

DETAIL VIEW:

When you select a run by number, you'll see:
  - Full correlation ID and agent information
  - Performance metrics breakdown
  - Content summary (patterns, infrastructure, models, schemas)
  - Debug intelligence (successful/failed approaches)
  - Formatted manifest preview

DEBUG INTELLIGENCE:

The debug intelligence section shows similar past workflows:
  ✓ Successful approaches: What worked in similar situations
  ✗ Failed approaches: What to avoid (don't retry these)

This helps agents learn from past executions and avoid repeating mistakes.

MANIFEST TRACEABILITY:

Each record includes:
  - Complete manifest snapshot (what the agent received)
  - Performance metrics (query times for each section)
  - Debug intelligence (similar workflows from past)
  - Formatted text (exactly what was injected into prompt)

This enables complete replay of any agent execution for debugging.

DATABASE CONNECTION:

Connection details can be configured via environment variables:
  POSTGRES_HOST (default: 192.168.86.200)
  POSTGRES_PORT (default: 5436)
  POSTGRES_DATABASE (default: omninode_bridge)
  POSTGRES_USER (default: postgres)
  POSTGRES_PASSWORD (default: omninode-bridge-postgres-dev-2024)
"""

        if RICH_AVAILABLE:
            self.console.print(Panel(help_text, title="Help", border_style="cyan"))
            Prompt.ask("\nPress Enter to return", default="")
        else:
            print(help_text)
            input("\nPress Enter to return...")

    def _format_time_ago(self, dt: datetime) -> str:
        """Format datetime as relative time."""
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = now - dt

        if delta.total_seconds() < 60:
            return "just now"
        elif delta.total_seconds() < 3600:
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes}m ago"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h ago"
        elif delta.days < 7:
            return f"{delta.days}d ago"
        else:
            return dt.strftime("%Y-%m-%d")

    def _print_success(self, message: str):
        """Print success message."""
        if RICH_AVAILABLE:
            self.console.print(f"✓ {message}", style="bold green")
        else:
            print(f"✓ {message}")

    def _print_error(self, message: str):
        """Print error message."""
        if RICH_AVAILABLE:
            self.console.print(f"✗ {message}", style="bold red")
        else:
            print(f"✗ {message}")

    def _print_warning(self, message: str):
        """Print warning message."""
        if RICH_AVAILABLE:
            self.console.print(f"⚠ {message}", style="bold yellow")
        else:
            print(f"⚠ {message}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Browse agent execution history with manifest traceability"
    )
    parser.add_argument(
        "--agent",
        help="Filter by agent name (partial match)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of runs to show (default: 50)",
    )
    parser.add_argument(
        "--correlation-id",
        help="Show details for specific correlation ID",
    )
    parser.add_argument(
        "--export",
        help="Export manifest to JSON file (requires --correlation-id)",
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        help="Only show runs from last N hours",
    )

    args = parser.parse_args()

    browser = AgentHistoryBrowser()

    # Non-interactive mode for specific correlation ID
    if args.correlation_id:
        if not browser.connect():
            sys.exit(1)

        try:
            detail = browser.get_run_detail(args.correlation_id)
            if detail:
                browser.display_detail_view(detail)

                if args.export:
                    browser.export_manifest(detail, args.export)
            else:
                print(f"Error: No run found with correlation ID: {args.correlation_id}")
                sys.exit(1)
        finally:
            browser.disconnect()

    # Interactive mode
    else:
        print(
            f"\nConnecting to {browser.db_host}:{browser.db_port}/{browser.db_name}..."
        )
        if not RICH_AVAILABLE:
            print("Note: Install 'rich' for better formatting: pip install rich\n")

        browser.run_interactive(
            initial_agent=args.agent,
            initial_limit=args.limit,
        )


if __name__ == "__main__":
    main()
