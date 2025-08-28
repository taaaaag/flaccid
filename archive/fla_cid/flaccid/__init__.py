"""
FLACCID - Modular FLAC music downloader and library manager
"""

__version__ = "0.1.0"
__author__ = "FLACCID Contributors"
__email__ = "maintainer@example.com"
__description__ = "Modular FLAC music downloader and library manager"

# Core exports for easy access
from .core.config import get_settings
from .core.metadata import apply_metadata

__all__ = [
    "__version__",
    "__author__",
    "__email__",
    "__description__",
    "get_settings",
    "apply_metadata",
]
