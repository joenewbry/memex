"""Search command - search your history."""

from datetime import datetime, timedelta
from typing import Optional
import typer
from rich.console import Console
from rich.text import Text

from cli.display.components import print_header, format_number
from cli.display.colors import COLORS
from cli.services.database import DatabaseService

console = Console()


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse a date string (supports natural language)."""
    date_str = date_str.lower().strip()
    now = datetime.now()

    # Natural language
    if date_str == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_str == "yesterday":
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_str == "last week":
        return now - timedelta(days=7)
    elif date_str == "last month":
        return now - timedelta(days=30)

    # Try various formats
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d",
        "%b %d",
        "%B %d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # If no year, assume current year
            if dt.year == 1900:
                dt = dt.replace(year=now.year)
            return dt
        except ValueError:
            continue

    return None


def highlight_match(text: str, query: str, context_chars: int = 100) -> str:
    """Extract and highlight matching portion of text."""
    query_lower = query.lower()
    text_lower = text.lower()

    pos = text_lower.find(query_lower)
    if pos == -1:
        # No match, return truncated text
        return text[:context_chars * 2] + "..." if len(text) > context_chars * 2 else text

    # Get context around match
    start = max(0, pos - context_chars)
    end = min(len(text), pos + len(query) + context_chars)

    snippet = text[start:end]

    # Add ellipsis if truncated
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    return snippet


def search(
    query: str = typer.Argument(..., help="Search query"),
    from_date: Optional[str] = typer.Option(
        None, "--from", "-f", help="Start date (e.g., 'yesterday', '2024-01-15')"
    ),
    to_date: Optional[str] = typer.Option(
        None, "--to", "-t", help="End date"
    ),
    screen: Optional[str] = typer.Option(
        None, "--screen", "-s", help="Filter by screen name"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of results"),
    full: bool = typer.Option(False, "--full", help="Show full text"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Search your screen history."""
    db = DatabaseService()

    # Parse dates
    start_dt = parse_date(from_date) if from_date else None
    end_dt = parse_date(to_date) if to_date else None

    # Perform search
    results = db.search(
        query=query,
        limit=limit,
        start_date=start_dt,
        end_date=end_dt,
    )

    # Filter by screen if specified
    if screen:
        results = [r for r in results if screen.lower() in r.screen_name.lower()]

    if json_output:
        import json
        output = []
        for r in results:
            entry = {
                "timestamp": r.timestamp.isoformat(),
                "screen": r.screen_name,
                "word_count": r.word_count,
                "text": r.text if full else r.text[:200],
                "relevance": r.relevance,
            }
            if r.screenshot_path:
                entry["screenshot_path"] = r.screenshot_path
            output.append(entry)
        console.print(json.dumps(output, indent=2))
        return

    print_header(f'Search: "{query}"')

    if not results:
        console.print("  No matches found.")
        console.print()
        console.print("  [dim]Tips:[/dim]")
        console.print("  [dim]  - Try a broader search term[/dim]")
        console.print("  [dim]  - Check the date range with --from and --to[/dim]")
        console.print("  [dim]  - Make sure memex is running (memex status)[/dim]")
        console.print()
        return

    total = len(results)
    console.print(f"  Found [bold]{format_number(total)}[/bold] matches", end="")
    if total > limit:
        console.print(f" (showing top {limit})")
    else:
        console.print()
    console.print()

    now = datetime.now()

    for i, result in enumerate(results[:limit], 1):
        # Format timestamp - handle timezone-aware timestamps
        result_ts = result.timestamp
        if result_ts.tzinfo is not None:
            result_ts = result_ts.replace(tzinfo=None)
        delta = now - result_ts
        if delta.days == 0:
            if delta.seconds < 3600:
                time_str = f"{delta.seconds // 60} min ago"
            else:
                time_str = f"Today {result.timestamp.strftime('%I:%M %p')}"
        elif delta.days == 1:
            time_str = f"Yesterday {result.timestamp.strftime('%I:%M %p')}"
        elif delta.days < 7:
            time_str = result.timestamp.strftime("%A %I:%M %p")
        else:
            time_str = result.timestamp.strftime("%b %d %I:%M %p")

        # Print result
        console.print(f"  [bold]{i}.[/bold] {time_str} [dim]({result.screen_name})[/dim]")
        console.print(f"     [dim]{'─' * 55}[/dim]")

        if full:
            # Show full text with wrapping
            lines = result.text.split("\n")
            for line in lines[:20]:  # Limit to 20 lines
                console.print(f"     {line[:100]}")
            if len(lines) > 20:
                console.print(f"     [dim]... ({len(lines) - 20} more lines)[/dim]")
        else:
            # Show highlighted snippet
            snippet = highlight_match(result.text, query)
            # Clean up whitespace
            snippet = " ".join(snippet.split())
            console.print(f"     {snippet}")

        if result.screenshot_path:
            console.print(f"     [dim]📷 {result.screenshot_path}[/dim]")

        console.print()

    console.print(f"  [dim]{'─' * 55}[/dim]")
    console.print("  [dim]Tip: Use --full to see complete text, --json for export[/dim]")
    console.print()
