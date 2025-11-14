#!/usr/bin/env python3
"""
Debug Loop Intelligence CLI

User-friendly CLI for managing Solution Template Fragments (STFs) and
model pricing catalog using the debug loop intelligence infrastructure.

Usage:
    python3 scripts/debug_loop_cli.py stf list
    python3 scripts/debug_loop_cli.py stf show <stf_id>
    python3 scripts/debug_loop_cli.py stf search --category "data_validation"
    python3 scripts/debug_loop_cli.py stf store --code path/to/code.py --description "My STF"
    python3 scripts/debug_loop_cli.py model list
    python3 scripts/debug_loop_cli.py model show anthropic claude-3-5-sonnet
    python3 scripts/debug_loop_cli.py model add

Requirements:
    pip install click rich asyncpg
"""

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

try:
    import asyncpg
except ImportError as e:
    click.echo(f"Error: Missing required dependency asyncpg: {e}", err=True)
    click.echo("Install with: pip install asyncpg", err=True)
    sys.exit(1)

# Add parent directory to path for config import
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load configuration
try:
    from config import settings

    POSTGRES_HOST = settings.postgres_host
    POSTGRES_PORT = settings.postgres_port
    POSTGRES_USER = settings.postgres_user
    POSTGRES_PASSWORD = settings.get_effective_postgres_password()
    POSTGRES_DATABASE = settings.postgres_database
except ImportError:
    # Fallback to environment variables
    import os

    # Safe fallback to localhost - avoids connecting to remote server if .env is misconfigured
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5436"))
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
    POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE", "omninode_bridge")

console = Console()

# Import environment validation
from env_validation import validate_required_env_vars

# Validate environment configuration in production
validate_required_env_vars(
    console,
    {
        "POSTGRES_HOST": "PostgreSQL database host",
        "POSTGRES_PORT": "PostgreSQL database port",
        "POSTGRES_USER": "PostgreSQL database user",
        "POSTGRES_PASSWORD": "PostgreSQL database password",
        "POSTGRES_DATABASE": "PostgreSQL database name",
    },
)


class DatabasePool:
    """Async context manager for database connection pool lifecycle."""

    def __init__(self):
        self.pool = None

    async def __aenter__(self):
        """Create and return database connection pool."""
        if not POSTGRES_PASSWORD:
            console.print("[red]Error: POSTGRES_PASSWORD not set in environment[/red]")
            console.print("Run: source .env")
            sys.exit(1)

        try:
            self.pool = await asyncpg.create_pool(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                database=POSTGRES_DATABASE,
                min_size=2,
                max_size=5,
            )
            return self.pool
        except Exception as e:
            console.print(f"[red]Database connection failed: {e}[/red]")
            console.print(
                f"Connection: {POSTGRES_USER}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"
            )
            sys.exit(1)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close database connection pool."""
        if self.pool is not None:
            await self.pool.close()


async def get_db_pool():
    """
    Create database connection pool context manager.

    Usage:
        async with get_db_pool() as pool:
            async with pool.acquire() as conn:
                # perform database operations
    """
    return DatabasePool()


def compute_stf_hash(code: str) -> str:
    """Compute deterministic hash for STF code."""
    # Normalize whitespace and compute SHA-256
    normalized = "\n".join(line.rstrip() for line in code.splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# STF Commands
@click.group()
def cli():
    """Debug Loop Intelligence CLI - Manage STFs and Model Pricing"""
    pass


@cli.group()
def stf():
    """Solution Template Fragment (STF) management commands"""
    pass


@stf.command("list")
@click.option("--limit", default=20, help="Maximum number of results")
@click.option("--category", help="Filter by problem category")
@click.option(
    "--min-quality", default=0.0, type=float, help="Minimum quality score (0.0-1.0)"
)
def list_stfs(limit: int, category: Optional[str], min_quality: float):
    """List all STFs with quality scores"""

    async def run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Querying database...", total=None)

            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    # Build query with parameterized placeholders
                    where_parts = ["quality_score >= $1"]
                    params = [min_quality]

                    if category:
                        params.append(category)
                        where_parts.append(f"problem_category = ${len(params)}")

                    where_clause = " AND ".join(where_parts)

                    # Add limit parameter
                    params.append(limit)
                    limit_placeholder = f"${len(params)}"

                    query = f"""
                    SELECT
                        stf_id, stf_name, problem_category, quality_score,
                        usage_count, approval_status, created_at,
                        CASE WHEN usage_count > 0
                             THEN success_count::float / usage_count
                             ELSE 0.0
                        END as success_rate
                    FROM debug_transform_functions
                    WHERE {where_clause}
                    ORDER BY quality_score DESC, usage_count DESC
                    LIMIT {limit_placeholder}
                    """

                    results = await conn.fetch(query, *params)

        if not results:
            console.print("[yellow]No STFs found matching criteria[/yellow]")
            return

        # Create table
        table = Table(
            title=f"Solution Template Fragments ({len(results)} results)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )

        table.add_column("Name", style="green", no_wrap=True)
        table.add_column("Category", style="blue")
        table.add_column("Quality", justify="right", style="yellow")
        table.add_column("Usage", justify="right")
        table.add_column("Success Rate", justify="right", style="magenta")
        table.add_column("Status", justify="center")
        table.add_column("Created", style="dim")

        for row in results:
            # Color code quality score
            quality = row["quality_score"] or 0.0
            if quality >= 0.9:
                quality_str = f"[green]{quality:.2f}[/green]"
            elif quality >= 0.7:
                quality_str = f"[yellow]{quality:.2f}[/yellow]"
            else:
                quality_str = f"[red]{quality:.2f}[/red]"

            # Color code success rate
            success_rate = row["success_rate"] or 0.0
            if success_rate >= 0.8:
                success_str = f"[green]{success_rate:.1%}[/green]"
            elif success_rate >= 0.5:
                success_str = f"[yellow]{success_rate:.1%}[/yellow]"
            else:
                success_str = f"[red]{success_rate:.1%}[/red]"

            # Status badge
            status = row["approval_status"]
            if status == "approved":
                status_badge = "[green]✓ Approved[/green]"
            elif status == "pending":
                status_badge = "[yellow]⧗ Pending[/yellow]"
            else:
                status_badge = "[red]✗ Rejected[/red]"

            table.add_row(
                row["stf_name"][:30],
                row["problem_category"] or "N/A",
                quality_str,
                str(row["usage_count"]),
                success_str,
                status_badge,
                row["created_at"].strftime("%Y-%m-%d") if row["created_at"] else "N/A",
            )

        console.print(table)

        # Summary panel
        avg_quality = sum(r["quality_score"] or 0 for r in results) / len(results)
        total_usage = sum(r["usage_count"] for r in results)
        approved_count = sum(1 for r in results if r["approval_status"] == "approved")

        summary = f"""
