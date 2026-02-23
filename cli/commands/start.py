"""Start command - start capture daemon."""

import subprocess
import time
import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from cli.display.components import print_header, print_success, print_error, print_warning
from cli.display.colors import COLORS
from cli.services.capture import CaptureService
from cli.services.chroma import get_chroma_command
from cli.services.health import HealthService
from cli.services.mcp import MCPService
from cli.services.instance import InstanceService, InstanceConfig
from cli.config import get_settings
from cli.config.credentials import get_configured_providers

console = Console()


def _wait_for_service(check_fn, timeout=15, interval=1):
    """Poll a health check function until it reports running or timeout is reached."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(interval)
        result = check_fn()
        if result.running:
            return result
    return result


def _first_run_setup() -> InstanceConfig:
    """Interactive first-run setup: pick hosting mode and configure instance."""
    console.print()
    console.print(f"  [{COLORS['primary']}]Welcome to Memex![/] Let's set up your instance.")
    console.print()
    console.print("  How do you want to host your data?")
    console.print()
    console.print(f"  [bold][1][/bold] Jetson Orin Nano  - Always-on, GPU-powered, Cloudflare Tunnel [{COLORS['success']}](recommended)[/]")
    console.print(f"  [bold][2][/bold] Local             - Everything on this machine")
    console.print(f"  [bold][3][/bold] Remote server     - Capture here, serve from a VPS")
    console.print()

    choice = Prompt.ask("  Choose", choices=["1", "2", "3"], default="1")

    mode_map = {"1": "jetson", "2": "local", "3": "remote"}
    mode = mode_map[choice]

    instance_name = Prompt.ask("  Instance name", default="personal")

    config = InstanceConfig(hosting_mode=mode, instance_name=instance_name)

    if mode == "jetson":
        config.jetson_host = Prompt.ask("  Jetson hostname or IP", default="192.168.1.100")
        tunnel = Prompt.ask("  Cloudflare Tunnel URL (optional, press Enter to skip)", default="")
        config.jetson_tunnel_url = tunnel

    elif mode == "remote":
        config.remote_host = Prompt.ask("  Remote hostname or IP")
        port = Prompt.ask("  SSH port", default="22")
        config.remote_ssh_port = int(port)
        tunnel = Prompt.ask("  Tunnel URL (optional, press Enter to skip)", default="")
        config.remote_tunnel_url = tunnel

    # Save config
    svc = InstanceService()
    svc.save(config)

    console.print()
    if mode == "jetson":
        target = config.jetson_host
        if config.jetson_tunnel_url:
            target += f" + {config.jetson_tunnel_url}"
        print_success(f"Instance configured: jetson mode -> {target}")
    elif mode == "remote":
        print_success(f"Instance configured: remote mode -> {config.remote_host}")
    else:
        print_success("Instance configured: local mode")

    console.print()
    return config


def _start_local(health, capture, mcp_svc, settings, foreground, no_chroma, start_mcp):
    """Start in local mode: ChromaDB + MCP + capture all on this machine."""
    # Check ChromaDB
    chroma_check = health.check_chroma_server()
    if not chroma_check.running and not no_chroma:
        console.print(f"  [{COLORS['muted']}]○[/] ChromaDB not running, starting...")

        chroma_exe, chroma_cmd = get_chroma_command()
        if not chroma_cmd:
            print_error("ChromaDB not found in venv or PATH")
            console.print()
            console.print("  [dim]To fix:[/dim]")
            console.print("    • Re-run [bold]./install.sh[/bold] to ensure ~/.memex venv has chromadb")
            console.print("    • Or: ~/.memex/.venv/bin/pip install chromadb")
            console.print("    • Or from repo: pip install chromadb (in your venv)")
            console.print()
        else:
            try:
                subprocess.Popen(
                    chroma_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                chroma_check = _wait_for_service(health.check_chroma_server)
                if chroma_check.running:
                    print_success(f"ChromaDB started ({settings.chroma_host}:{settings.chroma_port})")
                else:
                    print_error("ChromaDB failed to start")
                    console.print()
                    console.print("  [dim]To fix:[/dim]")
                    console.print(f"    • Try manually: chroma run --host {settings.chroma_host} --port {settings.chroma_port}")
                    console.print("    • Run [bold]memex doctor[/bold] for full diagnostics")
                    console.print()
            except FileNotFoundError:
                print_error("ChromaDB command not found")
                console.print()
                console.print("  [dim]To fix: ./install.sh or ~/.memex/.venv/bin/pip install chromadb[/dim]")
                console.print()
    elif chroma_check.running:
        print_success(f"ChromaDB already running ({settings.chroma_host}:{settings.chroma_port})")

    # Start MCP server if requested
    if start_mcp:
        _start_mcp_server(health, mcp_svc, settings)

    # Start capture
    _start_capture(health, capture, settings, foreground)


def _start_jetson(health, capture, mcp_svc, settings, instance_config, foreground, start_mcp):
    """Start in Jetson mode: capture locally, verify Jetson ChromaDB + MCP are reachable."""
    # Verify Jetson ChromaDB is reachable
    chroma_check = health.check_chroma_server()
    if chroma_check.running:
        print_success(f"Jetson ChromaDB reachable ({settings.chroma_host}:{settings.chroma_port})")
    else:
        print_warning(f"Cannot reach Jetson ChromaDB at {settings.chroma_host}:{settings.chroma_port}")
        console.print("  [dim]Ensure ChromaDB is running on the Jetson and the network is reachable.[/dim]")
        console.print()

    # Check tunnel URL if configured
    tunnel_url = instance_config.get_tunnel_url()
    if tunnel_url:
        tunnel_check = health.check_remote_url(tunnel_url)
        if tunnel_check.running:
            print_success(f"Cloudflare Tunnel reachable ({tunnel_url})")
        else:
            print_warning(f"Tunnel not reachable: {tunnel_url}")

    # Start MCP server locally if requested (for local Claude/Cursor connection)
    if start_mcp:
        _start_mcp_server(health, mcp_svc, settings)

    # Start capture locally
    _start_capture(health, capture, settings, foreground)


def _start_remote(health, capture, mcp_svc, settings, instance_config, foreground, start_mcp):
    """Start in remote mode: capture locally, verify remote SSH + services."""
    # Verify SSH connectivity
    ssh_check = health.check_ssh_connection(
        instance_config.remote_host,
        instance_config.remote_ssh_port,
    )
    if ssh_check.running:
        print_success(f"Remote host reachable ({instance_config.remote_host})")
    else:
        print_warning(f"Cannot reach remote host: {ssh_check.details}")

    # Verify remote ChromaDB
    chroma_check = health.check_chroma_server()
    if chroma_check.running:
        print_success(f"Remote ChromaDB reachable ({settings.chroma_host}:{settings.chroma_port})")
    else:
        print_warning(f"Cannot reach remote ChromaDB at {settings.chroma_host}:{settings.chroma_port}")

    # Check tunnel URL if configured
    tunnel_url = instance_config.get_tunnel_url()
    if tunnel_url:
        tunnel_check = health.check_remote_url(tunnel_url)
        if tunnel_check.running:
            print_success(f"Tunnel reachable ({tunnel_url})")
        else:
            print_warning(f"Tunnel not reachable: {tunnel_url}")

    # Start MCP server locally if requested
    if start_mcp:
        _start_mcp_server(health, mcp_svc, settings)

    # Start capture locally
    _start_capture(health, capture, settings, foreground)


def _start_mcp_server(health, mcp_svc, settings):
    """Start the MCP HTTP server."""
    mcp_running, mcp_pid = mcp_svc.is_running()
    if mcp_running:
        console.print(f"  [{COLORS['muted']}]○[/] MCP server already running (pid {mcp_pid})")
    else:
        success, message = mcp_svc.start()
        if success:
            mcp_verify = _wait_for_service(health.check_mcp_server)
            if mcp_verify.running:
                print_success(f"MCP server started - connect Claude/Cursor to port {settings.mcp_http_port}")
            else:
                print_warning("MCP server process started but is not responding on port 8082")
                console.print()
                console.print("  [dim]The server may have crashed. Common fixes:[/dim]")
                console.print("    • Install uv and run: cd mcp-server && uv sync (ensures fastapi, uvicorn)")
                console.print("    • Or: pip install -r mcp-server/requirements.txt (use your venv)")
                console.print("    • Re-run [bold]./install.sh[/bold] to refresh ~/.memex (if using install)")
                console.print("    • Run [bold]memex doctor[/bold] for full diagnostics")
                console.print()
        else:
            print_error(f"MCP server failed: {message}")
            console.print()
            console.print("  [dim]To fix:[/dim]")
            console.print("    • Ensure mcp-server is installed: ~/.memex/mcp-server/ or repo mcp-server/")
            console.print("    • Install deps: pip install -r mcp-server/requirements.txt")
            console.print("    • Run [bold]memex doctor[/bold] for diagnostics")
            console.print()


def _start_capture(health, capture, settings, foreground):
    """Start the screen capture process."""
    console.print(f"  [{COLORS['muted']}]○[/] Starting screen capture...")

    if foreground:
        print_success("Screen capture starting in foreground")
        console.print()
        console.print("  [dim]Press Ctrl+C to stop[/dim]")
        console.print()

        success, message = capture.start(foreground=True)
        if not success:
            print_error(message)
    else:
        success, message = capture.start(foreground=False)
        if success:
            time.sleep(1)
            capture_running, capture_pid = capture.is_running()
            if capture_running:
                print_success(f"Screen capture started ({message})")

                screens = health.get_unique_screens()
                if screens:
                    print_success(f"Monitoring {len(screens)} screens")
                else:
                    print_success("Monitoring screens (will detect on first capture)")

                console.print()
                console.print("  Memex is now recording. Run [bold]memex status[/bold] to check.")
            else:
                print_warning("Screen capture process exited immediately")
                console.print()
                console.print("  [dim]Possible causes:[/dim]")
                console.print("    • Missing Tesseract: brew install tesseract (macOS)")
                console.print("    • Screen Recording permission: System Settings -> Privacy & Security")
                console.print(f"    • Check refinery path: {settings.refinery_path}")
                console.print("    • Run [bold]memex doctor[/bold] for full diagnostics")
                console.print()
        else:
            print_error(f"Failed to start: {message}")
            console.print()
            console.print("  [dim]Run [bold]memex doctor[/bold] for diagnostics and fix suggestions.[/dim]")
            console.print()


def start(
    foreground: bool = typer.Option(
        False, "--foreground", "-f", help="Run in foreground with live output"
    ),
    no_chroma: bool = typer.Option(
        False, "--no-chroma", help="Don't auto-start ChromaDB"
    ),
    mcp: bool = typer.Option(
        None, "--mcp/--no-mcp", help="Start MCP server for Claude/Cursor (prompts if not specified)"
    ),
    skip_token_check: bool = typer.Option(
        False, "--skip-token-check", help="Skip AI token requirement (not recommended)"
    ),
):
    """Start the capture daemon. Requires a valid AI token (Anthropic, OpenAI, or Grok) for chat."""
    print_header("Starting")

    # First-run setup: if no instance.json exists, run interactive setup
    instance_svc = InstanceService()
    if not instance_svc.exists():
        instance_config = _first_run_setup()
        # Re-read settings so host overrides take effect
        from cli.config.settings import _settings
        import cli.config.settings as settings_mod
        settings_mod._settings = None
    else:
        instance_config = instance_svc.load()

    capture = CaptureService()
    health = HealthService()
    mcp_svc = MCPService()
    settings = get_settings()

    mode = instance_config.hosting_mode
    console.print(f"  [{COLORS['muted']}]Hosting mode:[/] [bold]{mode}[/bold]")
    console.print()

    # Require valid AI token (unless skipped)
    if not skip_token_check:
        configured = get_configured_providers()
        if not configured:
            print_error("No AI token configured. Memex requires Anthropic, OpenAI, or Grok for chat.")
            console.print()
            console.print("  Configure an API key first:")
            console.print("    [bold]memex auth login[/bold]")
            console.print()
            console.print("  Or set an environment variable:")
            console.print("    export ANTHROPIC_API_KEY=sk-ant-...")
            console.print("    export OPENAI_API_KEY=sk-...")
            console.print("    export XAI_API_KEY=xai-...")
            console.print()
            return

    # Determine whether to start a local MCP server
    start_mcp = mcp
    if mcp is None:
        if mode == "local":
            console.print(f"  Start MCP server for connecting Memex to Claude or other tools? (port {settings.mcp_http_port})")
            start_mcp = Confirm.ask("  Start MCP server?", default=False)
            console.print()
        else:
            # Jetson/remote modes: MCP server runs on the remote host, not locally
            start_mcp = False

    # Check if already running - stop it so we can restart fresh
    running, pid = capture.is_running()
    if running:
        console.print(f"  [{COLORS['muted']}]○[/] Stopping existing capture process (pid {pid})...")
        success, _ = capture.stop()
        time.sleep(1)
        still_running, _ = capture.is_running()
        if still_running:
            print_warning("Could not stop existing process. Run [bold]memex stop[/bold] first, then try again.")
            console.print()
            return
        console.print()

    # Dispatch based on hosting mode
    if mode == "local":
        _start_local(health, capture, mcp_svc, settings, foreground, no_chroma, start_mcp)
    elif mode == "jetson":
        _start_jetson(health, capture, mcp_svc, settings, instance_config, foreground, start_mcp)
    elif mode == "remote":
        _start_remote(health, capture, mcp_svc, settings, instance_config, foreground, start_mcp)
    else:
        # Fallback to local behavior
        _start_local(health, capture, mcp_svc, settings, foreground, no_chroma, start_mcp)

    console.print()
