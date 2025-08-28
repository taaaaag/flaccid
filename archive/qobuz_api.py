"""
Qobuz API Integration Module
Handles authentication and metadata retrieval from Qobuz
"""

import asyncio
import aiohttp
import time
from typing import Dict, Optional, Any
from urllib.parse import urlencode


class QobuzAPI:
    """Qobuz API client for metadata retrieval."""

    BASE_URL = "https://www.qobuz.com/api.json/0.2"

    def __init__(self, app_id: str, user_auth_token: str):
        self.app_id = app_id
        self.user_auth_token = user_auth_token
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search_track(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search for tracks on Qobuz."""
        if not self.session:
            raise RuntimeError("QobuzAPI must be used as async context manager")

        params = {
            "app_id": self.app_id,
            "user_auth_token": self.user_auth_token,
            "query": query,
            "type": "tracks",
            "limit": limit
        }

        url = f"{self.BASE_URL}/catalog/search"

        try:
            start_time = time.time()
            async with self.session.get(url, params=params) as response:
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
        """Normalize Qobuz track data to standard metadata format."""
        try:
            track = track_data.get("tracks", {}).get("items", [{}])[0]
            album = track.get("album", {})

            metadata = {
                "TITLE": track.get("title"),
                "ARTIST": ", ".join([artist.get("name", "") for artist in track.get("performers", [])]),
                "ALBUM": album.get("title"),
                "ALBUMARTIST": album.get("artist", {}).get("name"),
                "TRACKNUMBER": str(track.get("track_number", "")),
                "DISCNUMBER": str(track.get("media_number", "")),
                "DATE": album.get("release_date_original"),
                "YEAR": album.get("release_date_original", "")[:4] if album.get("release_date_original") else "",
                "LABEL": album.get("label", {}).get("name"),
                "GENRE": ", ".join(track.get("genres", [])),
                "DURATION": str(track.get("duration", "")),
                "QOBUZ_TRACK_ID": str(track.get("id", "")),
                "ISRC": track.get("isrc"),
                "UPC": album.get("upc"),
                "COPYRIGHT": track.get("copyright"),
                "COMPOSER": ", ".join([composer.get("name", "") for composer in track.get("composers", [])]),
                "CATALOGNUMBER": album.get("catalog_number")
            }

            # Add artwork URL
            if album.get("image", {}).get("large"):
                metadata["ARTWORK_URL"] = album["image"]["large"]

            # Clean up empty values
            return {k: v for k, v in metadata.items() if v and v != ""}

        except Exception as e:
            raise ValueError(f"Failed to normalize Qobuz metadata: {e}")
