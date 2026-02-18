"""Chat command - interactive chat with Memex."""

import os
from datetime import datetime
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from cli.display.components import print_header, print_tip, format_number
from cli.display.colors import COLORS
from cli.display.tips import TipEngine
from cli.services.ai import AIService
from cli.commands.ask import (
    format_tool_call,
    format_tool_result,
    CHAT_GREETING,
)

console = Console()


def _handle_slash_command(query: str, ai: AIService, tip_engine: TipEngine) -> bool:
    """Handle a slash command. Returns True if command was handled."""
    parts = query.split(None, 1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        from cli.commands.help_cmd import print_chat_help
        print_chat_help()
        return True

    elif command == "/status":
        _cmd_status()
        return True

    elif command == "/stats":
        _cmd_stats()
        return True

    elif command == "/clear":
        ai.messages.clear()
        os.system("clear" if os.name != "nt" else "cls")
        console.print("  [dim]Conversation cleared.[/dim]")
        console.print()
        return True

    elif command == "/search":
        if not args:
            console.print("  [dim]Usage: /search <query>[/dim]")
            console.print()
            return True
        _cmd_search(args)
        return True

    elif command == "/tips":
        tip = tip_engine.force_tip()
        if tip:
            print_tip(tip)
        console.print()
        return True

    elif command.startswith("/"):
        console.print(f"  [dim]Unknown command: {command}. Type /help for available commands.[/dim]")
        console.print()
        return True

    return False


def _cmd_status():
    """Inline status check for chat."""
    try:
        from cli.services.health import HealthService
        health = HealthService()

        capture = health.check_capture_process()
        chroma = health.check_chroma_server()

        capture_status = f"[{COLORS['success']}]running[/]" if capture.running else f"[{COLORS['error']}]stopped[/]"
        chroma_status = f"[{COLORS['success']}]connected[/]" if chroma.running else f"[{COLORS['error']}]disconnected[/]"

        console.print(f"  Capture: {capture_status}  |  ChromaDB: {chroma_status}")
        console.print()
    except Exception as e:
        console.print(f"  [{COLORS['error']}]Could not check status:[/] {e}")
        console.print()


def _cmd_stats():
    """Inline stats for chat."""
    try:
        from cli.services.database import DatabaseService
        db = DatabaseService()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        stats = db.get_stats(start_date=today)
        captures = stats.get("captures", 0)
        words = stats.get("words", 0)
        screens = stats.get("screens", [])
        console.print(
            f"  Today: [bold]{format_number(captures)}[/bold] captures, "
            f"[bold]{format_number(words)}[/bold] words, "
            f"[bold]{len(screens)}[/bold] screens"
        )
        console.print()
    except Exception as e:
        console.print(f"  [{COLORS['error']}]Could not load stats:[/] {e}")
        console.print()


def _cmd_search(query: str):
    """Inline search for chat."""
    try:
        from cli.services.database import DatabaseService
        db = DatabaseService()
        results = db.search(query=query, limit=5)
        if not results:
            console.print(f"  No matches for \"{query}\".")
            console.print()
            return

        console.print(f"  Found [bold]{len(results)}[/bold] matches:")
        now = datetime.now()
        for r in results:
            ts = r.timestamp
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            delta = now - ts
            if delta.days == 0 and delta.seconds < 3600:
                time_str = f"{delta.seconds // 60}m ago"
            elif delta.days == 0:
                time_str = r.timestamp.strftime("%I:%M %p")
            elif delta.days == 1:
                time_str = "Yesterday"
            else:
                time_str = r.timestamp.strftime("%b %d")

            snippet = " ".join(r.text.split())[:80]
            img_flag = " 📷" if r.screenshot_path else ""
            console.print(f"  [dim]{time_str}[/dim] ({r.screen_name}{img_flag}) {snippet}...")
        console.print()
    except Exception as e:
        console.print(f"  [{COLORS['error']}]Search failed:[/] {e}")
        console.print()


def chat():
    """Start an interactive chat session with Memex."""
    print_header("Chat")

    ai = AIService()

    if not ai.is_configured():
        console.print(f"  [{COLORS['error']}]✗[/] No AI provider configured")
        console.print()
        console.print("  To chat with Memex, configure an API key first:")
        console.print("    [bold]memex auth login[/bold]")
        console.print()
        console.print("  Supports: Anthropic (Claude), OpenAI (GPT-4), or Grok (xAI)")
        console.print()
        return

    tip_engine = TipEngine()

    provider_name = ai.get_provider_name()
    console.print(f"  [dim]Using {provider_name}[/dim]")
    console.print()
    console.print(f"  [bold]{CHAT_GREETING}[/bold]")
    console.print()
    console.print("  [dim]Type /help for commands, or 'quit' to exit.[/dim]")
    console.print()

    while True:
        try:
            query = console.input(f"  [{COLORS['primary']}]>[/] ").strip()

            if not query:
                continue

            if query.lower() in ["quit", "exit", "q"]:
                console.print("  [dim]Goodbye![/dim]")
                break

            if query.startswith("/"):
                _handle_slash_command(query, ai, tip_engine)
                continue

            console.print()

            for event in ai.chat_stream(query):
                if event.type == "text":
                    console.print(event.content, end="")
                elif event.type == "tool_call":
                    console.print()
                    console.print(format_tool_call(event.tool_call))
                elif event.type == "tool_result" and event.tool_call:
                    console.print(format_tool_result(event.tool_call.name, event.tool_result or ""))
                    console.print()
                elif event.type == "error":
                    console.print(f"  [{COLORS['error']}]Error:[/] {event.content}")

            console.print()
            console.print()

            tip = tip_engine.maybe_show_tip()
            if tip:
                print_tip(tip)
                console.print()

        except KeyboardInterrupt:
            console.print()
            console.print("  [dim]Goodbye![/dim]")
            break
        except EOFError:
            break

    console.print()
