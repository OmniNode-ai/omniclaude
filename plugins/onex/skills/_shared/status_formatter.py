#!/usr/bin/env python3
"""
Status Formatter - Shared utilities for formatting status output

Provides functions for:
- JSON formatting
- Table formatting (text-based)
- Markdown generation
- Status indicators (✓, ✗, ⚠)

Usage:
    from status_formatter import format_json, format_table, format_status_indicator

Created: 2025-11-12
"""

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


class StatusJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for status data types."""

    def default(self, obj):
        """Handle special data types."""
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def format_json(data: dict[str, Any], pretty: bool = True) -> str:
    """
    Format data as JSON.

    Args:
        data: Data to format
        pretty: Pretty print with indentation (default: True)

    Returns:
        JSON string
    """
    if pretty:
        return json.dumps(data, indent=2, cls=StatusJSONEncoder)
    else:
        return json.dumps(data, cls=StatusJSONEncoder)


def format_status_indicator(status: str) -> str:
    """
    Get status indicator symbol.

    Args:
        status: Status string (e.g., "healthy", "ok", "connected", "error", "failed")

    Returns:
        Status indicator (✓, ✗, ⚠, i)
    """
    status_lower = status.lower()

    # Success indicators
    if status_lower in ["healthy", "ok", "connected", "success", "running", "true"]:
        return "✓"

    # Error indicators
    if status_lower in [
        "error",
        "failed",
        "unhealthy",
        "unreachable",
        "critical",
        "false",
    ]:
        return "✗"

    # Warning indicators
    if status_lower in ["warning", "degraded", "timeout", "stopped"]:
        return "⚠"

    # Info indicators
    return "ℹ"  # noqa: RUF001 - intentional Unicode info symbol


def format_table(
    headers: list[str], rows: list[list[Any]], title: str | None = None
) -> str:
    """
    Format data as text-based table.

    Args:
        headers: Column headers
        rows: Data rows
        title: Optional table title

    Returns:
        Formatted table string
    """
    # Calculate column widths from headers
    col_widths = [len(h) for h in headers]

    # Expand to accommodate longest row (prevent IndexError)
    max_cols = max([len(row) for row in rows] + [len(headers)])
    col_widths.extend([0] * (max_cols - len(col_widths)))

    # Update widths based on row data
    for row_idx, row in enumerate(rows):
        # Warn if row has more columns than headers (potential data loss)
        if len(row) > len(headers):
            logger.warning(
                f"Row {row_idx} has {len(row)} columns but only {len(headers)} headers - "
                f"extra columns will be appended without proper alignment"
            )

        for i, cell in enumerate(row):
            cell_str = str(cell)
            col_widths[i] = max(col_widths[i], len(cell_str))

    # Build table
    output = []

    # Add title if provided
    if title:
        total_width = sum(col_widths) + 3 * (len(headers) - 1)
        output.append("=" * total_width)
        output.append(title)
        output.append("=" * total_width)

    # Add header row
    header_row = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    output.append(header_row)

    # Add separator
    separator = "-+-".join("-" * w for w in col_widths)
    output.append(separator)

    # Add data rows
    for row in rows:
        row_parts = []
        for i, cell in enumerate(row):
            if i < len(col_widths):
                row_parts.append(str(cell).ljust(col_widths[i]))
            else:
                # Extra columns beyond headers - just append as-is
                row_parts.append(str(cell))
        row_str = " | ".join(row_parts)
        output.append(row_str)

    return "\n".join(output)


def format_markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    """
    Format data as Markdown table.

    Args:
        headers: Column headers
        rows: Data rows

    Returns:
        Markdown table string
    """
    output = []

    # Add header row
    header_row = "| " + " | ".join(headers) + " |"
    output.append(header_row)

    # Add separator
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    output.append(separator)

    # Add data rows
    for row in rows:
        row_str = "| " + " | ".join(str(cell) for cell in row) + " |"
        output.append(row_str)

    return "\n".join(output)


def format_status_summary(data: dict[str, Any]) -> str:
    """
    Format a status summary with indicators.

    Args:
        data: Status data dictionary

    Returns:
        Formatted summary string
    """
    output = []

    for key, value in data.items():
        # Format key
        key_formatted = key.replace("_", " ").title()

        # Format value with indicator if boolean or status string
        if isinstance(value, bool):
            indicator = format_status_indicator("ok" if value else "error")
            value_str = "Yes" if value else "No"
            output.append(f"{indicator} {key_formatted}: {value_str}")
        elif isinstance(value, str) and value.lower() in [
            "healthy",
            "ok",
            "connected",
            "error",
            "failed",
            "warning",
            "degraded",
        ]:
            indicator = format_status_indicator(value)
            output.append(f"{indicator} {key_formatted}: {value}")
        else:
            output.append(f"  {key_formatted}: {value}")

    return "\n".join(output)


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Format a value as percentage.

    This function handles two input formats:
    - Fractional values (0.0-1.0): Treated as decimal fractions and multiplied by 100
    - Whole percentages (>1.0): Treated as already-converted percentages

    Args:
        value: Numeric value to format as percentage
            - If 0.0 <= value <= 1.0: Treated as fraction (e.g., 0.95 → 95%)
            - If value > 1.0: Treated as whole percentage (e.g., 95 → 95%)
        decimals: Number of decimal places in output (default: 1)

    Returns:
        Formatted percentage string with '%' suffix

    Examples:
        Fractional input (0.0-1.0):
        >>> format_percentage(0.0)
        '0.0%'
        >>> format_percentage(0.5)
        '50.0%'
        >>> format_percentage(0.95)
        '95.0%'
        >>> format_percentage(1.0)
        '100.0%'

        Whole percentage input (>1.0):
        >>> format_percentage(50)
        '50.0%'
        >>> format_percentage(95)
        '95.0%'
        >>> format_percentage(100)
        '100.0%'

        Custom decimal places:
        >>> format_percentage(0.9567, decimals=2)
        '95.67%'
        >>> format_percentage(0.9567, decimals=0)
        '96%'

    Note:
        Boundary condition: The value 1.0 is treated as a fraction (100%).
        This handles the common case where 1.0 represents "100% complete".
        Only values strictly greater than 1.0 are treated as pre-converted percentages.
    """
    # Decision boundary: values <= 1.0 are fractions (need *100 conversion)
    # Only values > 1.0 are treated as already-converted percentages
    if value <= 1.0:
        # Fraction format: multiply by 100 to convert to percentage
        percentage = value * 100
    else:
        # Already a whole percentage: use as-is
        percentage = value

    return f"{percentage:.{decimals}f}%"


