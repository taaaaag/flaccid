"""
Apple Music service plugin for FLACCID (Placeholder).

This plugin is intended to provide metadata lookup from the Apple Music API.
It does not currently implement any download functionality, as Apple Music does
not offer a legitimate way to download FLAC files.

Its primary purpose will be for the `fla tag apple` command to tag local files
by searching for matching album metadata on Apple Music.
"""
from .base import BasePlugin


class ApplePlugin(BasePlugin):
    """Implements metadata search for Apple Music."""

    async def authenticate(self):
        """Authentication for Apple Music.

        This would likely involve setting up an API key from Apple.
        """
        # This method is required by the BasePlugin, but may not be needed
        # for public metadata searching.
        pass

    def search_album(self, query: str) -> dict | None:
        """(Future) Search for an album on Apple Music by a query string."""
        # TODO: Implement Apple Music API search call
        return None

    def get_album_metadata(self, album_id: str) -> dict | None:
        """(Future) Get detailed album metadata by its Apple Music ID."""
        # TODO: Implement Apple Music API album lookup call
        return None
