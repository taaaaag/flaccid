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
import logging
import os as _os  # noqa: F401  # reserved for dynamic imports in this module
import time
from pathlib import Path
from typing import List, Optional, Tuple

import aiohttp
from rich.console import Console

from ..core.auth import get_credentials
from ..core.config import get_settings
from ..core.config import get_settings as _get_settings_cfg
from ..core.database import get_db_connection as _db_conn
from ..core.downloader import download_file
from ..core.metadata import apply_metadata
from ..core.ratelimit import AsyncRateLimiter
from .base import BasePlugin

QOBUZ_API_URL = "https://www.qobuz.com/api.json/0.2"
DEFAULT_QOBUZ_APP_ID = "798273057"
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
    """
    Create Qobuz request signature.

    Observed behavior (compatible with tests/streamrip):
    - Endpoint normalized by stripping leading/trailing slashes only
      e.g., '/track/getFileUrl' -> 'track/getFileUrl'
    - Params used in signature include app_id and user_auth_token (sorted by key)
    - Params are concatenated in key order as key+value (no separators)
    - Timestamp is a float/int-as-string (time.time())
    - Signature = MD5(endpoint + params + ts + secret)
    """
    ts = str(time.time())  # float or int timestamp string
    endpoint_clean = endpoint.strip("/")
    # Include all params (app_id, user_auth_token, etc.), sorted by key
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(kwargs.items()))
    base_string = f"{endpoint_clean}{sorted_params}{ts}{secret}"
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
        app_secret: Optional[str],
        auth_token: str,
        session: aiohttp.ClientSession,
        limiter: AsyncRateLimiter | None = None,
        app_secrets: Optional[List[str]] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.auth_token = auth_token
        self.session = session
        self.limiter = limiter
        # Try multiple secrets when provided, first wins
        self.app_secrets = list(app_secrets or ([] if not app_secret else [app_secret]))
        self.active_secret: Optional[str] = None
        # Discovered working formats preference (highest → lowest)
        self.format_preference: Optional[List[int]] = None

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
            ts, sig = _sign_request(self.app_secret, endpoint.strip("/"), **request_params)
            request_params["request_ts"] = ts
            request_params["request_sig"] = sig
        async with self.session.get(full_url, params=request_params) as response:
            response.raise_for_status()
            return await response.json()

    async def get_track(self, track_id: str) -> dict:
        return await self._request("/track/get", {"track_id": track_id})

    async def get_album(self, album_id: str) -> dict:
        return await self._request("/album/get", {"album_id": album_id})

    async def get_file_url(
        self, track_id: str, format_id: int, *, timeout: float | None = None
    ) -> dict:
        if not self.session:
            raise RuntimeError("API client must be used within an active session.")
        if not self.app_secrets:
            raise RuntimeError(
                "Qobuz app secret(s) not configured. Provide qobuz_app_secret or qobuz_secrets."
            )
        endpoint = f"{QOBUZ_API_URL}/track/getFileUrl"
        # Do NOT include app_id/user_auth_token in params; send via headers only
        base_params = {"track_id": track_id, "format_id": format_id, "intent": "stream"}
        last_exc: Exception | None = None
        secrets_to_try = [self.active_secret] if self.active_secret else list(self.app_secrets)
        for secret in secrets_to_try:
            if not secret:
                continue
            try:
                if self.limiter:
                    await self.limiter.acquire()
                ts, sig = _sign_request(
                    secret,
                    "/track/getFileUrl",
                    **base_params,
                )
                params = dict(base_params)
                params["request_ts"] = ts
                params["request_sig"] = sig
                # Keep per-try timeout short so unsupported formats don't stall
                import aiohttp as _aio

                to = _aio.ClientTimeout(total=(timeout or 4.0))
                async with self.session.get(endpoint, params=params, timeout=to) as response:
                    response.raise_for_status()
                    jd = await response.json()
                    if isinstance(jd, dict) and jd.get("url"):
                        # Cache winner secret for subsequent calls
                        self.active_secret = secret
                        return jd
                    file_obj = jd.get("file") if isinstance(jd, dict) else None
                    if isinstance(file_obj, dict) and file_obj.get("url"):
                        self.active_secret = secret
                        return {"url": file_obj.get("url")}
            except Exception as e:
                last_exc = e
                continue
        # No secret worked
        if last_exc:
            raise last_exc
        return {}

    async def prime_secret(self) -> None:
        """Quickly select a working secret (like Streamrip/qopy cfg_setup()).

        Tries each secret once against a known public track id with FLAC format.
        Uses a short per-request timeout to avoid long stalls.
        """
        if not self.session or not self.app_secrets:
            return
        TEST_TRACK_ID = "5966783"  # common test id used in community tools
        endpoint = f"{QOBUZ_API_URL}/track/getFileUrl"
        for secret in self.app_secrets:
            if not secret:
                continue
            try:
                ts, sig = _sign_request(
                    secret,
                    "/track/getFileUrl",
                    track_id=TEST_TRACK_ID,
                    # Use MP3 for maximum compatibility when priming secret
                    format_id=5,
                    intent="stream",
                )
                params = {
                    "track_id": TEST_TRACK_ID,
                    "format_id": 5,
                    "intent": "stream",
                    "request_ts": ts,
                    "request_sig": sig,
                }
                # Short timeout per probe
                import aiohttp as _aio

                to = _aio.ClientTimeout(total=3.5)
                async with self.session.get(endpoint, params=params, timeout=to) as r:
                    if r.status != 200:
                        continue
                    jd = await r.json()
                    url = (jd or {}).get("url") or ((jd or {}).get("file") or {}).get("url")
                    if url:
                        self.active_secret = secret
                        return
            except Exception:
                continue

    async def calibrate_formats(self) -> None:
        """Discover the highest working format_id once and cache an order.

        Mirrors qobuz-dl behavior by probing a public test track with
        descending quality list. This avoids trying unavailable formats for
        every track (e.g., 29) when the account or region doesn’t support them.
        """
        if not self.session or not (self.active_secret or self.app_secrets):
            return
        order = [29, 27, 19, 7, 6, 5]
        TEST_TRACK_ID = "5966783"
        for fmt in order:
            try:
                jd = await self.get_file_url(TEST_TRACK_ID, fmt, timeout=2.0)
                url = (jd or {}).get("url") or ((jd or {}).get("file") or {}).get("url")
                if url:
                    # Prefer from the first working fmt onwards
                    idx = order.index(fmt)
                    self.format_preference = order[idx:]
                    logger = logging.getLogger(__name__)
                    logger.debug("qobuz.calibrate_formats: preference=%s", self.format_preference)
                    return
            except Exception:
                continue
        # If none worked, leave as None; caller uses defaults

    async def calibrate_formats_for_track(self, track_id: str) -> None:
        """Calibrate working formats using the actual target track id.

        Helps when global calibration fails due to geo/rights limits on the
        test track. Establishes a preference list for subsequent downloads.
        """
        if not self.session or not (self.active_secret or self.app_secrets):
            return
        order = [29, 27, 19, 7, 6, 5]
        for fmt in order:
            try:
                jd = await self.get_file_url(track_id, fmt, timeout=2.0)
                url = (jd or {}).get("url") or ((jd or {}).get("file") or {}).get("url")
                if url:
                    idx = order.index(fmt)
                    self.format_preference = order[idx:]
                    logger = logging.getLogger(__name__)
                    logger.debug(
                        "qobuz.calibrate_formats_for_track: track=%s preference=%s",
                        track_id,
                        self.format_preference,
                    )
                    return
            except Exception:
                continue

    async def get_playlist(self, playlist_id: str, *, limit: int = 500, offset: int = 0) -> dict:
        # Qobuz playlist metadata (tracks are usually under tracks.items)
        # Prefer auth in headers (X-App-Id, X-User-Auth-Token) without app_id/user_auth_token params.
        if not self.session:
            raise RuntimeError("API client must be used within an active session.")
        if self.limiter:
            await self.limiter.acquire()
        full_url = f"{QOBUZ_API_URL}/playlist/get"
        params = {
            "playlist_id": playlist_id,
            "limit": limit,
            "offset": offset,
            "extra": "tracks",
        }
        async with self.session.get(full_url, params=params) as response:
            response.raise_for_status()
            return await response.json()

    async def search_track(self, query: str, *, limit: int = 5, offset: int = 0) -> dict:
        if not self.session:
            raise RuntimeError("API client must be used within an active session.")
        if self.limiter:
            await self.limiter.acquire()
        full_url = f"{QOBUZ_API_URL}/track/search"
        params = {"query": query, "limit": limit, "offset": offset}
        async with self.session.get(full_url, params=params) as response:
            response.raise_for_status()
            return await response.json()