def format_duration(milliseconds: int) -> str:
    """
    Format duration in human-readable format.

    Args:
        milliseconds: Duration in milliseconds

    Returns:
        Formatted duration string (e.g., "1.5s", "250ms")
    """
    if milliseconds < 1000:
        return f"{milliseconds}ms"
    elif milliseconds < 60000:
        seconds = milliseconds / 1000
        return f"{seconds:.1f}s"
    else:
        minutes = milliseconds / 60000
        return f"{minutes:.1f}m"


def format_bytes(bytes_count: int) -> str:
    """
    Format bytes in human-readable format.

    Args:
        bytes_count: Number of bytes

    Returns:
        Formatted byte string (e.g., "1.5 GB", "250 MB")
    """
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_count)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    return f"{size:.1f} {units[unit_index]}"


def format_timestamp(timestamp: datetime | None = None) -> str:
    """
    Format timestamp in ISO format.

    Args:
        timestamp: Datetime object (default: now)

    Returns:
        ISO formatted timestamp string
    """
    if timestamp is None:
        timestamp = datetime.now(UTC)

    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_markdown_report(title: str, sections: list[dict[str, Any]]) -> str:
    """
    Generate a complete Markdown report.

    Args:
        title: Report title
        sections: List of sections, each with 'title', 'content', and optional 'table'

    Returns:
        Complete Markdown report string
    """
    output = []

    # Add title
    output.append(f"# {title}")
    output.append("")
    output.append(f"**Generated**: {format_timestamp()}")
    output.append("")

    # Add sections
    for section in sections:
        section_title = section.get("title", "Section")
        content = section.get("content", "")
        table = section.get("table")

        # Add section title
        output.append(f"## {section_title}")
        output.append("")

        # Add content
        if content:
            output.append(content)
            output.append("")

        # Add table if provided
        if table:
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            if headers and rows:
                output.append(format_markdown_table(headers, rows))
                output.append("")

    return "\n".join(output)


if __name__ == "__main__":
    # Test formatter functions
    print("Testing Status Formatter...")

    print("\n1. Status Indicators:")
    statuses = ["healthy", "error", "warning", "unknown"]
    for status in statuses:
        indicator = format_status_indicator(status)
        print(f"  {indicator} {status}")

    print("\n2. Table Format:")
    headers = ["Service", "Status", "Uptime"]
    rows = [
        ["archon-intelligence", "healthy", "5d 3h"],
        ["archon-qdrant", "healthy", "5d 3h"],
        ["archon-bridge", "healthy", "5d 3h"],
    ]
    table = format_table(headers, rows, title="Service Status")
    print(table)

    print("\n3. Duration Format:")
    durations = [50, 500, 1500, 65000]
    for ms in durations:
        print(f"  {ms}ms = {format_duration(ms)}")

    print("\n4. Bytes Format:")
    sizes = [1024, 1048576, 1073741824]
    for size in sizes:
        print(f"  {size} bytes = {format_bytes(size)}")
