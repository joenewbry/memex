"""MCP HTTP server service for connecting Memex to Claude/Cursor."""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from cli.config import get_settings


class MCPService:
    """Service for managing the MCP HTTP server process."""

    def __init__(self):
        self.settings = get_settings()
        self.http_server = self.settings.mcp_server_path / "http_server.py"

    def is_running(self) -> tuple[bool, Optional[int]]:
        """Check if MCP HTTP server process is running. Returns (running, pid)."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "http_server.py"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                pid = int(result.stdout.strip().split("\n")[0])
                return True, pid
            return False, None
        except Exception:
            return False, None

    def start(self) -> tuple[bool, str]:
        """Start the MCP HTTP server in the background."""
        running, pid = self.is_running()
        if running:
            return False, f"Already running (pid {pid})"

        if not self.http_server.exists():
            return False, f"MCP server not found: {self.http_server}"

        # Prefer venv that has MCP deps (fastapi, uvicorn):
        # 1. uv run (mcp-server has pyproject.toml) - auto-manages deps
        # 2. project_root/.venv (install layout ~/.memex)
        # 3. mcp-server/.venv (repo layout)
        # 4. refinery/.venv
        use_uv = shutil.which("uv")
        cmd = []
        cwd = str(self.settings.mcp_server_path)

        if use_uv and (self.settings.mcp_server_path / "pyproject.toml").exists():
            cmd = ["uv", "run", "python", str(self.http_server), "--port", str(self.settings.mcp_http_port)]
        else:
            venv_python = self.settings.project_root / ".venv" / "bin" / "python"
            if not venv_python.exists():
                venv_python = self.settings.mcp_server_path / ".venv" / "bin" / "python"
            if not venv_python.exists():
                venv_python = self.settings.refinery_path / ".venv" / "bin" / "python"
            if not venv_python.exists():
                venv_python = Path.home() / ".memex" / ".venv" / "bin" / "python"
            python_path = str(venv_python) if venv_python.exists() else "python3"
            cmd = [python_path, str(self.http_server), "--port", str(self.settings.mcp_http_port)]

        try:
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True, f"Started (pid {process.pid}) on port {self.settings.mcp_http_port}"
        except Exception as e:
            return False, str(e)

    def stop(self) -> tuple[bool, str]:
        """Stop the MCP HTTP server."""
        running, pid = self.is_running()
        if not running:
            return False, "Not running"

        try:
            import os
            import signal
            os.kill(pid, signal.SIGTERM)
            return True, f"Stopped (pid {pid})"
        except ProcessLookupError:
            return False, "Process not found"
        except PermissionError:
            return False, "Permission denied"
        except Exception as e:
            return False, str(e)
