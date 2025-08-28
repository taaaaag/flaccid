"""
Tidal service plugin for FLACCID.

This plugin implements the full download and metadata retrieval functionality
for the Tidal streaming service. It handles the OAuth 2.0 device authorization
flow, token refreshing, and API calls for track and album data.
"""

import asyncio
from pathlib import Path

import requests
from rich.console import Console

from .base import BasePlugin
from ..core.auth import get_credentials, store_credentials
from ..core.downloader import download_file
from ..core.metadata import apply_metadata

from ..core.api_config import TIDAL_API_URL


def _sanitize(name: str) -> str:
    bad = '<>:"/\\|?\n\r\t'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip().strip(".")


console = Console()


class TidalPlugin(BasePlugin):
    """Implements download and metadata functionality for Tidal."""

    def __init__(self):
        self.client_id = None
        self.access_token = None
        self.refresh_token = None
        self.session = requests.Session()

    async def authenticate(self):
        """
        Authenticates with Tidal, loading stored tokens and refreshing if necessary.
        """
        console.print("Authenticating with Tidal...")
        self.client_id = get_credentials("tidal", "client_id")
        self.access_token = get_credentials("tidal", "access_token")
        self.refresh_token = get_credentials("tidal", "refresh_token")

        if not self.client_id or not self.access_token:
            raise Exception(
                "Tidal credentials not found. Please run `fla config auto-tidal` first."
            )

        self.session.headers.update(
            {
                "User-Agent": "flaccid/0.1.0",
                "Authorization": f"Bearer {self.access_token}",
            }
        )

        try:
            await self._check_auth()
        except (requests.RequestException, requests.HTTPError) as e:
            raise Exception(f"Tidal API check failed: {e}") from e

    async def _check_auth(self):
        """Verifies the current access token by calling the /me endpoint, refreshing if needed."""
        headers = dict(self.session.headers)
        headers["Accept"] = "application/vnd.tidal.v1+json"
        url = f"{TIDAL_API_URL}/v1/me"
        response = self.session.get(url, headers=headers, timeout=10)

        if response.status_code == 401:
            console.print(
                "[yellow]Tidal access token expired. Attempting to refresh...[/yellow]"
            )
            await self._refresh_access_token()
            response = self.session.get(url, headers=headers, timeout=10)

        response.raise_for_status()
        user_data = response.json()
        console.print(
            f"[green]✅ Authenticated as Tidal user: {user_data.get('email')}[/green]"
        )

    async def _refresh_access_token(self):
        """Uses the stored refresh token to obtain a new access token."""
        if not self.refresh_token:
            raise Exception("No refresh token available to renew Tidal session.")
        try:
            response = requests.post(
                "https://auth.tidal.com/v1/oauth2/token",
                data={
                    "client_id": self.client_id,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "r_usr+w_usr+w_sub",
                },
                timeout=10,
            )
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            self.session.headers["Authorization"] = f"Bearer {self.access_token}"
            store_credentials("tidal", "access_token", self.access_token)
            if "refresh_token" in token_data:
                self.refresh_token = token_data["refresh_token"]
                store_credentials("tidal", "refresh_token", self.refresh_token)
            console.print("[green]Successfully refreshed Tidal access token.[/green]")
        except requests.RequestException as e:
            raise Exception(f"Failed to refresh Tidal token: {e}") from e

    async def _get_track_metadata(self, track_id: str) -> dict:
        """Fetches and standardizes metadata for a single Tidal track."""
        url = f"{TIDAL_API_URL}/v1/tracks/{track_id}"
        response = self.session.get(
            url, headers={"Accept": "application/vnd.tidal.v1+json"}
        )
        response.raise_for_status()
        data = response.json()["resource"]
        return {
            "title": data["title"],
            "artist": ", ".join(
                [a["name"] for a in data["artists"] if a["type"] == "MAIN"]
            ),
            "album": data["album"]["title"],
            "albumartist": data["album"]["artist"]["name"],
            "tracknumber": data["trackNumber"],
            "tracktotal": data["album"]["numberOfTracks"],
            "discnumber": data["volumeNumber"],
            "disctotal": data["album"]["numberOfVolumes"],
            "date": data["album"]["releaseDate"],
            "isrc": data.get("isrc"),
            "copyright": data.get("copyright"),
            "cover_url": data["album"]["imageCover"]["large"]["url"],
        }

    async def _get_stream_url(self, track_id: str, quality: str = "LOSSLESS") -> str:
        """Gets the stream URL for a track (quality hint kept for compatibility)."""
        url = f"{TIDAL_API_URL}/v1/tracks/{track_id}/playback-info"
        params = {"audioquality": quality.upper(), "assetpresentation": "FULL"}
        response = self.session.get(
            url, params=params, headers={"Accept": "application/vnd.tidal.v1+json"}
        )
        response.raise_for_status()
        return response.json()["track_streams"][0]["urls"][0]

    async def download_track(self, track_id: str, quality: str, output_dir: Path):
        """Downloads a single track, including metadata and cover art."""
        if not self.access_token:
            await self.authenticate()

        metadata = await self._get_track_metadata(track_id)
        stream_url = await self._get_stream_url(track_id, quality)
        # Try to detect if the stream is MP3 (lossy). Prefer HEAD to inspect
        # content-type; fall back to quality flag.
        try:
            head = requests.head(stream_url, allow_redirects=True, timeout=5)
            content_type = head.headers.get("Content-Type", "").lower()
        except requests.RequestException:
            content_type = ""

        is_mp3 = (
            "mpeg" in content_type or "mp3" in content_type or "mp3" in quality.lower()
        )

        if is_mp3:
            console.print(
                (
                    f"[yellow]Only MP3 stream available for track {track_id}. "
                    "Skipping download (FLAC-only mode)."
                )
            )
            return

        track_no = int(metadata.get("tracknumber") or 0)
        safe_title = _sanitize(metadata["title"])
        ext = ".flac"
        filename = f"{track_no:02d}. {safe_title}{ext}"
        filepath = output_dir / filename

        await download_file(stream_url, filepath)
        apply_metadata(filepath, metadata)
        console.print(f"[green]✅ Downloaded '{metadata['title']}'[/green]")

    async def download_album(self, album_id: str, quality: str, output_dir: Path):
        """Downloads all tracks from a Tidal album concurrently."""
        if not self.access_token:
            await self.authenticate()

        url = f"{TIDAL_API_URL}/v1/albums/{album_id}/tracks"
        response = self.session.get(
            url, headers={"Accept": "application/vnd.tidal.v1+json"}
        )
        response.raise_for_status()
        tracks = response.json()["data"]

        if not tracks:
            raise Exception("No tracks found for this album.")

        first_track_meta = await self._get_track_metadata(tracks[0]["id"])
        album_name = first_track_meta["album"].replace("/", "-").replace("\\", "-")
        artist_name = (
            first_track_meta["albumartist"].replace("/", "-").replace("\\", "-")
        )
        album_dir = output_dir / f"{artist_name} - {album_name}"
        album_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"Downloading {len(tracks)} tracks to [blue]{album_dir}[/blue]")
        tasks = [
            self.download_track(track["id"], quality, album_dir) for track in tracks
        ]
        await asyncio.gather(*tasks)

        console.print("[green]✅ Album download complete![/green]")
