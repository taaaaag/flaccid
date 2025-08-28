"""
Discogs API Integration Module
Handles metadata retrieval from Discogs database
"""

import asyncio
import aiohttp
import time
from typing import Dict, Optional, Any


class DiscogsAPI:
    """Discogs API client for metadata retrieval."""

    BASE_URL = "https://api.discogs.com"

    def __init__(self, user_agent: str, token: Optional[str] = None):
        self.user_agent = user_agent
        self.token = token
        self.session = None
        self.rate_limit_delay = 1.0  # Discogs rate limiting

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search_releases(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search for releases on Discogs."""
        if not self.session:
            raise RuntimeError("DiscogsAPI must be used as async context manager")

        headers = {
            "User-Agent": self.user_agent
        }

        if self.token:
            headers["Authorization"] = f"Discogs token={self.token}"

        params = {
            "q": query,
            "type": "release",
            "per_page": limit
        }

        url = f"{self.BASE_URL}/database/search"

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
        finally:
            await asyncio.sleep(self.rate_limit_delay)

    def normalize_metadata(self, release_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Discogs release data to standard metadata format."""
        try:
            results = release_data.get("results", [])
            if not results:
                return {}

            release = results[0]

            metadata = {
                "ALBUM": release.get("title"),
                "ARTIST": ", ".join(release.get("artist", [])),
                "LABEL": ", ".join(release.get("label", [])),
                "YEAR": str(release.get("year", "")),
                "GENRE": ", ".join(release.get("genre", [])),
                "STYLE": ", ".join(release.get("style", [])),
                "COUNTRY": release.get("country"),
                "DISCOGS_RELEASE_ID": str(release.get("id", "")),
                "CATALOGNUMBER": release.get("catno"),
                "FORMAT": ", ".join(release.get("format", []))
            }

            # Clean up empty values
            return {k: v for k, v in metadata.items() if v and v != ""}

        except Exception as e:
            raise ValueError(f"Failed to normalize Discogs metadata: {e}")
