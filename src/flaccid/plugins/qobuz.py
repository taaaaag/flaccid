"""
Qobuz plugin implementation for FLACCID.

Features:
- Async authentication and API calls using aiohttp
- Quality fallback strategy for selecting best available format_id
- Optional MP3 allowance (otherwise MP3 formats are skipped)
- Safe filename/path generation with metadata-driven structure
"""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Tuple

import aiohttp
from rich.console import Console
import logging

from .base import BasePlugin
from ..core.auth import get_credentials
from ..core.config import get_settings
from ..core.downloader import download_file
from ..core.ratelimit import AsyncRateLimiter
from ..core.metadata import apply_metadata

QOBUZ_API_URL = "https://www.qobuz.com/api.json/0.2"
console = Console()
logger = logging.getLogger(__name__)

# Preferred format_id fallback lists for different quality requests
# Qobuz format ids reference: 5=mp3, 6=flac 16-bit, 7/19/27/29=hi-res variants
QUALITY_FALLBACKS = {
    "1": [5],
    "2": [6, 5],
    "3": [19, 7, 6, 5],
    "4": [29, 27, 19, 7, 6, 5],
    "mp3": [5],
    "lossless": [6, 5],
    "hires": [29, 27, 19, 7, 6, 5],
    "max": [29, 27, 19, 7, 6, 5],
}


def _sign_request(secret: str, endpoint: str, **kwargs) -> Tuple[str, str]:
    ts = str(int(time.time()))
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(kwargs.items()))
    base_string = f"{endpoint}{sorted_params}{ts}{secret}"
    signature = hashlib.md5(base_string.encode("utf-8")).hexdigest()
    return ts, signature


def _sanitize(name: str) -> str:
    bad = '<>:"/\\|?*\n\r\t'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip().strip(".")


def _generate_path_from_template(fields: dict, ext: str) -> str:
    album_artist = fields.get("albumartist", "Unknown Artist")
    album = fields.get("album", "Unknown Album")
    date = fields.get("date", "XXXX")
    title = fields.get("title", "Unknown Title")
    track_num = str(fields.get("tracknumber", "0")).zfill(2)
    disc_num = str(fields.get("discnumber", "1"))
    disc_total = int(fields.get("disctotal", 1))

    dir_artist = _sanitize(album_artist)
    year = date[:4] if date and len(date) >= 4 else "XXXX"
    dir_album = _sanitize(f"({year}) {album}")
    disc_part = f"CD{disc_num}/" if disc_total > 1 else ""
    file_name_stem = f"{track_num}. {title}"
    safe_file_name = _sanitize(file_name_stem) + ext
    return f"{dir_artist}/{dir_album}/{disc_part}{safe_file_name}"


class _QobuzApiClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        auth_token: str,
        session: aiohttp.ClientSession,
        limiter: AsyncRateLimiter | None = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.auth_token = auth_token
        self.session = session
        self.limiter = limiter

    async def _request(
        self, endpoint: str, params: dict | None = None, signed: bool = False
    ) -> dict:
        if not self.session:
            raise RuntimeError("API client must be used within an active session.")
        if self.limiter:
            await self.limiter.acquire()
        full_url = f"{QOBUZ_API_URL}{endpoint}"
        request_params = {
            "app_id": self.app_id,
            "user_auth_token": self.auth_token,
            **(params or {}),
        }
        if signed:
            ts, sig = _sign_request(
                self.app_secret, endpoint.strip("/"), **request_params
            )
            request_params["request_ts"] = ts
            request_params["request_sig"] = sig
        async with self.session.get(full_url, params=request_params) as response:
            response.raise_for_status()
            return await response.json()

    async def get_track(self, track_id: str) -> dict:
        return await self._request("/track/get", {"track_id": track_id})

    async def get_album(self, album_id: str) -> dict:
        return await self._request("/album/get", {"album_id": album_id})

    async def get_file_url(self, track_id: str, format_id: int) -> dict:
        return await self._request(
            "/track/getFileUrl",
            {"track_id": track_id, "format_id": format_id, "intent": "stream"},
            signed=True,
        )


