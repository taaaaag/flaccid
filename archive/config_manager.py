"""
Configuration Management for FLAC Tagger
Handles loading, validation, and management of configuration settings
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
import logging


@dataclass
class QobuzConfig:
    """Qobuz API configuration."""
    app_id: Optional[str] = None
    user_auth_token: Optional[str] = None
    enabled: bool = False


@dataclass
class AppleConfig:
    """Apple Music API configuration."""
    media_user_token: Optional[str] = None
    authorization: Optional[str] = None
    enabled: bool = False


@dataclass
class MusicBrainzConfig:
    """MusicBrainz API configuration."""
    user_agent: str = "FLACTagger/1.0"
    enabled: bool = True
    rate_limit: float = 1.0


@dataclass
class DiscogsConfig:
    """Discogs API configuration."""
    user_agent: str = "FLACTagger/1.0"
    token: Optional[str] = None
    enabled: bool = False


@dataclass
class AcousticIDConfig:
    """AcousticID API configuration."""
    api_key: Optional[str] = None
    enabled: bool = False


@dataclass
class TaggerConfig:
    """Main tagger configuration."""
    auto_mode: bool = False
    backup_original: bool = True
    max_concurrent: int = 5
    timeout: int = 30
    confidence_threshold: float = 0.8
    artwork_max_size: int = 3000
    artwork_quality: int = 95


@dataclass
class Config:
    """Complete configuration for FLAC Tagger."""
    qobuz: QobuzConfig = QobuzConfig()
    apple: AppleConfig = AppleConfig()
    musicbrainz: MusicBrainzConfig = MusicBrainzConfig()
    discogs: DiscogsConfig = DiscogsConfig()
    acoustid: AcousticIDConfig = AcousticIDConfig()
    tagger: TaggerConfig = TaggerConfig()


class ConfigManager:
    """Manages configuration loading, saving, and validation."""

    DEFAULT_CONFIG_PATHS = [
        Path.home() / ".config" / "flaccid" / "tagger.json",
        Path.home() / ".flaccid" / "tagger.json",
        Path.cwd() / "tagger.json"
    ]

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._config = Config()

    def load_config(self, config_path: Optional[str] = None) -> Config:
        """Load configuration from file and environment variables."""
        # Start with default config
        config = Config()

        # Load from file if specified or found in default locations
        config_file = None
        if config_path:
            config_file = Path(config_path)
        else:
            for path in self.DEFAULT_CONFIG_PATHS:
                if path.exists():
                    config_file = path
                    break

        if config_file and config_file.exists():
            try:
                with open(config_file) as f:
                    file_config = json.load(f)
                    config = self._merge_config(config, file_config)
                    self.logger.info(f"Loaded configuration from {config_file}")
            except Exception as e:
                self.logger.error(f"Failed to load config from {config_file}: {e}")

        # Override with environment variables
        config = self._load_env_config(config)

        # Validate configuration
        self._validate_config(config)

        self._config = config
        return config

    def _merge_config(self, base_config: Config, file_config: Dict[str, Any]) -> Config:
        """Merge file configuration with base configuration."""
        config_dict = asdict(base_config)

        # Deep merge configuration
        for section, values in file_config.items():
            if section in config_dict and isinstance(values, dict):
                config_dict[section].update(values)
            else:
                config_dict[section] = values

        # Reconstruct config object
        try:
            return Config(
                qobuz=QobuzConfig(**config_dict.get("qobuz", {})),
                apple=AppleConfig(**config_dict.get("apple", {})),
                musicbrainz=MusicBrainzConfig(**config_dict.get("musicbrainz", {})),
                discogs=DiscogsConfig(**config_dict.get("discogs", {})),
                acoustid=AcousticIDConfig(**config_dict.get("acoustid", {})),
                tagger=TaggerConfig(**config_dict.get("tagger", {}))
            )
        except Exception as e:
            self.logger.error(f"Failed to merge configuration: {e}")
            return base_config

    def _load_env_config(self, config: Config) -> Config:
        """Load configuration from environment variables."""
        # Qobuz
        if os.getenv("QOBUZ_APP_ID"):
            config.qobuz.app_id = os.getenv("QOBUZ_APP_ID")
            config.qobuz.enabled = True
        if os.getenv("QOBUZ_USER_AUTH_TOKEN"):
            config.qobuz.user_auth_token = os.getenv("QOBUZ_USER_AUTH_TOKEN")

        # Apple Music
        if os.getenv("APPLE_MEDIA_USER_TOKEN"):
            config.apple.media_user_token = os.getenv("APPLE_MEDIA_USER_TOKEN")
            config.apple.enabled = True
        if os.getenv("APPLE_AUTHORIZATION"):
            config.apple.authorization = os.getenv("APPLE_AUTHORIZATION")

        # MusicBrainz
        if os.getenv("MUSICBRAINZ_USER_AGENT"):
            config.musicbrainz.user_agent = os.getenv("MUSICBRAINZ_USER_AGENT")

        # Discogs
        if os.getenv("DISCOGS_TOKEN"):
            config.discogs.token = os.getenv("DISCOGS_TOKEN")
            config.discogs.enabled = True
        if os.getenv("DISCOGS_USER_AGENT"):
            config.discogs.user_agent = os.getenv("DISCOGS_USER_AGENT")

        # AcousticID
        if os.getenv("ACOUSTID_API_KEY"):
            config.acoustid.api_key = os.getenv("ACOUSTID_API_KEY")
            config.acoustid.enabled = True

        return config

    def _validate_config(self, config: Config) -> None:
        """Validate configuration and log warnings for missing required fields."""
        warnings = []

        # Check Qobuz
        if config.qobuz.enabled and not (config.qobuz.app_id and config.qobuz.user_auth_token):
            warnings.append("Qobuz enabled but missing app_id or user_auth_token")

        # Check Apple Music
        if config.apple.enabled and not (config.apple.media_user_token and config.apple.authorization):
            warnings.append("Apple Music enabled but missing media_user_token or authorization")

        # Check Discogs
        if config.discogs.enabled and not config.discogs.token:
            warnings.append("Discogs enabled but missing token")

        # Check AcousticID
        if config.acoustid.enabled and not config.acoustid.api_key:
            warnings.append("AcousticID enabled but missing api_key")

        # Log warnings
        for warning in warnings:
            self.logger.warning(warning)

        # Check if at least one source is enabled
        enabled_sources = sum([
            config.qobuz.enabled,
            config.apple.enabled,
            config.musicbrainz.enabled,
            config.discogs.enabled,
            config.acoustid.enabled
        ])

        if enabled_sources == 0:
            self.logger.warning("No metadata sources are enabled - only MusicBrainz will be used")

    def save_config(self, config_path: Optional[str] = None) -> None:
        """Save current configuration to file."""
        if config_path:
            path = Path(config_path)
        else:
            path = self.DEFAULT_CONFIG_PATHS[0]

        # Create directory if it doesn't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, 'w') as f:
                json.dump(asdict(self._config), f, indent=2)
            self.logger.info(f"Configuration saved to {path}")
        except Exception as e:
            self.logger.error(f"Failed to save configuration: {e}")

    def get_config(self) -> Config:
        """Get the current configuration."""
        return self._config

    def create_example_config(self, config_path: str) -> None:
        """Create an example configuration file."""
        example_config = {
            "qobuz": {
                "app_id": "YOUR_QOBUZ_APP_ID",
                "user_auth_token": "YOUR_QOBUZ_USER_AUTH_TOKEN",
                "enabled": False
            },
            "apple": {
                "media_user_token": "YOUR_APPLE_MEDIA_USER_TOKEN",
                "authorization": "YOUR_APPLE_AUTHORIZATION",
                "enabled": False
            },
            "musicbrainz": {
                "user_agent": "FLACTagger/1.0 (your-email@example.com)",
                "enabled": True,
                "rate_limit": 1.0
            },
            "discogs": {
                "user_agent": "FLACTagger/1.0",
                "token": "YOUR_DISCOGS_TOKEN",
                "enabled": False
            },
            "acoustid": {
                "api_key": "YOUR_ACOUSTID_API_KEY",
                "enabled": False
            },
            "tagger": {
                "auto_mode": False,
                "backup_original": True,
                "max_concurrent": 5,
                "timeout": 30,
                "confidence_threshold": 0.8,
                "artwork_max_size": 3000,
                "artwork_quality": 95
            }
        }

        Path(config_path).parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(example_config, f, indent=2)

        print(f"Example configuration created at {config_path}")
        print("Please edit the file to add your API credentials.")
