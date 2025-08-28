"""
Configuration management using Dynaconf and Pydantic.

This module provides a robust, layered configuration system. It uses Dynaconf
to load settings from files (e.g., `settings.toml`, `.secrets.toml`) and
environment variables. Pydantic is then used to validate the loaded data and
provide a typed `FlaccidSettings` object.

The `get_settings` function provides a singleton instance of the settings,
ensuring consistent configuration throughout the application.
"""
from pathlib import Path
from typing import Optional

from dynaconf import Dynaconf
from pydantic import BaseModel, Field, ValidationError
from rich.console import Console

console = Console()

# Determine a user-scoped config directory (XDG-style)
USER_CONFIG_DIR = Path.home() / ".config" / "flaccid"
USER_SETTINGS_FILE = USER_CONFIG_DIR / "settings.toml"
USER_SECRETS_FILE = USER_CONFIG_DIR / ".secrets.toml"

# Initialize Dynaconf to read from settings files and environment variables.
settings_loader = Dynaconf(
    envvar_prefix="FLA",
    # Load order (first wins, later overrides):
    # - Project-local settings (for development)
    # - User-scoped settings (global/default)
    settings_files=[
        "settings.toml",
        ".secrets.toml",
        str(USER_SETTINGS_FILE),
        str(USER_SECRETS_FILE),
    ],
    environments=True,
    load_dotenv=True,
)

class FlaccidSettings(BaseModel):
    """A Pydantic model that defines and validates all application settings."""

    library_path: Path = Field(default_factory=lambda: Path.home() / "Music" / "FLACCID")
    download_path: Path = Field(default_factory=lambda: Path.home() / "Downloads" / "FLACCID")
    db_path: Optional[Path] = None

    # Service API settings
    qobuz_app_id: Optional[str] = None
    qobuz_app_secret: Optional[str] = None
    tidal_client_id: Optional[str] = None

    class Config:
        validate_assignment = True

_settings_instance: Optional[FlaccidSettings] = None

def get_settings() -> FlaccidSettings:
    """Get the application settings as a singleton Pydantic model."""
    global _settings_instance
    if _settings_instance is None:
        try:
            config_dict = settings_loader.as_dict()
            _settings_instance = FlaccidSettings(**config_dict)
        except ValidationError as e:
            console.print(f"[red]Configuration error:[/red]\n{e}")
            raise

        _settings_instance.library_path.mkdir(parents=True, exist_ok=True)
        _settings_instance.download_path.mkdir(parents=True, exist_ok=True)
        if _settings_instance.db_path:
            try:
                _settings_instance.db_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    return _settings_instance

def save_settings(new_settings: FlaccidSettings):
    """Save updated settings back to the user's `settings.toml` file."""
    global _settings_instance
    # Persist globally in the user config directory to avoid CWD confusion
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Update in-memory loader for immediate use
    settings_loader.set("library_path", str(new_settings.library_path))
    settings_loader.set("download_path", str(new_settings.download_path))
    if new_settings.db_path is not None:
        settings_loader.set("db_path", str(new_settings.db_path))

    # Write a minimal TOML
    lines = [
        "[default]",
        f"library_path = \"{new_settings.library_path}\"",
        f"download_path = \"{new_settings.download_path}\"",
    ]
    if new_settings.db_path is not None:
        lines.append(f"db_path = \"{new_settings.db_path}\"")
    USER_SETTINGS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _settings_instance = new_settings

def create_default_settings() -> FlaccidSettings:
    """Create a default settings instance, useful for resets."""
    return FlaccidSettings()

def reset_settings():
    """Reset settings by deleting the settings file and clearing the instance."""
    global _settings_instance
    _settings_instance = None
    settings_file = Path("settings.toml")
    if settings_file.exists():
        settings_file.unlink()