class QobuzPlugin(BasePlugin):
    def __init__(self, *, correlation_id: str | None = None, rps: int | None = None):
        self.app_id: str | None = None
        self.app_secret: str | None = None
        self.auth_token: str | None = None
        self.api_client: _QobuzApiClient | None = None
        self.session: aiohttp.ClientSession | None = None
        self.correlation_id: str | None = correlation_id
        self._rps: int | None = rps

    async def authenticate(self):
        console.print("Authenticating with Qobuz...")
        settings = get_settings()
        self.app_id = settings.qobuz_app_id or get_credentials("qobuz", "app_id")
        # Prefer settings, fall back to keyring
        self.app_secret = getattr(
            settings, "qobuz_app_secret", None
        ) or get_credentials("qobuz", "app_secret")
        self.auth_token = get_credentials("qobuz", "user_auth_token")
        if not all([self.app_id, self.app_secret, self.auth_token]):
            raise Exception(
                "Qobuz credentials (app_id, app_secret, user_auth_token) not found. "
                "Please run `fla config auto-qobuz` first."
            )
        logger.debug(
            "qobuz.authenticate ok",
            extra={
                "provider": "qobuz",
                "has_app_id": bool(self.app_id),
                "has_app_secret": bool(self.app_secret),
                "has_token": bool(self.auth_token),
            },
        )

    def _normalize_metadata(self, track_data: dict) -> dict:
        album = track_data.get("album", {})

        def _join_artists(data):
            if not data:
                return None
            return ", ".join([a["name"] for a in data if "name" in a])

        albumartist = _join_artists(album.get("artist"))
        artist = _join_artists(track_data.get("performers")) or albumartist
        fields = {
            "title": track_data.get("title"),
            "artist": artist,
            "album": album.get("title"),
            "albumartist": albumartist,
            "tracknumber": track_data.get("track_number"),
            "tracktotal": album.get("tracks_count"),
            "discnumber": track_data.get("media_number"),
            "disctotal": album.get("media_count"),
            "date": album.get("release_date_original"),
            "year": str(album.get("release_date_original", "0000")[:4]),
            "isrc": track_data.get("isrc"),
            "copyright": track_data.get("copyright"),
            "label": album.get("label", {}).get("name"),
            "genre": album.get("genre", {}).get("name"),
            "upc": album.get("upc"),
            "lyrics": track_data.get("lyrics"),
            "cover_url": album.get("image", {}).get("large"),
        }
        return {k: v for k, v in fields.items() if v is not None}

    async def download_track(
        self,
        track_id: str,
        quality: str,
        output_dir: Path,
        allow_mp3: bool = False,
        verify: bool = False,
    ):
        if not self.api_client:
            raise RuntimeError("Plugin not authenticated or session not started.")
        logger.info(
            "qobuz.download_track.start",
            extra={
                "provider": "qobuz",
                "track_id": track_id,
                "quality": quality,
                "corr": self.correlation_id,
            },
        )
        track_data = await self.api_client.get_track(track_id)
        metadata = self._normalize_metadata(track_data)
        format_id, stream_url = await self._find_stream(track_id, quality, allow_mp3)
        if format_id is None or stream_url is None:
            console.print(
                f"[red]Error for track {track_id}:[/red] No download URL found for any tried format id."
            )
            logger.warning(
                "qobuz.download_track.no_stream",
                extra={
                    "provider": "qobuz",
                    "track_id": track_id,
                    "corr": self.correlation_id,
                },
            )
            return
        if isinstance(format_id, int) and format_id < 6 and not allow_mp3:
            console.print(
                f"[yellow]Selected format {format_id} for track {track_id} is MP3. Skipping download (use --allow-mp3 to permit MP3 fallbacks).[/yellow]"
            )
            logger.info(
                "qobuz.download_track.skip_mp3",
                extra={
                    "provider": "qobuz",
                    "track_id": track_id,
                    "format_id": format_id,
                    "corr": self.correlation_id,
                },
            )
            return
        ext = ".flac"
        relative_path = _generate_path_from_template(metadata, ext)
        filepath = output_dir / relative_path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        await download_file(stream_url, filepath)
        apply_metadata(filepath, metadata)
        if verify:
            try:
                from ..core.verify import verify_media

                info = verify_media(filepath)
                if info is not None:
                    console.print(
                        f"[cyan]Verified:[/cyan] {info.get('codec')} {info.get('sample_rate')}Hz "
                        f"{info.get('channels')}ch, duration {info.get('duration')}s"
                    )
                    codec = (info.get('codec') or '').lower()
                    if filepath.suffix.lower() == '.flac' and codec != 'flac':
                        console.print(
                            f"[yellow]Warning:[/yellow] Unexpected codec '{codec}' for .flac output."
                        )
            except Exception as _e:
                console.print("[yellow]Warning:[/yellow] ffprobe verification failed.")
        console.print(f"[green]\u2705 Downloaded '{metadata['title']}'[/green]")
        logger.info(
            "qobuz.download_track.done",
            extra={
                "provider": "qobuz",
                "track_id": track_id,
                "path": str(filepath),
                "corr": self.correlation_id,
            },
        )

    async def download_album(
        self,
        album_id: str,
        quality: str,
        output_dir: Path,
        allow_mp3: bool = False,
        concurrency: int = 4,
        verify: bool = False,
    ):
        if not self.api_client:
            raise RuntimeError("Plugin not authenticated or session not started.")
        album_data = await self.api_client.get_album(album_id)
        tracks = album_data.get("tracks", {}).get("items", [])
        console.print(
            f"Downloading {len(tracks)} tracks from '{album_data['title']}'..."
        )
        logger.info(
            "qobuz.download_album.start",
            extra={
                "provider": "qobuz",
                "album_id": album_id,
                "tracks": len(tracks),
                "quality": quality,
                "corr": self.correlation_id,
            },
        )
        sem = asyncio.Semaphore(max(1, int(concurrency or 1)))

        async def _wrapped(tid: str):
            async with sem:
                await self.download_track(tid, quality, output_dir, allow_mp3, verify)

        tasks = [_wrapped(str(track["id"])) for track in tracks]
        await asyncio.gather(*tasks)
        console.print("[green]\u2705 Album download complete![/green]")
        logger.info(
            "qobuz.download_album.done",
            extra={
                "provider": "qobuz",
                "album_id": album_id,
                "tracks": len(tracks),
                "corr": self.correlation_id,
            },
        )

    async def _find_stream(
        self, track_id: str, quality: str, allow_mp3: bool = False
    ) -> tuple[int | None, str | None]:
        if not self.api_client:
            raise RuntimeError("Plugin not authenticated or session not started.")
        key = (str(quality) if quality is not None else "").lower()
        try:
            if key.isdigit() and int(key) >= 4:
                key = "max"
        except Exception:
            pass
        tried = QUALITY_FALLBACKS.get(key, QUALITY_FALLBACKS.get("max"))
        logger.debug(
            "Qobuz: trying format ids %s for track %s (quality=%s, allow_mp3=%s)",
            tried,
            track_id,
            quality,
            allow_mp3,
        )
        for fmt in tried:
            if isinstance(fmt, int) and fmt < 6 and not allow_mp3:
                logger.debug(
                    "Qobuz: skipping MP3 format_id=%s for track=%s (FLAC-only mode)",
                    fmt,
                    track_id,
                )
                console.print(
                    f"[yellow]Qobuz: skipping MP3 format_id={fmt} for track {track_id} (use --allow-mp3 to permit MP3)[/yellow]"
                )
                continue
            console.print(f"Qobuz: trying format_id={fmt} for track {track_id}...")
            logger.debug("Qobuz: trying format_id=%s for track=%s", fmt, track_id)
            try:
                stream_data = await self.api_client.get_file_url(track_id, fmt)
                url = (stream_data or {}).get("url")
                if url:
                    logger.debug("Qobuz: format_id=%s yielded URL %s", fmt, url)
                    console.print(
                        f"[green]Qobuz: selected format_id={fmt} for track {track_id}[/green]"
                    )
                    return fmt, url
                else:
                    logger.debug(
                        "Qobuz: format_id=%s returned no URL", fmt
                    )
            except Exception as exc:
                logger.debug("Qobuz: format_id=%s failed with exception: %s", fmt, exc)
                console.print(f"Qobuz: format_id={fmt} failed: {exc}")
                logger.debug(
                    "qobuz.find_stream.try_fail",
                    extra={
                        "provider": "qobuz",
                        "track_id": track_id,
                        "format_id": fmt,
                    },
                )
                continue
        logger.debug(
            "Qobuz: no stream URL found for track %s with tried formats %s",
            track_id,
            tried,
        )
        console.print(
            f"[yellow]Qobuz: no stream URL found for track {track_id}[/yellow]"
        )
        return None, None

    async def __aenter__(self):
        await self.authenticate()
        self.session = aiohttp.ClientSession()
        # Default: 8 requests/second unless overridden via env
        import os

        rps = (
            self._rps
            if self._rps is not None
            else int(os.getenv("FLA_QOBUZ_RPS", "8") or "8")
        )
        self._limiter = AsyncRateLimiter(rps, 1.0)
        self.api_client = _QobuzApiClient(
            self.app_id, self.app_secret, self.auth_token, self.session, self._limiter
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            self.session = None
        self.api_client = None
