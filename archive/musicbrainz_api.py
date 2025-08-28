"""
MusicBrainz API Integration Module
Handles metadata retrieval from MusicBrainz database
"""

import asyncio
import aiohttp
import time
from typing import Dict, Optional, Any
from urllib.parse import urlencode


class MusicBrainzAPI:
    """MusicBrainz API client for metadata retrieval."""

    BASE_URL = "https://musicbrainz.org/ws/2"

    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.session = None
        self.rate_limit_delay = 1.0  # MusicBrainz rate limiting

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search_recording(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search for recordings on MusicBrainz."""
        if not self.session:
            raise RuntimeError("MusicBrainzAPI must be used as async context manager")

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json"
        }

        params = {
            "query": query,
            "fmt": "json",
            "limit": limit
        }

        url = f"{self.BASE_URL}/recording"

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
            # Respect rate limiting
            await asyncio.sleep(self.rate_limit_delay)

    async def get_recording_details(self, recording_id: str) -> Dict[str, Any]:
        """Get detailed recording information by ID."""
        if not self.session:
            raise RuntimeError("MusicBrainzAPI must be used as async context manager")

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json"
        }

        params = {
            "fmt": "json",
            "inc": "releases+artist-credits+genres+isrcs+recordings"
        }

        url = f"{self.BASE_URL}/recording/{recording_id}"

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

    def normalize_metadata(self, recording_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize MusicBrainz recording data to standard metadata format."""
        try:
            recordings = recording_data.get("recordings", [])
            if not recordings:
                return {}

            recording = recordings[0]

            # Get primary release
            releases = recording.get("releases", [])
            primary_release = releases[0] if releases else {}

            # Get artist credits
            artist_credits = recording.get("artist-credit", [])
            artists = [credit.get("artist", {}).get("name", "") for credit in artist_credits]

            metadata = {
                "TITLE": recording.get("title"),
                "ARTIST": ", ".join(artists),
                "ALBUM": primary_release.get("title"),
                "DATE": primary_release.get("date"),
                "YEAR": primary_release.get("date", "")[:4] if primary_release.get("date") else "",
                "MUSICBRAINZ_TRACKID": recording.get("id"),
                "MUSICBRAINZ_ALBUMID": primary_release.get("id"),
                "DURATION": str(int(recording.get("length", 0) / 1000)) if recording.get("length") else "",
                "COUNTRY": primary_release.get("country"),
                "RELEASETYPE": primary_release.get("release-group", {}).get("primary-type")
            }

            # Add ISRCs
            isrcs = recording.get("isrcs", [])
            if isrcs:
                metadata["ISRC"] = isrcs[0]

            # Add genres
            genres = [genre.get("name") for genre in recording.get("genres", [])]
            if genres:
                metadata["GENRE"] = ", ".join(genres)

            # Add artist MBID
            if artist_credits:
                metadata["MUSICBRAINZ_ARTISTID"] = artist_credits[0].get("artist", {}).get("id")

            # Clean up empty values
            return {k: v for k, v in metadata.items() if v and v != ""}

        except Exception as e:
            raise ValueError(f"Failed to normalize MusicBrainz metadata: {e}")
