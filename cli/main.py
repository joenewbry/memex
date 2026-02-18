"""Memex CLI - Main application entry point."""

import typer
from rich.console import Console

from cli import __version__
from cli.display.components import print_logo
from cli.display.colors import COLORS

app = typer.Typer(
    name="memex",
    help="Your digital memory - search and analyze your screen history.",
    no_args_is_help=False,
    add_completion=True,
)
console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"memex version {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
):
    """Memex - Your digital memory."""
    if ctx.invoked_subcommand is None:
        print_logo()
        A = COLORS["accent"]

        console.print(f"  [{A}]Track your work[/]")
        console.print("    status     Quick health check")
        console.print("    stats      Activity statistics")
        console.print("    graph      Usage graph (--live to watch)")
        console.print("    standup    Daily standup summary")
        console.print()
        console.print(f"  [{A}]Search & learn[/]")
        console.print("    ask        AI-powered search (streaming)")
        console.print("    chat       Interactive chat with your history")
        console.print("    search     Direct text search")
        console.print()
        console.print(f"  [{A}]Capture[/]")
        console.print("    start      Start screen capture")
        console.print("    stop       Stop capture")
        console.print("    watch      Live capture view")
        console.print()
        console.print(f"  [{A}]Manage[/]")
        console.print("    auth       API keys")
        console.print("    config     Settings")
        console.print("    sync       Sync to database")
        console.print("    logs       Service logs")
        console.print("    doctor     Full diagnostics")
        console.print()
        console.print("  [dim]Run 'memex <command> --help' for details.[/dim]")


# Import and register commands
from cli.commands import status, doctor, stats, search, start, stop, watch, sync, config, auth, ask, chat, contact, help_cmd, logs as logs_cmd, standup, automate, graph, record

app.command()(status.status)
app.command()(doctor.doctor)
app.command()(stats.stats)
app.command()(search.search)
app.command()(ask.ask)
app.command("chat")(chat.chat)
app.command("contact")(contact.contact)
app.command("help")(help_cmd.help_cmd)
app.command()(start.start)
app.command()(stop.stop)
app.command()(watch.watch)
app.command()(sync.sync)
app.command("logs")(logs_cmd.logs)
app.command()(standup.standup)
app.command("graph")(graph.graph)
app.add_typer(config.app, name="config")
app.add_typer(auth.app, name="auth")
app.add_typer(automate.app, name="automate")
app.add_typer(record.app, name="record")


if __name__ == "__main__":
    app()
