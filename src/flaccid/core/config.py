"""
Configuration management using Dynaconf and Pydantic.

This module provides a robust, layered configuration system. It uses Dynaconf
to load settings from files (e.g., `settings.toml`, `.secrets.toml`) and
environment variables. Pydantic is then used to validate the loaded data and
provide a typed `FlaccidSettings` object.

The `get_settings` function provides a singleton instance of the settings,
ensuring consistent configuration throughout the application.
"""

import os
from pathlib import Path
from typing import Optional

import toml
from dynaconf import Dynaconf
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rich.console import Console

console = Console()

# Determine a user-scoped config directory (XDG-style)
USER_CONFIG_DIR = Path.home() / ".config" / "flaccid"
USER_SETTINGS_FILE = USER_CONFIG_DIR / "settings.toml"
USER_SECRETS_FILE = USER_CONFIG_DIR / ".secrets.toml"

# Project-local settings (CWD) to support isolated runs and tests
LOCAL_SETTINGS_FILE = Path("settings.toml")
LOCAL_SECRETS_FILE = Path(".secrets.toml")

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


# Defaults
DEFAULT_QOBUZ_APP_ID = "798273057"


class FlaccidSettings(BaseModel):
    """A Pydantic model that defines and validates all application settings."""

    library_path: Path = Field(default_factory=lambda: Path.home() / "Music" / "FLACCID")
    download_path: Path = Field(default_factory=lambda: Path.home() / "Downloads" / "FLACCID")
    db_path: Optional[Path] = None

    # Service API settings
    # Hardcode a sensible default App ID to reduce setup friction
    qobuz_app_id: Optional[str] = Field(default=DEFAULT_QOBUZ_APP_ID)
    qobuz_app_secret: Optional[str] = None
    qobuz_secrets: Optional[list[str]] = None
    tidal_client_id: Optional[str] = None

    # Pydantic v2 configuration
    model_config = ConfigDict(validate_assignment=True)


def get_default_db_dir() -> Path:
    """Return a user-scoped default directory for DB storage (not currently used)."""
    try:
        from platformdirs import user_data_dir

        return Path(user_data_dir("flaccid"))
    except Exception:
        return Path.home() / ".local" / "share" / "flaccid"


_settings_instance: Optional[FlaccidSettings] = None


def get_settings() -> FlaccidSettings:
    """Get the application settings as a singleton Pydantic model."""
    global _settings_instance
    if _settings_instance is None:
        try:
            config_dict = settings_loader.as_dict() or {}

            # If a project-local settings file exists, load and overlay explicitly
            if LOCAL_SETTINGS_FILE.exists():
                try:
                    local_data = toml.loads(LOCAL_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
                    if isinstance(local_data, dict):
                        config_dict.update(local_data)
                except Exception:
                    # Ignore malformed local settings; fall back to other layers
                    pass

            # Explicit environment overrides for robustness
            env_lib = os.getenv("FLA_LIBRARY_PATH")
            env_dl = os.getenv("FLA_DOWNLOAD_PATH")
            env_db = os.getenv("FLA_DB_PATH")
            if env_lib:
                config_dict["library_path"] = env_lib
            if env_dl:
                config_dict["download_path"] = env_dl
            if env_db:
                config_dict["db_path"] = env_db

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
    """Save updated settings to the project-local `settings.toml` file."""
    global _settings_instance
    # Update in-memory loader for immediate use
    settings_loader.set("library_path", str(new_settings.library_path))
    settings_loader.set("download_path", str(new_settings.download_path))
    if new_settings.db_path is not None:
        settings_loader.set("db_path", str(new_settings.db_path))

    # Persist locally to support isolated filesystem scenarios
    data = {
        "library_path": str(new_settings.library_path),
        "download_path": str(new_settings.download_path),
    }
    if new_settings.db_path is not None:
        data["db_path"] = str(new_settings.db_path)

    LOCAL_SETTINGS_FILE.write_text(toml.dumps(data), encoding="utf-8")

    _settings_instance = new_settings


def create_default_settings() -> FlaccidSettings:
    """Create a default settings instance, useful for resets."""
    return FlaccidSettings()


def reset_settings():
    """Reset in-memory settings (do not delete on-disk settings)."""
    global _settings_instance
    _settings_instance = None
