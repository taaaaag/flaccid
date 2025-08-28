"""
Base Plugin Class for Flaccid Integration
Defines the interface for all flaccid plugins
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
import argparse


class BasePlugin(ABC):
    """Base class for all flaccid plugins."""

    name: str = ""
    description: str = ""
    version: str = "1.0.0"

    @abstractmethod
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add command-line arguments specific to this plugin."""
        pass

    @abstractmethod
    async def execute(self, args: argparse.Namespace) -> Any:
        """Execute the plugin with the given arguments."""
        pass

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate plugin configuration."""
        return True

    def get_help(self) -> str:
        """Get detailed help text for this plugin."""
        return f"{self.name}: {self.description}"


class PluginRegistry:
    """Registry for managing flaccid plugins."""

    def __init__(self):
        self._plugins = {}

    def register(self, plugin: BasePlugin) -> None:
        """Register a plugin."""
        if not plugin.name:
            raise ValueError("Plugin must have a name")

        self._plugins[plugin.name] = plugin

    def get_plugin(self, name: str) -> BasePlugin:
        """Get a plugin by name."""
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' not found")

        return self._plugins[name]

    def list_plugins(self) -> Dict[str, BasePlugin]:
        """List all registered plugins."""
        return self._plugins.copy()

    def has_plugin(self, name: str) -> bool:
        """Check if a plugin is registered."""
        return name in self._plugins


# Global plugin registry
registry = PluginRegistry()