[cyan]Total STFs:[/cyan] {len(results)}
[cyan]Average Quality:[/cyan] {avg_quality:.2f}
[cyan]Total Usage:[/cyan] {total_usage}
[cyan]Approved:[/cyan] {approved_count} ({approved_count/len(results):.1%})
        """
        console.print(Panel(summary.strip(), title="Summary", border_style="cyan"))

    asyncio.run(run())


@stf.command("show")
@click.argument("stf_id")
def show_stf(stf_id: str):
    """Show detailed STF information"""

    async def run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Fetching STF...", total=None)

            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    query = """
                    SELECT
                        stf_id, stf_name, stf_code, stf_hash, stf_description,
                        problem_category, quality_score, usage_count, success_count,
                        approval_status, created_at, last_used_at
                    FROM debug_transform_functions
                    WHERE stf_id = $1
                    """

                    result = await conn.fetchrow(query, stf_id)

        if not result:
            console.print(f"[red]STF not found: {stf_id}[/red]")
            return

        # Header
        console.print(
            Panel(
                f"[bold cyan]{result['stf_name']}[/bold cyan]\n"
                f"[dim]ID: {result['stf_id']}[/dim]",
                border_style="cyan",
            )
        )

        # Metadata table
        meta_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        meta_table.add_column("Field", style="cyan")
        meta_table.add_column("Value")

        meta_table.add_row("Problem Category", result.get("problem_category") or "N/A")
        meta_table.add_row("Quality Score", f"{result.get('quality_score', 0):.2f}")
        meta_table.add_row("Usage Count", str(result.get("usage_count", 0)))
        meta_table.add_row("Success Count", str(result.get("success_count", 0)))

        success_count = result.get("success_count", 0)
        usage_count = result.get("usage_count", 0)
        success_rate = (success_count / usage_count * 100) if usage_count > 0 else 0
        meta_table.add_row("Success Rate", f"{success_rate:.1f}%")

        meta_table.add_row(
            "Approval Status", result.get("approval_status", "unknown").upper()
        )
        meta_table.add_row("Created", str(result.get("created_at", "N/A")))
        meta_table.add_row("Last Used", str(result.get("last_used_at", "Never")))

        console.print(meta_table)

        # Description
        if result.get("stf_description"):
            console.print(
                Panel(
                    result["stf_description"],
                    title="Description",
                    border_style="blue",
                )
            )

        # Code
        console.print("\n[bold]Code:[/bold]")
        syntax = Syntax(
            result.get("stf_code", "# No code available"),
            "python",
            theme="monokai",
            line_numbers=True,
        )
        console.print(syntax)

        # Hash
        console.print(f"\n[dim]Hash: {result.get('stf_hash', 'N/A')}[/dim]")

    asyncio.run(run())


@stf.command()
@click.option("--category", help="Problem category")
@click.option("--min-quality", default=0.7, type=float, help="Minimum quality score")
@click.option("--limit", default=10, type=int, help="Maximum results")
def search(category: Optional[str], min_quality: float, limit: int):
    """Search STFs by criteria"""

    async def run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Searching...", total=None)

            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    # Build WHERE clause with parameterized placeholders
                    where_parts = [
                        "quality_score >= $1",
                        "approval_status = 'approved'",
                    ]
                    params = [min_quality]

                    if category:
                        params.append(category)
                        where_parts.append(f"problem_category = ${len(params)}")

                    where_clause = " AND ".join(where_parts)

                    # Add limit parameter
                    params.append(limit)
                    limit_placeholder = f"${len(params)}"

                    query = f"""
                    SELECT
                        stf_id, stf_name, stf_description, problem_category,
                        quality_score, usage_count,
                        CASE WHEN usage_count > 0
                             THEN success_count::float / usage_count
                             ELSE 0.0
                        END as success_rate
                    FROM debug_transform_functions
                    WHERE {where_clause}
                    ORDER BY quality_score DESC, usage_count DESC
                    LIMIT {limit_placeholder}
                    """

                    results = await conn.fetch(query, *params)

        if not results:
            console.print("[yellow]No STFs found matching criteria[/yellow]")
            return

        # Create table
        table = Table(
            title=f"Search Results ({len(results)} found)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )

        table.add_column("Name", style="green")
        table.add_column("Category", style="blue")
        table.add_column("Quality", justify="right", style="yellow")
        table.add_column("Usage", justify="right")
        table.add_column("Success Rate", justify="right", style="magenta")
        table.add_column("Description", style="dim")

        for row in results:
            quality = row["quality_score"]
            success_rate = row["success_rate"]

            table.add_row(
                row["stf_name"][:25],
                row["problem_category"] or "N/A",
                f"{quality:.2f}",
                str(row["usage_count"]),
                f"{success_rate:.1%}",
                (row["stf_description"] or "")[:40],
            )

        console.print(table)

    asyncio.run(run())


@stf.command()
@click.option(
    "--code", type=click.Path(exists=True), required=True, help="Path to code file"
)
@click.option("--name", required=True, help="STF name")
@click.option("--description", required=True, help="STF description")
@click.option("--category", help="Problem category")
@click.option("--quality", default=0.8, type=float, help="Quality score (0.0-1.0)")
def store(
    code: str, name: str, description: str, category: Optional[str], quality: float
):
    """Store new STF from code file"""

    async def run():
        # Read code file
        code_path = Path(code)
        if not code_path.exists():
            console.print(f"[red]Code file not found: {code}[/red]")
            return

        stf_code = code_path.read_text()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Computing hash...", total=None)

            # Compute hash
            stf_hash = compute_stf_hash(stf_code)
            stf_id = str(uuid4())

            progress.update(0, description="Storing STF...")

            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    query = """
                    INSERT INTO debug_transform_functions (
                        stf_id, stf_name, stf_code, stf_hash, stf_description,
                        problem_category, quality_score,
                        usage_count, success_count, approval_status, created_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, 0, 0, 'pending', NOW()
                    )
                    ON CONFLICT (stf_hash) DO NOTHING
                    RETURNING stf_id
                    """

                    result = await conn.fetchrow(
                        query,
                        stf_id,
                        name,
                        stf_code,
                        stf_hash,
                        description,
                        category,
                        quality,
                    )

        if result:
            console.print(
                Panel(
                    f"[green]✓ STF stored successfully[/green]\n\n"
                    f"[cyan]ID:[/cyan] {stf_id}\n"
                    f"[cyan]Hash:[/cyan] {stf_hash[:16]}...\n"
                    f"[cyan]File:[/cyan] {code_path.name}",
                    title="Success",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    "[yellow]STF with same code hash already exists[/yellow]",
                    title="Duplicate Detected",
                    border_style="yellow",
                )
            )

    asyncio.run(run())


# Model Commands
@cli.group()
def model():
    """Model pricing catalog management commands"""
    pass


@model.command("list")
@click.option(
    "--provider", help="Filter by provider (anthropic, openai, google, zai, together)"
)
@click.option("--active-only/--all", default=True, help="Show only active models")
def list_models(provider: Optional[str], active_only: bool):
    """List all models in price catalog"""

    async def run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Querying models...", total=None)

            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    # Build WHERE clause with parameterized placeholders
                    where_parts = []
                    params = []

                    if active_only:
                        where_parts.append("is_active = true")
                    if provider:
                        params.append(provider)
                        where_parts.append(f"provider = ${len(params)}")

                    where_clause = " AND ".join(where_parts) if where_parts else "1=1"

                    query = f"""
                    SELECT
                        catalog_id, provider, model_name,
                        input_price_per_million, output_price_per_million,
                        is_active, supports_streaming, supports_function_calling,
                        created_at
                    FROM model_price_catalog
                    WHERE {where_clause}
                    ORDER BY provider, model_name
                    """

                    results = await conn.fetch(query, *params)

        if not results:
            console.print("[yellow]No models found[/yellow]")
            return

        # Create table
        table = Table(
            title=f"Model Price Catalog ({len(results)} models)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )

        table.add_column("Provider", style="blue")
        table.add_column("Model Name", style="green")
        table.add_column("Input Price", justify="right", style="yellow")
        table.add_column("Output Price", justify="right", style="yellow")
        table.add_column("Features", style="magenta")
        table.add_column("Status", justify="center")

        for model in results:
            # Features badges
            features = []
            if model.get("supports_streaming"):
                features.append("🔄")
            if model.get("supports_function_calling"):
                features.append("🔧")

            features_str = " ".join(features) if features else "—"

            # Status
            status = (
                "[green]✓ Active[/green]"
                if model["is_active"]
                else "[dim]✗ Inactive[/dim]"
            )

            table.add_row(
                model["provider"],
                model["model_name"],
                f"${model['input_price_per_million']:.2f}/M",
                f"${model['output_price_per_million']:.2f}/M",
                features_str,
                status,
            )

        console.print(table)

        # Summary
        total_providers = len(set(m["provider"] for m in results))
        avg_input = sum(m["input_price_per_million"] for m in results) / len(results)
        avg_output = sum(m["output_price_per_million"] for m in results) / len(results)

        summary = f"""
