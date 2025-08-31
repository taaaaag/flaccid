"""
Tidal service plugin for FLACCID.

This plugin implements the full download and metadata retrieval functionality
for the Tidal streaming service. It handles the OAuth 2.0 device authorization
flow, token refreshing, and API calls for track and album data.
"""

import logging
import shutil
import subprocess
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from rich.console import Console

from ..core.api_config import TIDAL_API_ALT_URL, TIDAL_API_FALLBACK_URL, TIDAL_API_URL
from ..core.auth import get_credentials, store_credentials
from ..core.downloader import download_file
from ..core.metadata import apply_metadata
from .base import BasePlugin
from ..core.ratelimit import AsyncRateLimiter

logger = logging.getLogger(__name__)


def _sanitize(name: str) -> str:
    bad = '<>:"/\\|?\n\r\t'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip().strip(".")


console = Console()


class TidalPlugin(BasePlugin):
    """Implements download and metadata functionality for Tidal."""

    def __init__(self, *, correlation_id: str | None = None, rps: int | None = None):
        self.client_id = None
        self.access_token = None
        self.refresh_token = None
        self.session = requests.Session()
        self.correlation_id = correlation_id
        self._rps = rps
        _rps = (
            self._rps
            if self._rps is not None
            else int(os.getenv("FLA_TIDAL_RPS", "5") or "5")
        )
        self._limiter = AsyncRateLimiter(_rps, 1.0)
        self.country_code = os.getenv("FLA_TIDAL_COUNTRY", "US")

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
        """Verifies access token via /v1/me; gracefully handles OpenAPI 404.

        Some regions/accounts see 404 from openapi.tidal.com for /v1/me even
        with a valid token. Treat 404 as a non-fatal OpenAPI unavailability and
        proceed, since subsequent resource calls already implement host
        fallbacks. Only 401 should trigger a refresh or failure.
        """
        headers = dict(self.session.headers)
        headers["Accept"] = "application/vnd.tidal.v1+json"
        url = f"{TIDAL_API_URL}/v1/me"
        await self._limiter.acquire()
        response = self.session.get(url, headers=headers, timeout=10)

        if response.status_code == 401:
            console.print(
                "[yellow]Tidal access token expired. Attempting to refresh...[/yellow]"
            )
            await self._refresh_access_token()
            response = self.session.get(url, headers=headers, timeout=10)

        if response.status_code == 404:
            # OpenAPI path not available. Consider auth OK and continue.
            logger.debug(
                "tidal.authenticate openapi /me 404; proceeding with fallback hosts",
                extra={"provider": "tidal", "corr": self.correlation_id},
            )
            return

        response.raise_for_status()
        user_data = response.json()
        console.print(
            f"[green]✅ Authenticated as Tidal user: {user_data.get('email')}[/green]"
        )
        logger.debug(
            "tidal.authenticate ok",
            extra={
                "provider": "tidal",
                "has_access": bool(self.access_token),
                "corr": self.correlation_id,
            },
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
        base_hosts = [TIDAL_API_URL, TIDAL_API_FALLBACK_URL]
        data = None
        for base in base_hosts:
            try:
                url = f"{base}/v1/tracks/{track_id}"
                await self._limiter.acquire()
                resp = self.session.get(
                    url,
                    params={"countryCode": self.country_code},
                    headers={"Accept": "application/vnd.tidal.v1+json"},
                )
                if resp.status_code == 404 and base != TIDAL_API_FALLBACK_URL:
                    continue
                resp.raise_for_status()
                j = resp.json()
                data = j.get("resource") if isinstance(j, dict) else None
                if data is None and isinstance(j, dict):
                    data = j
                if data:
                    break
            except Exception:
                continue
        if not data:
            raise Exception("Failed to fetch Tidal track metadata")
        # Normalize artist(s)
        artists = data.get("artists") or []
        main_names = [a.get("name") for a in artists if (a or {}).get("type") == "MAIN"]
        if not main_names:
            main_names = [a.get("name") for a in artists if a.get("name")]
        artist_name = ", ".join([n for n in main_names if n]) or data.get(
            "artist", {}
        ).get("name")

        # Normalize album and album artist
        album_info = data.get("album") or {}
        album_title = album_info.get("title") or data.get("albumTitle")
        album_artist = (
            (album_info.get("artist") or {}).get("name")
            or (data.get("albumArtist") or {}).get("name")
            or artist_name
        )

        # Track/disc numbers and totals
        track_no = data.get("trackNumber") or data.get("track_number")
        disc_no = data.get("volumeNumber") or data.get("discNumber")
        track_total = album_info.get("numberOfTracks") or album_info.get(
            "numberOfTracksOnMedia"
        )
        disc_total = album_info.get("numberOfVolumes") or album_info.get(
            "numberOfMedia"
        )

        # Dates
        release_date = album_info.get("releaseDate") or data.get("streamStartDate")

        # Cover URL: handle OpenAPI imageCover and legacy cover string
        cover_url = None
        image_cover = (
            (album_info.get("imageCover") or {}) if isinstance(album_info, dict) else {}
        )
        if isinstance(image_cover, dict):
            large = image_cover.get("large") or {}
            cover_url = large.get("url") or image_cover.get("url")
        if not cover_url:
            cover_id = album_info.get("cover") or data.get("cover")
            if cover_id and isinstance(cover_id, str):
                # Convert dashed/hyphenated id into path segments
                # e.g., 0b6898bf-a492-4ac7-8158-465bae8943fb -> 0b6898bf/a492/4ac7/8158/465bae8943fb
                pathish = cover_id.replace("-", "/")
                cover_url = (
                    f"https://resources.tidal.com/images/{pathish}/1280x1280.jpg"
                )

        return {
            "title": data.get("title"),
            "artist": artist_name,
            "album": album_title,
            "albumartist": album_artist,
            "tracknumber": track_no,
            "tracktotal": track_total,
            "discnumber": disc_no,
            "disctotal": disc_total,
            "date": release_date,
            "isrc": data.get("isrc"),
            "copyright": data.get("copyright"),
            "cover_url": cover_url,
        }

    async def search_track_by_isrc(self, isrc: str) -> dict | None:
        """Search Tidal for a track by ISRC and return normalized metadata.

        Tries common hosts and shapes. Returns None if not found.
        """
        hosts = [TIDAL_API_URL, TIDAL_API_ALT_URL, TIDAL_API_FALLBACK_URL]
        params_variants = [
            {
                "query": isrc,
                "types": "TRACKS",
                "limit": 1,
                "countryCode": self.country_code,
            },
            {"query": isrc, "types": "TRACKS", "limit": 1},
        ]
        headers = {"Accept": "application/vnd.tidal.v1+json"}
        for base in hosts:
            for params in params_variants:
                try:
                    await self._limiter.acquire()
                    resp = self.session.get(
                        f"{base}/v1/search", params=params, headers=headers, timeout=10
                    )
                    if resp.status_code == 404 and base != TIDAL_API_FALLBACK_URL:
                        continue
                    resp.raise_for_status()
                    j = resp.json() or {}
                    # Try common shapes
                    items = None
                    if isinstance(j, dict):
                        tracks_obj = j.get("tracks") or j.get("items") or j.get("data")
                        if isinstance(tracks_obj, dict):
                            items = tracks_obj.get("items")
                        elif isinstance(tracks_obj, list):
                            items = tracks_obj
                    if not items:
                        continue
                    first = items[0]
                    tid = None
                    if isinstance(first, dict):
                        tid = first.get("id") or (first.get("resource") or {}).get("id")
                    if tid:
                        return await self._get_track_metadata(str(tid))
                except Exception:
                    continue
        return None

    def _map_quality(self, quality: str) -> str:
        q = (quality or "").strip().lower()
        if q in {"hires", "hi-res", "hi_res", "hifi", "master"}:
            # Prefer explicit lossless hi-res naming used by clients
            return "HI_RES_LOSSLESS"
        if q in {"lossless", "flac"}:
            return "LOSSLESS"
        if q in {"mp3", "high", "320", "aac"}:
            return "HIGH"
        if q in {"low", "96"}:
            return "LOW"
        return (quality or "").upper()

    async def _get_stream_url(self, track_id: str, quality: str = "LOSSLESS") -> str:
        """Gets the stream URL for a track (quality hint kept for compatibility)."""
        q = self._map_quality(quality)
        paths = [
            f"/v1/tracks/{track_id}/playbackinfo",  # widely used by clients
            f"/v1/tracks/{track_id}/playbackinfopostpaywall",
            f"/v1/tracks/{track_id}/playback-info",
        ]
        # Try both common param casings across hosts
        param_variants = [
            # With explicit country
            {
                "audioquality": q,
                "assetpresentation": "FULL",
                "playbackmode": "STREAM",
                "countryCode": self.country_code,
            },
            {
                "audioQuality": q,
                "assetPresentation": "FULL",
                "playbackmode": "STREAM",
                "countryCode": self.country_code,
            },
            {
                "audioQuality": q,
                "assetPresentation": "FULL",
                "playbackMode": "STREAM",
                "countryCode": self.country_code,
            },
            # Without country (matches tiddl behavior for playback)
            {"audioquality": q, "assetpresentation": "FULL", "playbackmode": "STREAM"},
            {"audioQuality": q, "assetPresentation": "FULL", "playbackmode": "STREAM"},
            {"audioQuality": q, "assetPresentation": "FULL", "playbackMode": "STREAM"},
        ]
        # Prefer api.tidal.com first for playback
        for base in [TIDAL_API_ALT_URL, TIDAL_API_FALLBACK_URL, TIDAL_API_URL]:
            for path in paths:
                for params in param_variants:
                    try:
                        url = f"{base}{path}"
                        await self._limiter.acquire()
                        logger.debug(
                            "tidal.playbackinfo.try",
                            extra={
                                "provider": "tidal",
                                "url": url,
                                "params": params,
                                "corr": self.correlation_id,
                            },
                        )
                        # Accept header: json for legacy hosts
                        accept = (
                            "application/json"
                            if base in (TIDAL_API_ALT_URL, TIDAL_API_FALLBACK_URL)
                            else "application/vnd.tidal.v1+json"
                        )
                        response = self.session.get(
                            url,
                            params=params,
                            headers={"Accept": accept},
                        )
                        if response.status_code == 404:
                            continue
                        response.raise_for_status()
                        j = response.json()
                        if isinstance(j, dict):
                            # Legacy shape
                            if "track_streams" in j:
                                urls = (j.get("track_streams") or [{}])[0].get(
                                    "urls"
                                ) or []
                                if urls:
                                    return urls[0]
                            if (
                                "urls" in j
                                and isinstance(j["urls"], list)
                                and j["urls"]
                            ):
                                return j["urls"][0]
                            # Newer shape with base64 manifest
                            manifest_b64 = j.get("manifest")
                            if manifest_b64:
                                import base64
                                import json as _json

                                try:
                                    decoded = base64.b64decode(manifest_b64).decode(
                                        "utf-8", "ignore"
                                    )
                                    mj = _json.loads(decoded)
                                    logger.debug(
                                        "tidal.playbackinfo.manifest",
                                        extra={
                                            "provider": "tidal",
                                            "mime": j.get("mimeType")
                                            or (
                                                mj.get("mimeType")
                                                if isinstance(mj, dict)
                                                else None
                                            ),
                                            "corr": self.correlation_id,
                                        },
                                    )
                                    urls = (
                                        (mj.get("urls") or [])
                                        if isinstance(mj, dict)
                                        else []
                                    )
                                    if not urls and isinstance(mj, dict):
                                        urls = mj.get("streamingUrls") or []
                                    if urls:
                                        return urls[0]
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.debug(
                            "tidal.playbackinfo.error",
                            extra={
                                "provider": "tidal",
                                "url": url,
                                "error": str(e),
                                "corr": self.correlation_id,
                            },
                        )
                        continue
        logger.warning(
            "tidal.playbackinfo.no_url",
            extra={
                "provider": "tidal",
                "track_id": track_id,
                "corr": self.correlation_id,
            },
        )
        raise Exception("No playback URL found for track")

    async def fetch_artist_top_tracks(
        self, artist_id: str, limit: int = 50
    ) -> list[str]:
        """Return a list of track IDs for an artist's top tracks."""
        hosts = [TIDAL_API_URL, TIDAL_API_ALT_URL, TIDAL_API_FALLBACK_URL]
        params_variants = [
            {"countryCode": self.country_code, "limit": limit},
            {"limit": limit},
        ]
        for base in hosts:
            for params in params_variants:
                try:
                    await self._limiter.acquire()
                    resp = self.session.get(
                        f"{base}/v1/artists/{artist_id}/toptracks",
                        params=params,
                        headers={"Accept": "application/vnd.tidal.v1+json"},
                        timeout=10,
                    )
                    if resp.status_code == 404 and base != TIDAL_API_FALLBACK_URL:
                        continue
                    resp.raise_for_status()
                    j = resp.json() or {}
                    items = None
                    if isinstance(j, dict):
                        items = j.get("items") or j.get("data")
                    if isinstance(items, list) and items:
                        ids: list[str] = []
                        for it in items:
                            try:
                                tid = it.get("id") or (it.get("resource") or {}).get(
                                    "id"
                                )
                                if tid:
                                    ids.append(str(tid))
                            except Exception:
                                continue
                        if ids:
                            return ids
                except Exception:
                    continue
        return []

    async def download_artist_top_tracks(
        self,
        artist_id: str,
        quality: str,
        output_dir: Path,
        *,
        limit: int = 50,
        verify: bool = False,
        concurrency: int = 4,
    ) -> int:
        """Download an artist's top tracks into a folder."""
        if not self.access_token:
            await self.authenticate()
        ids = await self.fetch_artist_top_tracks(artist_id, limit)
        if not ids:
            console.print("[yellow]No top tracks found for this artist.[/yellow]")
            return 0
        # Try fetch artist name for folder
        artist_name = f"Artist {artist_id}"
        try:
            await self._limiter.acquire()
            r = self.session.get(
                f"{TIDAL_API_URL}/v1/artists/{artist_id}",
                params={"countryCode": self.country_code},
                headers={"Accept": "application/vnd.tidal.v1+json"},
                timeout=10,
            )
            if r.status_code < 400:
                j = r.json() or {}
                nm = j.get("name") or (j.get("resource") or {}).get("name")
                if nm:
                    artist_name = nm
        except Exception:
            pass
        safe = _sanitize(artist_name)
        dest = output_dir / f"Tidal - {safe} - Top Tracks"
        dest.mkdir(parents=True, exist_ok=True)

        import asyncio as _asyncio

        sem = _asyncio.Semaphore(max(1, int(concurrency or 1)))

        async def _wrapped(tid: str):
            async with sem:
                await self.download_track(tid, quality, dest, verify=verify)

        tasks = [_wrapped(t) for t in ids[: int(limit)]]
        await _asyncio.gather(*tasks)
        console.print(
            f"[green]✅ Downloaded {len(tasks)} top tracks for {safe}[/green]"
        )
        return len(tasks)

    def _parse_track_manifest(self, stream_json: dict) -> tuple[list[str], str] | None:
        """
        Parse Tidal playback manifest to list of URLs and file extension.

        Returns (urls, extension) or None if parsing fails.
        """
        try:
            mime = stream_json.get("manifestMimeType") or stream_json.get("mimeType")
            manifest_b64 = stream_json.get("manifest")
            if not manifest_b64 or not mime:
                return None
            import base64
            from xml.etree.ElementTree import fromstring as _fromstring

            decoded = base64.b64decode(manifest_b64).decode("utf-8", "ignore")
            audio_quality = stream_json.get("audioQuality") or ""

            if mime == "application/vnd.tidal.bts":
                # JSON manifest with urls + codecs
                import json as _json

                mj = _json.loads(decoded)
                urls = (mj.get("urls") or []) if isinstance(mj, dict) else []
                codecs = (mj.get("codecs") or "") if isinstance(mj, dict) else ""
            elif mime == "application/dash+xml":
                # Parse DASH MPD to build segment urls, similar to tiddl
                NS = "{urn:mpeg:dash:schema:mpd:2011}"
                tree = _fromstring(decoded)
                rep = tree.find(f"{NS}Period/{NS}AdaptationSet/{NS}Representation")
                if rep is None:
                    return None
                codecs = rep.get("codecs", "")
                seg = rep.find(f"{NS}SegmentTemplate")
                if seg is None:
                    return None
                media = seg.get("media")
                if not media:
                    return None
                timeline = seg.findall(f"{NS}SegmentTimeline/{NS}S")
                if not timeline:
                    return None
                total = 0
                for el in timeline:
                    total += 1
                    r = el.get("r")
                    if r is not None:
                        total += int(r)
                urls = [media.replace("$Number$", str(i)) for i in range(0, total + 1)]
            else:
                return None

            # Extension decision (follow tiddl behavior)
            ext = ".flac"
            if codecs == "flac":
                ext = ".flac"
                if str(audio_quality).upper() == "HI_RES_LOSSLESS":
                    ext = ".m4a"
            elif str(codecs).startswith("mp4"):
                ext = ".m4a"
            return (urls, ext) if urls else None
        except Exception as e:
            logger.debug(
                "tidal.parse_manifest.error",
                extra={"error": str(e), "corr": self.correlation_id},
            )
            return None

    async def _get_stream_info(
        self, track_id: str, quality: str = "LOSSLESS"
    ) -> tuple[list[str], str] | None:
        """Return (urls, extension) for a track stream if available."""
        q = self._map_quality(quality)
        paths = [
            f"/v1/tracks/{track_id}/playbackinfo",
            f"/v1/tracks/{track_id}/playbackinfopostpaywall",
            f"/v1/tracks/{track_id}/playback-info",
        ]
        param_variants = [
            {
                "audioquality": q,
                "assetpresentation": "FULL",
                "playbackmode": "STREAM",
                "countryCode": self.country_code,
            },
            {
                "audioQuality": q,
                "assetPresentation": "FULL",
                "playbackmode": "STREAM",
                "countryCode": self.country_code,
            },
            {
                "audioQuality": q,
                "assetPresentation": "FULL",
                "playbackMode": "STREAM",
                "countryCode": self.country_code,
            },
            {"audioquality": q, "assetpresentation": "FULL", "playbackmode": "STREAM"},
            {"audioQuality": q, "assetPresentation": "FULL", "playbackmode": "STREAM"},
            {"audioQuality": q, "assetPresentation": "FULL", "playbackMode": "STREAM"},
        ]
        for base in [TIDAL_API_ALT_URL, TIDAL_API_FALLBACK_URL, TIDAL_API_URL]:
            for path in paths:
                for params in param_variants:
                    try:
                        url = f"{base}{path}"
                        await self._limiter.acquire()
                        accept = (
                            "application/json"
                            if base in (TIDAL_API_ALT_URL, TIDAL_API_FALLBACK_URL)
                            else "application/vnd.tidal.v1+json"
                        )
                        response = self.session.get(
                            url,
                            params=params,
                            headers={"Accept": accept},
                        )
                        if response.status_code == 404:
                            continue
                        response.raise_for_status()
                        j = response.json()
                        # Direct URLs in legacy shapes
                        if isinstance(j, dict):
                            if "track_streams" in j:
                                urls = (j.get("track_streams") or [{}])[0].get(
                                    "urls"
                                ) or []
                                if urls:
                                    ext = (
                                        ".flac"
                                        if any("flac" in u for u in urls)
                                        else ".m4a"
                                    )
                                    return urls, ext
                            if (
                                "urls" in j
                                and isinstance(j["urls"], list)
                                and j["urls"]
                            ):
                                urls = j["urls"]
                                ext = (
                                    ".flac"
                                    if any("flac" in u for u in urls)
                                    else ".m4a"
                                )
                                return urls, ext
                            # Parse manifest shapes
                            parsed = self._parse_track_manifest(j)
                            if parsed:
                                return parsed
                    except Exception:
                        continue
        return None

    async def download_track(
        self, track_id: str, quality: str, output_dir: Path, verify: bool = False
    ):
        """Downloads a single track, including metadata and cover art."""
        if not self.access_token:
            await self.authenticate()

        logger.info(
            "tidal.download_track.start",
            extra={
                "provider": "tidal",
                "track_id": track_id,
                "quality": quality,
                "corr": self.correlation_id,
            },
        )
        metadata = await self._get_track_metadata(track_id)
        # Check library DB before attempting download to avoid duplicates
        try:
            from ..core.config import get_settings as _get_settings
            from ..core.database import get_db_connection as _dbc

            st = _get_settings()
            db_path = st.db_path or (st.library_path / "flaccid.db")
            conn = _dbc(db_path)
            cur = conn.cursor()
            row = cur.execute(
                "SELECT 1 FROM tracks WHERE tidal_id=? LIMIT 1", (str(track_id),)
            ).fetchone()
            if row is not None:
                console.print(
                    "[cyan]Already in library (by Tidal ID); skipping download[/cyan]"
                )
                conn.close()
                return False
            isrc = metadata.get("isrc")
            if isrc:
                row2 = cur.execute(
                    "SELECT 1 FROM tracks WHERE isrc=? LIMIT 1", (str(isrc),)
                ).fetchone()
                if row2 is not None:
                    console.print(
                        "[cyan]Already in library (by ISRC); skipping download[/cyan]"
                    )
                    conn.close()
                    return False
            conn.close()
        except Exception:
            pass
        stream_info = await self._get_stream_info(track_id, quality)
        if not stream_info:
            raise Exception("No playable stream found")
        urls, ext = stream_info

        track_no = int(metadata.get("tracknumber") or 0)
        safe_title = _sanitize(metadata["title"])
        filename = f"{track_no:02d}. {safe_title}{ext}"
        filepath = output_dir / filename

        # If single URL, just download; if multiple, enforce container-aware muxing for M4A.
        if len(urls) == 1:
            await download_file(urls[0], filepath)
        else:
            tmp_out = filepath.with_suffix(ext + ".part")
            if ext.lower() == ".m4a":
                ffmpeg_path = shutil.which("ffmpeg")
                if not ffmpeg_path:
                    raise Exception(
                        "ffmpeg is required to mux ALAC segments into a valid M4A."
                    )
                try:
                    with TemporaryDirectory(prefix="fla_tidal_") as tmpdir:
                        seg_files: list[Path] = []
                        with requests.Session() as s:
                            for i, u in enumerate(urls):
                                # Preserve original suffix for better muxing
                                suffix = Path(u).suffix or ".mp4"
                                seg_path = Path(tmpdir) / f"seg_{i:05d}{suffix}"
                                r = s.get(u, timeout=120)
                                r.raise_for_status()
                                with open(seg_path, "wb") as sf:
                                    sf.write(r.content)
                                seg_files.append(seg_path)
                        concat_path = Path(tmpdir) / "concat.txt"
                        concat_path.write_text(
                            "".join(f"file '{p.name}'\n" for p in seg_files),
                            encoding="utf-8",
                        )
                        # Output to a temp file with proper extension so ffmpeg can infer the container
                        out_tmp = Path(tmpdir) / ("out" + ext)
                        cmd = [
                            ffmpeg_path,
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-f",
                            "concat",
                            "-safe",
                            "0",
                            "-i",
                            concat_path.name,
                            "-c",
                            "copy",
                            "-movflags",
                            "+faststart",
                            str(out_tmp),
                        ]
                        subprocess.run(cmd, check=True, cwd=tmpdir)
                        # Move to final destination via .part name first
                        Path(out_tmp).replace(tmp_out)
                except Exception as e:
                    logger.debug(
                        "tidal.ffmpeg_concat.failed",
                        extra={"error": str(e), "corr": self.correlation_id},
                    )
                    # Fallback: naive concatenation of init + segments
                    with open(tmp_out, "wb") as out:
                        with requests.Session() as s:
                            for u in urls:
                                rr = s.get(u, stream=True, timeout=120)
                                rr.raise_for_status()
                                for chunk in rr.iter_content(8192):
                                    if chunk:
                                        out.write(chunk)
                Path(tmp_out).rename(filepath)
            else:
                # Non-M4A segmented content: best-effort append as before
                with open(tmp_out, "wb") as f:
                    with requests.Session() as s:
                        for u in urls:
                            r = s.get(u, timeout=60)
                            r.raise_for_status()
                            f.write(r.content)
                Path(tmp_out).rename(filepath)

        # Basic container validation for M4A; suggest ffmpeg if invalid
        if filepath.suffix.lower() == ".m4a":
            try:
                from mutagen.mp4 import MP4  # type: ignore

                _ = MP4(filepath)
            except Exception:
                console.print(
                    "[yellow]Warning:[/yellow] Resulting M4A may not be container-valid.\n"
                    "Install ffmpeg for a safe, bitstream copy mux (no re-encode)."
                )
        apply_metadata(filepath, metadata)
        # Upsert into library database with provider IDs unless explicitly disabled
        try:
            import os as _os

            if (_os.getenv("FLA_DISABLE_AUTO_DB") or "").strip() != "1":
                from ..core.config import get_settings as _get_settings
                from ..core.database import Track as _Track
                from ..core.database import get_db_connection as _dbc
                from ..core.database import init_db as _init_db
                from ..core.database import insert_track as _insert
                from ..core.database import upsert_track_id as _upsert_id

                _st = _get_settings()
                _db_path = _st.db_path or (_st.library_path / "flaccid.db")
                conn = _dbc(_db_path)
                _init_db(conn)
                tr = _Track(
                    title=str(metadata.get("title")),
                    artist=(
                        str(metadata.get("artist")) if metadata.get("artist") else None
                    ),
                    album=str(metadata.get("album")) if metadata.get("album") else None,
                    albumartist=(
                        str(metadata.get("albumartist"))
                        if metadata.get("albumartist")
                        else None
                    ),
                    tracknumber=int(metadata.get("tracknumber") or 0),
                    discnumber=int(metadata.get("discnumber") or 0),
                    duration=None,
                    isrc=metadata.get("isrc"),
                    tidal_id=str(track_id),
                    path=str(filepath.resolve()),
                    hash=None,
                    last_modified=filepath.stat().st_mtime,
                )
                rowid = _insert(conn, tr)
                try:
                    if rowid is not None:
                        _upsert_id(conn, rowid, "tidal", str(track_id), preferred=False)
                        if metadata.get("isrc"):
                            _upsert_id(
                                conn,
                                rowid,
                                "isrc",
                                str(metadata.get("isrc")),
                                preferred=False,
                            )
                except Exception:
                    pass
                conn.close()
        except Exception:
            pass
        if verify:
            try:
                from ..core.verify import verify_media

                info = verify_media(filepath)
                if info is not None:
                    console.print(
                        f"[cyan]Verified:[/cyan] {info.get('codec')} {info.get('sample_rate')}Hz "
                        f"{info.get('channels')}ch, duration {info.get('duration')}s"
                    )
                    # Simple expectation check based on extension
                    codec = (info.get("codec") or "").lower()
                    if filepath.suffix.lower() == ".m4a" and codec not in {
                        "alac",
                        "aac",
                        "mp4a",
                    }:
                        console.print(
                            f"[yellow]Warning:[/yellow] Unexpected codec '{codec}' for .m4a output."
                        )
                    if filepath.suffix.lower() == ".flac" and codec != "flac":
                        console.print(
                            f"[yellow]Warning:[/yellow] Unexpected codec '{codec}' for .flac output."
                        )
            except Exception:
                console.print("[yellow]Warning:[/yellow] ffprobe verification failed.")
        console.print(f"[green]✅ Downloaded '{metadata['title']}'[/green]")
        logger.info(
            "tidal.download_track.done",
            extra={
                "provider": "tidal",
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
        *,
        concurrency: int = 4,
        verify: bool = False,
    ):
        """Downloads all tracks from a Tidal album concurrently."""
        if not self.access_token:
            await self.authenticate()

        tracks = []
        for base in [TIDAL_API_URL, TIDAL_API_FALLBACK_URL]:
            try:
                url = f"{base}/v1/albums/{album_id}/tracks"
                await self._limiter.acquire()
                response = self.session.get(
                    url,
                    params={"countryCode": self.country_code, "limit": 200},
                    headers={"Accept": "application/vnd.tidal.v1+json"},
                )
                if response.status_code == 404:
                    if base == TIDAL_API_FALLBACK_URL:
                        import os as _os

                        cc = _os.getenv("FLA_TIDAL_COUNTRY", "US")
                        response = self.session.get(
                            url,
                            params={"countryCode": cc},
                            headers={"Accept": "application/json"},
                        )
                        if response.status_code == 404:
                            continue
                    else:
                        continue
                response.raise_for_status()
                j = response.json()
                if isinstance(j, dict) and "data" in j:
                    tracks = j["data"]
                elif isinstance(j, dict) and "items" in j:
                    tracks = j["items"]
                elif isinstance(j, list):
                    tracks = j
                else:
                    tracks = []
                break
            except Exception:
                continue
        if not tracks:
            raise Exception("No tracks found for this album.")

        def _track_id(t: dict):
            if isinstance(t, dict):
                return t.get("id") or (t.get("item") or {}).get("id")
            return None

        first_id = _track_id(tracks[0])
        meta_default = {"album": "Unknown Album", "albumartist": "Unknown Artist"}
        first_track_meta = (
            await self._get_track_metadata(str(first_id)) if first_id else meta_default
        )
        album_name = (
            (first_track_meta.get("album") or "Unknown Album")
            .replace("/", "-")
            .replace("\\", "-")
        )
        artist_name = (
            (first_track_meta.get("albumartist") or "Unknown Artist")
            .replace("/", "-")
            .replace("\\", "-")
        )
        album_dir = output_dir / f"{artist_name} - {album_name}"
        album_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"Downloading {len(tracks)} tracks to [blue]{album_dir}[/blue]")
        logger.info(
            "tidal.download_album.start",
            extra={
                "provider": "tidal",
                "album_id": album_id,
                "tracks": len(tracks),
                "quality": quality,
                "corr": self.correlation_id,
            },
        )
        import asyncio as _asyncio

        # Filter out tracks already in DB by Tidal ID or ISRC to avoid duplicates
        try:
            from ..core.config import get_settings as _get_settings
            from ..core.database import get_db_connection as _dbc

            _st = _get_settings()
            _db_path = _st.db_path or (_st.library_path / "flaccid.db")
            conn = _dbc(_db_path)
            cur = conn.cursor()

            def _exists_by_tid(_tid: str) -> bool:
                try:
                    from ..core.database import has_track as _has

                    return _has(cur.connection, tidal_id=str(_tid))
                except Exception:
                    return False

            kept = []
            skipped = 0
            for t in tracks:
                tid = _track_id(t)
                if not tid:
                    continue
                tid = str(tid)
                if _exists_by_tid(tid):
                    skipped += 1
                    continue
                # Try ISRC-based skip by fetching minimal metadata
                try:
                    md = await self._get_track_metadata(tid)
                    isrc = (md or {}).get("isrc") if isinstance(md, dict) else None
                    try:
                        from ..core.database import has_track as _has

                        if _has(cur.connection, isrc=str(isrc) if isrc else None):
                            skipped += 1
                            continue
                    except Exception:
                        pass
                except Exception:
                    pass
                kept.append(t)
            if skipped > 0:
                console.print(
                    f"[cyan]Skipping {skipped} tracks already in library[/cyan]"
                )
            tracks = kept
            conn.close()
        except Exception:
            pass

        sem = _asyncio.Semaphore(max(1, int(concurrency or 1)))

        async def _wrapped(tid: str):
            async with sem:
                await self.download_track(tid, quality, album_dir, verify)

        ids = [_track_id(t) for t in tracks]
        tasks = [_wrapped(tid) for tid in ids if tid]
        await _asyncio.gather(*tasks)

        console.print("[green]✅ Album download complete![/green]")
        logger.info(
            "tidal.download_album.done",
            extra={
                "provider": "tidal",
                "album_id": album_id,
                "tracks": len(tracks),
                "corr": self.correlation_id,
            },
        )

    async def download_playlist(
        self,
        playlist_id: str,
        quality: str,
        output_dir: Path,
        *,
        concurrency: int = 4,
        verify: bool = False,
        limit: int | None = None,
    ):
        """Downloads all tracks from a Tidal playlist concurrently."""
        if not self.access_token:
            await self.authenticate()

        # Fetch playlist metadata (name) and items
        name = f"Playlist {playlist_id}"
        items = []
        for base in [TIDAL_API_URL, TIDAL_API_FALLBACK_URL, TIDAL_API_ALT_URL]:
            try:
                # Metadata
                await self._limiter.acquire()
                meta = self.session.get(
                    f"{base}/v1/playlists/{playlist_id}",
                    params={"countryCode": self.country_code},
                    headers={"Accept": "application/vnd.tidal.v1+json"},
                    timeout=10,
                )
                if meta.status_code in (200, 404):
                    try:
                        mj = meta.json() or {}
                        nm = (
                            mj.get("title")
                            or mj.get("name")
                            or mj.get("resource", {}).get("title")
                        )
                        if nm:
                            name = str(nm)
                    except Exception:
                        pass
                # Items
                await self._limiter.acquire()
                resp = self.session.get(
                    f"{base}/v1/playlists/{playlist_id}/items",
                    params={"countryCode": self.country_code, "limit": 500},
                    headers={"Accept": "application/vnd.tidal.v1+json"},
                    timeout=15,
                )
                if resp.status_code == 404:
                    # Fallback path shape
                    resp = self.session.get(
                        f"{base}/v1/playlists/{playlist_id}/tracks",
                        params={"countryCode": self.country_code, "limit": 500},
                        headers={"Accept": "application/vnd.tidal.v1+json"},
                        timeout=15,
                    )
                if resp.status_code >= 400:
                    continue
                j = resp.json() or {}
                if isinstance(j, dict):
                    items = j.get("items") or j.get("data") or []
                elif isinstance(j, list):
                    items = j
                if items:
                    break
            except Exception:
                continue
        if not items:
            raise Exception("No tracks found in playlist.")

        def _tid_from_item(it: dict) -> str | None:
            if not isinstance(it, dict):
                return None
            # common shapes: {item:{id:..}} or direct {id:..}
            return str((it.get("item") or {}).get("id") or it.get("id")) if it else None

        # Prepare output directory
        safe_name = _sanitize(name or f"Playlist {playlist_id}")
        pl_dir = output_dir / f"Tidal - {safe_name}"
        pl_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"Downloading playlist to [blue]{pl_dir}[/blue]")

        # Download concurrently with simple throttle
        import asyncio as _asyncio

        sem = _asyncio.Semaphore(max(1, int(concurrency or 1)))

        async def _wrapped(tid: str):
            async with sem:
                await self.download_track(tid, quality, pl_dir, verify)

        ids = [_tid_from_item(x) for x in items]
        if isinstance(limit, int) and limit > 0:
            ids = [t for t in ids if t][:limit]
        tasks = [_wrapped(t) for t in ids if t]
        await _asyncio.gather(*tasks)
        console.print("[green]✅ Playlist download complete![/green]")
