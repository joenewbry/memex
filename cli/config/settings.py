"""Settings and configuration for Memex CLI."""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Literal

# Determine the project root (where this repo is located)
CLI_DIR = Path(__file__).parent.parent
PROJECT_ROOT = CLI_DIR.parent

AIProvider = Literal["anthropic", "openai", "grok"]
HostingMode = Literal["local", "jetson", "remote"]


@dataclass
class Settings:
    """Memex CLI settings."""

    # Paths
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    refinery_path: Path = field(default_factory=lambda: PROJECT_ROOT / "refinery")
    mcp_server_path: Path = field(default_factory=lambda: PROJECT_ROOT / "mcp-server")
    ocr_data_path: Path = field(default_factory=lambda: PROJECT_ROOT / "refinery" / "data" / "ocr")
    audio_data_path: Path = field(default_factory=lambda: PROJECT_ROOT / "refinery" / "data" / "audio")
    chroma_path: Path = field(default_factory=lambda: PROJECT_ROOT / "refinery" / "chroma")

    # Screenshot storage
    screenshots_data_path: Path = field(default_factory=lambda: PROJECT_ROOT / "refinery" / "data" / "images")
    screenshot_max_width: int = 1280
    screenshot_jpeg_quality: int = 70

    # ChromaDB settings
    chroma_host: str = "localhost"
    chroma_port: int = 8000

    # MCP HTTP server (for Claude/Cursor connection)
    mcp_http_port: int = 8082
    chroma_collection: str = "screen_ocr_history"
    chroma_multimodal_collection: str = "screen_multimodal"

    # Hosting mode (overridden from instance.json if present)
    hosting_mode: HostingMode = "jetson"

    # Capture settings
    capture_interval: int = 60  # seconds
    audio_rotation_interval: int = 300  # seconds

    # AI settings
    ai_provider: AIProvider = "anthropic"
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"
    grok_model: str = "grok-2"

    # Config file location
    config_dir: Path = field(default_factory=lambda: Path.home() / ".memex")

    def __post_init__(self):
        """Ensure paths are Path objects and apply instance config overrides."""
        if isinstance(self.project_root, str):
            self.project_root = Path(self.project_root)
        if isinstance(self.refinery_path, str):
            self.refinery_path = Path(self.refinery_path)
        if isinstance(self.mcp_server_path, str):
            self.mcp_server_path = Path(self.mcp_server_path)
        if isinstance(self.ocr_data_path, str):
            self.ocr_data_path = Path(self.ocr_data_path)
        if isinstance(self.audio_data_path, str):
            self.audio_data_path = Path(self.audio_data_path)
        if isinstance(self.chroma_path, str):
            self.chroma_path = Path(self.chroma_path)
        if isinstance(self.config_dir, str):
            self.config_dir = Path(self.config_dir)
        if isinstance(self.screenshots_data_path, str):
            self.screenshots_data_path = Path(self.screenshots_data_path)

        # Load instance config and override connection settings
        self._apply_instance_config()

    def _apply_instance_config(self):
        """Load instance.json and override chroma_host/port/mcp_http_port based on hosting mode."""
        instance_path = self.config_dir / "instance.json"
        if not instance_path.exists():
            return

        try:
            with open(instance_path, "r") as f:
                data = json.load(f)
        except Exception:
            return

        mode = data.get("hosting_mode", "jetson")
        self.hosting_mode = mode

        if mode == "jetson":
            jetson_host = data.get("jetson_host", "")
            if jetson_host:
                self.chroma_host = jetson_host
            self.chroma_port = data.get("jetson_chroma_port", self.chroma_port)
            self.mcp_http_port = data.get("jetson_mcp_port", self.mcp_http_port)
        elif mode == "remote":
            remote_host = data.get("remote_host", "")
            if remote_host:
                self.chroma_host = remote_host
            self.chroma_port = data.get("remote_chroma_port", self.chroma_port)
            self.mcp_http_port = data.get("remote_mcp_port", self.mcp_http_port)
        elif mode == "local":
            self.chroma_host = data.get("local_chroma_host", "localhost")
            self.chroma_port = data.get("local_chroma_port", self.chroma_port)
            self.mcp_http_port = data.get("local_mcp_port", self.mcp_http_port)


# Singleton settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