def _load_streamrip_config() -> tuple[Optional[str], list[str]]:
    """Load app_id and secrets from Streamrip config if present.

    macOS: ~/Library/Application Support/streamrip/config.toml
    Linux: ~/.config/streamrip/config.toml
    """
    import os as _os  # noqa: F401

    import toml as _toml

    paths = [
        Path.home() / "Library" / "Application Support" / "streamrip" / "config.toml",
        Path.home() / ".config" / "streamrip" / "config.toml",
    ]
    for p in paths:
        try:
            if p.exists():
                data = _toml.loads(p.read_text(encoding="utf-8")) or {}
                q = data.get("qobuz") or {}
                app_id = q.get("app_id")
                secrets = q.get("secrets") or []
                if isinstance(secrets, list):
                    secrets = [str(s) for s in secrets if s]
                else:
                    secrets = []
                return (str(app_id) if app_id else None, secrets)
        except Exception:
            continue
    return None, []


class QobuzPlugin(BasePlugin):
    def __init__(
        self,
        *,
        correlation_id: str | None = None,
        rps: int | None = None,
        prefer_29: bool | None = False,
    ):
        self.app_id: str | None = None
        self.app_secret: str | None = None
        self.app_secrets: list[str] | None = None
        self.auth_token: str | None = None
        self.api_client: _QobuzApiClient | None = None
        self.session: aiohttp.ClientSession | None = None
        self.correlation_id: str | None = correlation_id
        self._rps: int | None = rps
        self._prefer_29: bool | None = prefer_29

    async def authenticate(self):
        console.print("Authenticating with Qobuz...")
        settings = get_settings()
        # App ID: settings -> keyring -> streamrip config -> env -> default
        self.app_id = settings.qobuz_app_id or get_credentials("qobuz", "app_id")
        sr_app_id, sr_secrets = _load_streamrip_config()
        if not self.app_id and sr_app_id:
            self.app_id = sr_app_id
        if not self.app_id:
            env_app = _os.getenv("FLA_QOBUZ_APP_ID") or _os.getenv("QOBUZ_APP_ID")
            self.app_id = env_app or DEFAULT_QOBUZ_APP_ID

        # Secrets: settings (list) + single secret -> env -> streamrip
        secrets_from_settings = []
        try:
            secrets_from_settings = list(getattr(settings, "qobuz_secrets", []) or [])
        except Exception:
            secrets_from_settings = []
        single_secret = getattr(settings, "qobuz_app_secret", None) or get_credentials(
            "qobuz", "app_secret"
        )
        secrets_env = []
        try:
            import os as _os  # noqa: F401

            env_val = _os.getenv("FLA_QOBUZ_SECRETS")
            if env_val:
                secrets_env = [s.strip() for s in env_val.split(",") if s.strip()]
        except Exception:
            secrets_env = []
        # Consolidate secrets
        secrets: list[str] = []
        for source in (secrets_from_settings, secrets_env, sr_secrets):
            for s in source:
                if s and s not in secrets:
                    secrets.append(s)
        if single_secret and single_secret not in secrets:
            secrets.append(single_secret)
        self.app_secrets = secrets
        self.app_secret = single_secret

        # Token: keyring/env/.secrets.toml; if missing, try streamrip config fallback
        self.auth_token = get_credentials("qobuz", "user_auth_token")
        if not self.auth_token and sr_app_id and sr_secrets:
            # Try to derive token from streamrip config (email+password or token)
            try:
                import requests as _requests
                import toml as _toml

                sr_paths = [
                    Path.home() / "Library" / "Application Support" / "streamrip" / "config.toml",
                    Path.home() / ".config" / "streamrip" / "config.toml",
                ]
                for p in sr_paths:
                    if p.exists():
                        cfg = _toml.loads(p.read_text(encoding="utf-8")) or {}
                        q = cfg.get("qobuz") or {}
                        use_auth_token = bool(q.get("use_auth_token", False))
                        if use_auth_token and q.get("password_or_token"):
                            self.auth_token = str(q.get("password_or_token"))
                            break
                        email = q.get("email_or_userid")
                        pw = q.get("password_or_token")
                        if email and pw and self.app_id:
                            pwd_md5 = (
                                pw
                                if isinstance(pw, str)
                                and len(pw) == 32
                                and all(c in "0123456789abcdef" for c in pw.lower())
                                else hashlib.md5(str(pw).encode("utf-8")).hexdigest()
                            )
                            r = _requests.post(
                                f"{QOBUZ_API_URL}/user/login",
                                data={
                                    "email": email,
                                    "password": pwd_md5,
                                    "app_id": self.app_id,
                                },
                                headers={"User-Agent": "flaccid/0.1.0"},
                                timeout=20,
                            )
                            if r.status_code < 400:
                                jd = r.json() or {}
                                tok = jd.get("user_auth_token") or (
                                    (jd.get("user") or {}).get("user_auth_token")
                                )
                                if tok:
                                    self.auth_token = tok
                                    break
            except Exception:
                pass

        # Validate minimum requirements
        if not self.app_id or not self.auth_token:
            raise Exception(
                "Qobuz credentials not found. Need app_id and user_auth_token. "
                "Run `fla config auto-qobuz` or provide Streamrip config."
            )
        if not self.app_secrets:
            console.print(
                "[yellow]Warning:[/yellow] No Qobuz app secrets configured; some file URLs may fail."
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
        def _safe_get(d: dict | None, key: str):
            return d.get(key) if isinstance(d, dict) else None

        def _join_names(val) -> str | None:
            # Accept list[dict|str] | dict | str
            if val is None:
                return None
            if isinstance(val, list):
                names: list[str] = []
                for it in val:
                    if isinstance(it, dict) and it.get("name"):
                        names.append(str(it.get("name")))
                    elif isinstance(it, str) and it.strip():
                        names.append(it.strip())
                return ", ".join(names) if names else None
            if isinstance(val, dict):
                n = val.get("name")
                return str(n) if n else None
            if isinstance(val, str):
                return val.strip() or None
            return None

        def _extract_main_artist_from_performers(val) -> str | None:
            """Try to pick only main/primary artists from a performers list.

            Qobuz may include many contributors in `performers` with roles.
            We filter to common main roles so the ARTIST tag remains clean.
            """
            if not isinstance(val, list):
                return None
            names: list[str] = []
            for it in val:
                if not isinstance(it, dict):
                    continue
                role = str(it.get("role") or it.get("type") or "").lower()
                if any(k in role for k in ("main", "primary")) or role in {
                    "artist",
                    "mainartist",
                    "main artist",
                }:
                    n = it.get("name")
                    if not n and isinstance(it.get("artist"), dict):
                        n = it.get("artist", {}).get("name")
                    if n and str(n) not in names:
                        names.append(str(n))
            return ", ".join(names) if names else None

        album = track_data.get("album") or {}
        albumartist = _join_names(_safe_get(album, "artist"))
        performers = track_data.get("performers")
        # Prefer specific main/primary artist, then track.artist, then album artist
        artist = (
            _extract_main_artist_from_performers(performers)
            or _join_names(track_data.get("artist"))
            or _join_names(track_data.get("performer"))
            or albumartist
        )
        label_v = _safe_get(album, "label")
        label = (
            label_v.get("name")
            if isinstance(label_v, dict)
            else (label_v if isinstance(label_v, str) else None)
        )
        genre_v = _safe_get(album, "genre")
        genre = (
            genre_v.get("name")
            if isinstance(genre_v, dict)
            else (genre_v if isinstance(genre_v, str) else None)
        )
        img_v = _safe_get(album, "image")
        cover_url = (
            img_v.get("large")
            if isinstance(img_v, dict)
            else (img_v if isinstance(img_v, str) else None)
        )

        date_orig = _safe_get(album, "release_date_original")
        year = None
        try:
            if isinstance(date_orig, str) and len(date_orig) >= 4:
                year = date_orig[:4]
        except Exception:
            year = None

        fields = {
            "title": track_data.get("title"),
            "artist": artist,
            "album": _safe_get(album, "title"),
            "albumartist": albumartist,
            "tracknumber": track_data.get("track_number") or track_data.get("trackNumber"),
            "tracktotal": _safe_get(album, "tracks_count") or _safe_get(album, "track_count"),
            "discnumber": track_data.get("media_number") or track_data.get("disc_number") or 1,
            "disctotal": _safe_get(album, "media_count") or _safe_get(album, "mediaCount") or 1,
            "date": date_orig,
            "year": year,
            "isrc": track_data.get("isrc"),
            "copyright": track_data.get("copyright"),
            "label": label,
            "genre": genre,
            "upc": _safe_get(album, "upc"),
            "lyrics": track_data.get("lyrics"),
            "cover_url": cover_url,
            # Provider identifiers for tagging and DB
            "qobuz_track_id": (str(track_data.get("id")) if track_data.get("id") else None),
            "qobuz_album_id": (str(_safe_get(album, "id")) if _safe_get(album, "id") else None),
        }
        return {k: v for k, v in fields.items() if v is not None}

    async def download_track(
        self,
        track_id: str,
        quality: str,
        output_dir: Path,
        allow_mp3: bool = False,
        verify: bool = False,
    ) -> bool:
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
            return False
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
            return False
        ext = ".flac"
        # Check library DB before attempting download to avoid duplicates
        try:
            st = _get_settings_cfg()
            db_path = st.db_path or (st.library_path / "flaccid.db")
            conn = _db_conn(db_path)
            cur = conn.cursor()
            isrc = metadata.get("isrc")
            if isrc:
                row = cur.execute(
                    "SELECT 1 FROM tracks WHERE isrc=? LIMIT 1", (str(isrc),)
                ).fetchone()
                if row is not None:
                    console.print(
                        "[cyan]Already in library (by ISRC); skipping download[/cyan]"
                    )
                    conn.close()
                    return False
            row2 = cur.execute(
                "SELECT 1 FROM tracks WHERE qobuz_id=? LIMIT 1", (str(track_id),)
            ).fetchone()
            if row2 is not None:
                console.print(
                    "[cyan]Already in library (by Qobuz ID); skipping download[/cyan]"
                )
                conn.close()
                return False
            conn.close()
        except Exception:
            pass
        relative_path = _generate_path_from_template(metadata, ext)
        filepath = output_dir / relative_path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        await download_file(stream_url, filepath)
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
                    artist=(str(metadata.get("artist")) if metadata.get("artist") else None),
                    album=str(metadata.get("album")) if metadata.get("album") else None,
                    albumartist=(
                        str(metadata.get("albumartist")) if metadata.get("albumartist") else None
                    ),
                    tracknumber=int(metadata.get("tracknumber") or 0),
                    discnumber=int(metadata.get("discnumber") or 0),
                    duration=None,
                    isrc=metadata.get("isrc"),
                    qobuz_id=str(metadata.get("qobuz_track_id") or track_id),
                    path=str(filepath.resolve()),
                    hash=None,
                    last_modified=filepath.stat().st_mtime,
                )
                rowid = _insert(conn, tr)
                try:
                    # Also persist identifiers in track_ids for consistent lookup
                    if rowid is not None:
                        if metadata.get("qobuz_track_id"):
                            _upsert_id(
                                conn,
                                rowid,
                                "qobuz",
                                str(metadata.get("qobuz_track_id")),
                                preferred=False,
                            )
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
                    codec = (info.get("codec") or "").lower()
                    if filepath.suffix.lower() == ".flac" and codec != "flac":
                        console.print(
                            f"[yellow]Warning:[/yellow] Unexpected codec '{codec}' for .flac output."
                        )
            except Exception:
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
        return True

    async def download_album(
        self,
        album_id: str,
        quality: str,
        output_dir: Path,
        allow_mp3: bool = False,
        concurrency: int = 4,
        verify: bool = False,
    ) -> int:
        if not self.api_client:
            raise RuntimeError("Plugin not authenticated or session not started.")
        album_data = await self.api_client.get_album(album_id)
        tracks = album_data.get("tracks", {}).get("items", [])
        console.print(f"Downloading {len(tracks)} tracks from '{album_data['title']}'...")
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
        # Filter out tracks already in DB by Qobuz ID or ISRC
        try:
            st = _get_settings_cfg()
            db_path = st.db_path or (st.library_path / "flaccid.db")
            conn = _db_conn(db_path)
            cur = conn.cursor()

            def _exists(tid: str, isrc: str | None) -> bool:
                try:
                    if isrc:
                        row = cur.execute(
                            "SELECT 1 FROM tracks WHERE isrc=? LIMIT 1", (isrc,)
                        ).fetchone()
                        if row is not None:
                            return True
                    row2 = cur.execute(
                        "SELECT 1 FROM tracks WHERE qobuz_id=? LIMIT 1", (tid,)
                    ).fetchone()
                    return row2 is not None
                except Exception:
                    return False

            before = len(tracks)
            tracks = [t for t in tracks if not _exists(str(t.get("id")), (t or {}).get("isrc"))]
            skipped = before - len(tracks)
            if skipped > 0:
                console.print(f"[cyan]Skipping {skipped} tracks already in library[/cyan]")
            conn.close()
        except Exception:
            pass
        if not tracks:
            console.print("[green]✅ All tracks already present in library[/green]")
            return 0
        # Pre-calibrate format preference using the first track to avoid
        # wasted attempts across concurrent downloads (especially fmt 29).
        try:
            if tracks and getattr(self.api_client, "format_preference", None) is None:
                first_tid = str(tracks[0]["id"]) if isinstance(tracks[0], dict) else None
                if first_tid:
                    await self.api_client.calibrate_formats_for_track(first_tid)
        except Exception:
            pass
        sem = asyncio.Semaphore(max(1, int(concurrency or 1)))

        async def _wrapped(tid: str):
            async with sem:
                return await self.download_track(tid, quality, output_dir, allow_mp3, verify)

        tasks = [_wrapped(str(track["id"])) for track in tracks]
        results = await asyncio.gather(*tasks)
        succeeded = sum(1 for r in results if r)
        console.print(
            f"[green]\u2705 Album download complete![/green] ({succeeded}/{len(tracks)} tracks)"
        )
        logger.info(
            "qobuz.download_album.done",
            extra={
                "provider": "qobuz",
                "album_id": album_id,
                "tracks": len(tracks),
                "corr": self.correlation_id,
            },
        )
        return succeeded

    async def download_playlist(
        self,
        playlist_id: str,
        quality: str,
        output_dir: Path,
        allow_mp3: bool = False,
        concurrency: int = 4,
        verify: bool = False,
    ) -> int:
        if not self.api_client:
            raise RuntimeError("Plugin not authenticated or session not started.")
        # Fetch first page and paginate if necessary
        pl_data = await self.api_client.get_playlist(playlist_id, limit=500, offset=0)
        tracks_obj = (pl_data.get("tracks") or {}) if isinstance(pl_data, dict) else {}
        items: list = []
        if isinstance(tracks_obj, dict):
            items = list(tracks_obj.get("items") or [])
        elif isinstance(tracks_obj, list):
            items = list(tracks_obj)
        total = None
        try:
            total = (
                (tracks_obj.get("total") if isinstance(tracks_obj, dict) else None)
                or pl_data.get("tracks_count")
                or len(items)
            )
        except Exception:
            total = len(items)
        offset = 500
        while total and len(items) < int(total):
            try:
                page = await self.api_client.get_playlist(playlist_id, limit=500, offset=offset)
                t_obj = (page.get("tracks") or {}) if isinstance(page, dict) else {}
                more = (t_obj.get("items") or []) if isinstance(t_obj, dict) else []
                if not more:
                    break
                items.extend(more)
                offset += 500
            except Exception:
                break

        name = pl_data.get("name") or pl_data.get("title") or f"Playlist-{playlist_id}"
        console.print(f"Downloading {len(items)} tracks from playlist '{name}'...")
        logger.info(
            "qobuz.download_playlist.start",
            extra={
                "provider": "qobuz",
                "playlist_id": playlist_id,
                "tracks": len(items),
                "quality": quality,
                "corr": self.correlation_id,
            },
        )
        sem = asyncio.Semaphore(max(1, int(concurrency or 1)))

        async def _wrapped(tid: str):
            async with sem:
                await self.download_track(tid, quality, output_dir, allow_mp3, verify)

        # Items can be full track dicts or nested under 'track'
        def _extract_track_id(item) -> str | None:
            if isinstance(item, dict):
                if "id" in item:
                    return str(item["id"])
                inner = item.get("track") if isinstance(item.get("track"), dict) else None
                if inner and inner.get("id"):
                    return str(inner.get("id"))
            return None

        task_ids = [_extract_track_id(t) for t in items]
        task_ids = [tid for tid in task_ids if tid]
        tasks = [_wrapped(tid) for tid in task_ids]
        if tasks:
            await asyncio.gather(*tasks)
        console.print("[green]\u2705 Playlist download complete![/green]")
        logger.info(
            "qobuz.download_playlist.done",
            extra={
                "provider": "qobuz",
                "playlist_id": playlist_id,
                "tracks": len(task_ids),
                "corr": self.correlation_id,
            },
        )
        return len(task_ids)

    async def _find_stream(
        self, track_id: str, quality: str, allow_mp3: bool = False
    ) -> tuple[int | None, str | None]:
        if not self.api_client:
            raise RuntimeError("Plugin not authenticated or session not started.")
        # If no calibrated preference yet, try calibrating on this track id
        if getattr(self.api_client, "format_preference", None) is None:
            try:
                await self.api_client.calibrate_formats_for_track(track_id)
            except Exception:
                pass
        key = (str(quality) if quality is not None else "").lower()
        try:
            if key.isdigit() and int(key) >= 4:
                key = "max"
        except Exception:
            pass
        tried = list(QUALITY_FALLBACKS.get(key, QUALITY_FALLBACKS.get("max")))
        # Optional override to skip 29 globally
        try:
            import os as _os

            if (_os.getenv("FLA_QOBUZ_SKIP_29") or "").strip() == "1":
                tried = [f for f in tried if f != 29]
        except Exception:
            pass
        # If we have a calibrated preference, reorder to try those first
        pref = getattr(self.api_client, "format_preference", None)
        if pref:
            ordered = [fmt for fmt in pref if fmt in tried]
            tail = [fmt for fmt in tried if fmt not in ordered]
            tried = ordered + tail
        # Apply explicit preference toggle from CLI/env
        if getattr(self, "_prefer_29", None) is not None:
            if self._prefer_29 is False:
                tried = [f for f in tried if f != 29]
            elif self._prefer_29 is True and 29 in tried:
                tried = [29] + [f for f in tried if f != 29]
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
                    logger.debug("Qobuz: format_id=%s returned no URL", fmt)
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
        console.print(f"[yellow]Qobuz: no stream URL found for track {track_id}[/yellow]")
        return None, None

    async def __aenter__(self):
        await self.authenticate()
        # Set headers similar to Streamrip/qopy for better compatibility
        _headers = {
            # Match a common desktop UA like qobuz-dl/qopy does
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) " "Gecko/20100101 Firefox/83.0"
            ),
            "X-App-Id": str(self.app_id or ""),
        }
        if self.auth_token:
            _headers["X-User-Auth-Token"] = str(self.auth_token)
        # Bounded HTTP timeout to avoid hanging forever on bad formats/regions
        import os as _os

        try:
            _http_to = float(_os.getenv("FLA_QOBUZ_HTTP_TIMEOUT", "10") or "10")
        except Exception:
            _http_to = 10.0
        _timeout = aiohttp.ClientTimeout(total=_http_to)
        self.session = aiohttp.ClientSession(headers=_headers, timeout=_timeout)
        # Default: 8 requests/second unless overridden via env
        import os

        rps = self._rps if self._rps is not None else int(os.getenv("FLA_QOBUZ_RPS", "8") or "8")
        self._limiter = AsyncRateLimiter(rps, 1.0)
        self.api_client = _QobuzApiClient(
            self.app_id,
            self.app_secret,
            self.auth_token,
            self.session,
            self._limiter,
            app_secrets=self.app_secrets,
        )
        # Pre-select a working secret to avoid trying many per request
        try:
            await self.api_client.prime_secret()
        except Exception:
            pass
        # Calibrate working formats once to speed up fallbacks
        try:
            await self.api_client.calibrate_formats()
        except Exception:
            pass
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            self.session = None
        self.api_client = None
