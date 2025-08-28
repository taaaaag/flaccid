"""
Defines the abstract base class for all service plugins.

This module provides the `BasePlugin` ABC (Abstract Base Class), which establishes
a common interface that all service plugins (like Qobuz, Tidal, etc.) must
adhere to. This ensures that the core application can interact with any plugin
in a consistent way.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class BasePlugin(ABC):
    """An abstract base class that all service plugins must inherit from."""

    @abstractmethod
    async def authenticate(self):
        """
        Authenticate with the service.

        This method should handle loading credentials, checking their validity,
        and refreshing them if necessary.
        """
        pass
