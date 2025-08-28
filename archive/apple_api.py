"""
Apple Music API Integration Module
Handles SPC/CKC authentication and metadata retrieval
"""

import asyncio
import aiohttp
import base64
import time
from typing import Dict, Optional, Any


class AppleMusicAPI:
    """Apple Music API client for metadata retrieval."""

    BASE_URL = "https://amp-api.music.apple.com/v1"

    def __init__(self, media_user_token: str, authorization: str):
        self.media_user_token = media_user_token
        self.authorization = authorization
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search_track(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search for tracks on Apple Music."""
        if not self.session:
            raise RuntimeError("AppleMusicAPI must be used as async context manager")

        headers = {
            "Authorization": self.authorization,
            "Media-User-Token": self.media_user_token,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }

        params = {
            "term": query,
            "types": "songs",
            "limit": limit
        }

        url = f"{self.BASE_URL}/catalog/us/search"

        try:
            start_time = time.time()
            async with self.session.get(url, headers=headers, params=params) as response:
                response_time = time.time() - start_time

                if response.status == 200:
                    data = await response.json()
                    return {
                        "success": True,
                        "data": data,
                        "response_time": response_time
                    }
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status}",
                        "response_time": response_time
                    }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "response_time": time.time() - start_time
            }

    def normalize_metadata(self, track_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Apple Music track data to standard metadata format."""
        try:
            songs = track_data.get("results", {}).get("songs", {}).get("data", [])
            if not songs:
                return {}

            track = songs[0]
            attributes = track.get("attributes", {})

            metadata = {
                "TITLE": attributes.get("name"),
                "ARTIST": attributes.get("artistName"),
                "ALBUM": attributes.get("albumName"),
                "ALBUMARTIST": attributes.get("albumName"),  # Often same as artist
                "TRACKNUMBER": str(attributes.get("trackNumber", "")),
                "DISCNUMBER": str(attributes.get("discNumber", "")),
                "DATE": attributes.get("releaseDate"),
                "YEAR": attributes.get("releaseDate", "")[:4] if attributes.get("releaseDate") else "",
                "GENRE": ", ".join(attributes.get("genreNames", [])),
                "DURATION": str(int(attributes.get("durationInMillis", 0) / 1000)),
                "ITUNES_TRACK_ID": track.get("id"),
                "ISRC": attributes.get("isrc"),
                "COPYRIGHT": attributes.get("copyright"),
                "COMPOSER": attributes.get("composerName"),
                "LANGUAGE": attributes.get("contentRating")  # Approximation
            }

            # Add artwork URL
            artwork = attributes.get("artwork")
            if artwork:
                artwork_url = artwork.get("url", "").replace("{w}", "3000").replace("{h}", "3000")
                metadata["ARTWORK_URL"] = artwork_url

            # Add lyrics URL if available
            if attributes.get("hasLyrics"):
                metadata["LYRICS_AVAILABLE"] = "true"

            # Clean up empty values
            return {k: v for k, v in metadata.items() if v and v != ""}

        except Exception as e:
            raise ValueError(f"Failed to normalize Apple Music metadata: {e}")
