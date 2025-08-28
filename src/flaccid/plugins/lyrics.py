"""
Lyrics service plugin for FLACCID (Placeholder).

This plugin is intended to provide a generic interface for fetching song lyrics
from various online sources (e.g., Genius, Musixmatch, etc.).

It could be used as a post-download hook to automatically add lyrics tags
to downloaded files.
"""

from .base import BasePlugin


class LyricsPlugin(BasePlugin):
    """A placeholder for a future lyrics fetching implementation."""

    async def authenticate(self):
        """Authentication for the chosen lyrics service.

        This might not be necessary for all lyrics providers.
        """
        pass

    def get_lyrics(self, artist: str, title: str) -> str | None:
        """(Future) Fetch lyrics for a given artist and track title."""
        # TODO: Implement a lyrics fetching service
        return None