[cyan]Total Models:[/cyan] {len(results)}
[cyan]Providers:[/cyan] {total_providers}
[cyan]Avg Input Price:[/cyan] ${avg_input:.2f}/M tokens
[cyan]Avg Output Price:[/cyan] ${avg_output:.2f}/M tokens

[dim]Features: 🔄 Streaming | 🔧 Function Calling[/dim]
        """
        console.print(Panel(summary.strip(), title="Summary", border_style="cyan"))

    asyncio.run(run())


@model.command("show")
@click.argument("provider")
@click.argument("model_name")
def show_model(provider: str, model_name: str):
    """Show detailed model information"""

    async def run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Fetching model...", total=None)

            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    query = """
                    SELECT
                        catalog_id, provider, model_name, model_version,
                        input_price_per_million, output_price_per_million,
                        max_tokens, context_window, is_active,
                        supports_streaming, supports_function_calling, supports_vision,
                        requests_per_minute, tokens_per_minute,
                        created_at, updated_at
                    FROM model_price_catalog
                    WHERE provider = $1 AND model_name = $2 AND is_active = true
                    ORDER BY created_at DESC
                    LIMIT 1
                    """

                    result = await conn.fetchrow(query, provider, model_name)

        if not result:
            console.print(f"[red]Model not found: {provider}/{model_name}[/red]")
            return

        # Header
        console.print(
            Panel(
                f"[bold cyan]{result['provider']} / {result['model_name']}[/bold cyan]\n"
                f"[dim]Version: {result.get('model_version') or 'N/A'}[/dim]",
                border_style="cyan",
            )
        )

        # Pricing table
        price_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        price_table.add_column("Metric", style="cyan")
        price_table.add_column("Value", style="yellow")

        price_table.add_row(
            "Input Price",
            f"${result['input_price_per_million']:.2f} per million tokens",
        )
        price_table.add_row(
            "Output Price",
            f"${result['output_price_per_million']:.2f} per million tokens",
        )
        price_table.add_row("Max Tokens", str(result.get("max_tokens") or "N/A"))
        price_table.add_row(
            "Context Window", str(result.get("context_window") or "N/A")
        )

        console.print(Panel(price_table, title="Pricing", border_style="yellow"))

        # Features table
        feature_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        feature_table.add_column("Feature", style="cyan")
        feature_table.add_column("Supported", style="green")

        feature_table.add_row(
            "Streaming", "✓ Yes" if result.get("supports_streaming") else "✗ No"
        )
        feature_table.add_row(
            "Function Calling",
            "✓ Yes" if result.get("supports_function_calling") else "✗ No",
        )
        feature_table.add_row(
            "Vision", "✓ Yes" if result.get("supports_vision") else "✗ No"
        )

        console.print(Panel(feature_table, title="Features", border_style="blue"))

        # Rate limits
        if result.get("requests_per_minute") or result.get("tokens_per_minute"):
            limit_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            limit_table.add_column("Limit", style="cyan")
            limit_table.add_column("Value", style="magenta")

            if result.get("requests_per_minute"):
                limit_table.add_row(
                    "Requests/Minute", str(result["requests_per_minute"])
                )
            if result.get("tokens_per_minute"):
                limit_table.add_row("Tokens/Minute", str(result["tokens_per_minute"]))

            console.print(
                Panel(limit_table, title="Rate Limits", border_style="magenta")
            )

        # Metadata
        console.print(
            f"\n[dim]Status: {'Active' if result['is_active'] else 'Inactive'}[/dim]"
        )
        console.print(f"[dim]Created: {result.get('created_at', 'N/A')}[/dim]")
        console.print(f"[dim]Updated: {result.get('updated_at', 'N/A')}[/dim]")

    asyncio.run(run())


@model.command()
def add():
    """Add new model to catalog (interactive)"""
    console.print("[bold cyan]Add New Model to Catalog[/bold cyan]\n")

    # Collect information interactively
    provider = click.prompt(
        "Provider",
        type=click.Choice(["anthropic", "openai", "google", "zai", "together"]),
    )
    model_name = click.prompt("Model name")
    model_version = click.prompt(
        "Model version (optional)", default="", show_default=False
    )

    input_price = click.prompt("Input price per million tokens", type=float)
    output_price = click.prompt("Output price per million tokens", type=float)

    max_tokens = click.prompt(
        "Max tokens (optional)", type=int, default=0, show_default=False
    )
    context_window = click.prompt(
        "Context window (optional)", type=int, default=0, show_default=False
    )

    supports_streaming = click.confirm("Supports streaming?", default=False)
    supports_function_calling = click.confirm(
        "Supports function calling?", default=False
    )
    supports_vision = click.confirm("Supports vision?", default=False)

    requests_per_minute = click.prompt(
        "Requests per minute (optional)", type=int, default=0, show_default=False
    )
    tokens_per_minute = click.prompt(
        "Tokens per minute (optional)", type=int, default=0, show_default=False
    )

    async def run():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Adding model...", total=None)

            catalog_id = str(uuid4())

            async with await get_db_pool() as pool:
                async with pool.acquire() as conn:
                    query = """
                    INSERT INTO model_price_catalog (
                        catalog_id, provider, model_name, model_version,
                        input_price_per_million, output_price_per_million,
                        max_tokens, context_window,
                        supports_streaming, supports_function_calling, supports_vision,
                        requests_per_minute, tokens_per_minute,
                        is_active, created_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, true, NOW()
                    )
                    ON CONFLICT (provider, model_name, model_version) DO NOTHING
                    RETURNING catalog_id
                    """

                    result = await conn.fetchrow(
                        query,
                        catalog_id,
                        provider,
                        model_name,
                        model_version or None,
                        input_price,
                        output_price,
                        max_tokens if max_tokens > 0 else None,
                        context_window if context_window > 0 else None,
                        supports_streaming,
                        supports_function_calling,
                        supports_vision,
                        requests_per_minute if requests_per_minute > 0 else None,
                        tokens_per_minute if tokens_per_minute > 0 else None,
                    )

        if result:
            console.print(
                Panel(
                    f"[green]✓ Model added successfully[/green]\n\n"
                    f"[cyan]ID:[/cyan] {catalog_id}\n"
                    f"[cyan]Provider:[/cyan] {provider}\n"
                    f"[cyan]Model:[/cyan] {model_name}",
                    title="Success",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    "[yellow]Model already exists[/yellow]",
                    title="Duplicate Detected",
                    border_style="yellow",
                )
            )

    asyncio.run(run())


if __name__ == "__main__":
    cli()
