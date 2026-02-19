"""Secure credential storage for Memex CLI."""

import os
import json
from pathlib import Path
from typing import Optional

from cli.config.settings import get_settings


def get_credentials_path() -> Path:
    """Get path to credentials file."""
    settings = get_settings()
    return settings.config_dir / "credentials.json"


def ensure_config_dir():
    """Ensure config directory exists with proper permissions."""
    settings = get_settings()
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    # Set directory permissions to user-only on Unix
    try:
        os.chmod(settings.config_dir, 0o700)
    except Exception:
        pass


def save_api_key(provider: str, api_key: str):
    """Save an API key for a provider."""
    ensure_config_dir()
    creds_path = get_credentials_path()

    # Load existing credentials
    creds = {}
    if creds_path.exists():
        try:
            with open(creds_path, "r") as f:
                creds = json.load(f)
        except Exception:
            pass

    # Update credentials
    creds[provider] = {"api_key": api_key}

    # Save with restricted permissions
    with open(creds_path, "w") as f:
        json.dump(creds, f, indent=2)

    # Set file permissions to user-only
    try:
        os.chmod(creds_path, 0o600)
    except Exception:
        pass


def get_api_key(provider: str) -> Optional[str]:
    """Get API key for a provider.

    Checks in order:
    1. Environment variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, or XAI_API_KEY)
    2. Credentials file
    """
    # Check environment first
    env_vars = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "grok": "XAI_API_KEY",
    }
    env_var = env_vars.get(provider)
    if env_var:
        key = os.environ.get(env_var)
        if key:
            return key

    # Check credentials file
    creds_path = get_credentials_path()
    if creds_path.exists():
        try:
            with open(creds_path, "r") as f:
                creds = json.load(f)
                if provider in creds:
                    return creds[provider].get("api_key")
        except Exception:
            pass

    return None


def delete_api_key(provider: str) -> bool:
    """Delete an API key for a provider."""
    creds_path = get_credentials_path()
    if not creds_path.exists():
        return False

    try:
        with open(creds_path, "r") as f:
            creds = json.load(f)

        if provider in creds:
            del creds[provider]
            with open(creds_path, "w") as f:
                json.dump(creds, f, indent=2)
            return True
    except Exception:
        pass

    return False


def get_configured_providers() -> list[str]:
    """Get list of providers that have API keys configured."""
    providers = []

    for provider in ["anthropic", "openai", "grok"]:
        if get_api_key(provider):
            providers.append(provider)

    return providers


def get_default_provider() -> Optional[str]:
    """Get the default AI provider (first configured one)."""
    settings = get_settings()

    # Check if preferred provider is configured
    if get_api_key(settings.ai_provider):
        return settings.ai_provider

    # Fall back to any configured provider
    configured = get_configured_providers()
    return configured[0] if configured else None


def get_prometheus_token() -> Optional[str]:
    """Get Prometheus API token for tunnel sync.

    Checks in order:
    1. MEMEX_PROMETHEUS_TOKEN environment variable
    2. credentials.json "prometheus" key
    """
    # Check environment first
    token = os.environ.get("MEMEX_PROMETHEUS_TOKEN")
    if token:
        return token

    # Check credentials file
    creds_path = get_credentials_path()
    if creds_path.exists():
        try:
            with open(creds_path, "r") as f:
                creds = json.load(f)
                if "prometheus" in creds:
                    return creds["prometheus"].get("api_key")
        except Exception:
            pass

    return None
