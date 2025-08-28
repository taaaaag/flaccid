# FLACCID CLI Toolkit Developer Handbook

## Introduction

FLACCID is a modular command-line toolkit for managing FLAC audio libraries and integrating with music services. It provides:

- Flexible CLI: a single `fla` command with subcommands for download, tagging, library management, and settings (Typer-based).
- Modular plugins: Qobuz (working), Apple (metadata), Tidal (experimental stub), and lyrics provider.
- Rich metadata tagging: Mutagen-based FLAC tagging with album art and optional lyrics.
- Efficient downloads: aiohttp-based async downloads with Rich progress.
- Robust configuration: Dynaconf + Pydantic; secrets via Keyring or `.secrets.toml`.
- Library indexing: SQLite (SQLAlchemy) library with scan, index, and optional Watchdog.
- Testing: Pytest-friendly architecture and examples.

Security note: Do not commit secrets (API keys, tokens, passwords) to the repository. Store credentials in the OS keychain (via `keyring`) or a local, gitignored `.secrets.toml`.

---

## CLI Architecture Overview

The CLI is accessed via `fla` and organized into grouped subcommands:

- `fla get ...`: download music from providers (e.g., Qobuz)
- `fla tag ...`: tag local FLAC files from online metadata (Qobuz, Apple)
- `fla lib ...`: scan and index a local library (with optional watch)
- `fla config ...`: configure credentials, paths, and view settings
- `fla playlist ...`: playlist matching tools (if enabled)

Examples:

- Download a Qobuz album: `fla get qobuz --album-id 123456 --quality lossless --out ~/Music/Downloads`
- Tag from Qobuz metadata: `fla tag qobuz --album-id 123456 "/path/to/AlbumFolder"`
- Tag from Apple search: `fla tag apple "Artist - Album" "/path/to/AlbumFolder"`
- Scan library: `fla lib scan` (add `--watch` to continuously monitor)
- Re-index library: `fla lib index --verify`
- Authenticate Qobuz: `fla config auto-qobuz`
- Set library path: `fla config path --library ~/Music`
- Show current config (JSON): `fla config show --json`

Typer nested subcommands: https://typer.tiangolo.com/tutorial/subcommands/nested-subcommands/

---

## Project Structure

```
flaccid/
├── __init__.py
├── cli.py               # Typer entry point
├── commands/
│   ├── get.py           # 'fla get' (Qobuz, Tidal experimental)
│   ├── tag.py           # 'fla tag' (Qobuz, Apple)
│   ├── lib.py           # 'fla lib' (scan/index)
│   └── settings.py      # 'fla set' (auth/path)
├── plugins/
│   ├── base.py          # Plugin interfaces and metadata models
│   ├── qobuz.py         # Qobuz implementation (auth/metadata/download)
│   ├── tidal.py         # Tidal (experimental)
│   ├── apple.py         # Apple metadata-only
│   └── lyrics.py        # Lyrics provider example
├── core/
│   ├── config.py        # Dynaconf + Pydantic config
│   ├── metadata.py      # Tagging cascade (Mutagen)
│   ├── downloader.py    # Download helpers (aiohttp + Rich)
│   ├── library.py       # Scan/watch/index
│   └── database.py      # SQLAlchemy models and helpers
├── tests/
├── pyproject.toml
└── README.md
```

---

## CLI Entry Point and Subcommand Wiring

```python
# flaccid/cli.py

import typer
from flaccid.commands import config, get, lib, playlist, tag

app = typer.Typer(help="FLACCID CLI - A modular FLAC toolkit")

app.add_typer(config.app, name="config", help="Manage authentication, paths, and settings")
app.add_typer(get.app, name="get", help="Download from providers")
app.add_typer(lib.app, name="lib", help="Manage local music library")
app.add_typer(playlist.app, name="playlist", help="Playlist matching and export")
app.add_typer(tag.app, name="tag", help="Tag local files from metadata")

if __name__ == "__main__":
    app()
```

---

## Download Commands: Qobuz and Tidal (experimental)

```python
# flaccid/commands/get.py

import asyncio
from pathlib import Path
import typer
from flaccid.core import config
from flaccid.plugins import qobuz, tidal

app = typer.Typer()

@app.command("qobuz")
def get_qobuz(
    album_id: str = typer.Option(None, "--album-id", help="Qobuz album ID"),
    track_id: str = typer.Option(None, "--track-id", help="Qobuz track ID"),
    quality: str = typer.Option("lossless", "--quality", "-q", help="lossless|hi-res"),
    output: Path = typer.Option(None, "--out", "-o", help="Output directory"),
):
    """Download an album or track from Qobuz."""
    if not album_id and not track_id:
        typer.echo("Error: Specify either --album-id or --track-id", err=True)
        raise typer.Exit(code=1)

    dest_dir = output or Path(config.settings.library_path).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)

    qbz = qobuz.QobuzPlugin()
    asyncio.run(qbz.authenticate())  # async auth

    if album_id:
        album_meta = asyncio.run(qbz.get_album_metadata(album_id))
        tracks = album_meta.tracks
    else:
        track_meta = asyncio.run(qbz.get_track_metadata(track_id))
        tracks = [track_meta]

    asyncio.run(qbz.download_tracks(tracks, dest_dir, quality))
    typer.secho("Qobuz download complete!", fg=typer.colors.GREEN)


@app.command("tidal")
def get_tidal(
    album_id: str = typer.Option(None, "--album-id", help="Tidal album ID"),
    track_id: str = typer.Option(None, "--track-id", help="Tidal track ID"),
    quality: str = typer.Option("lossless", "--quality", "-q", help="lossless|hi-res"),
    output: Path = typer.Option(None, "--out", "-o", help="Output directory"),
):
    """Download from Tidal (experimental, not implemented)."""
    typer.secho("Tidal support is experimental and not yet implemented.", fg=typer.colors.YELLOW)
    raise typer.Exit(code=2)
```

Notes:
- Tidal is explicitly marked experimental to avoid implying full support.
- Qobuz `authenticate()` is async and invoked via `asyncio.run(...)`.

---

## Plugin Interfaces and Models

```python
# flaccid/plugins/base.py

from abc import ABC, abstractmethod
from typing import List, Optional

class TrackMetadata:
    def __init__(
        self,
        id: str,
        title: str,
        artist: str,
        album: str,
        track_number: int,
        disc_number: int = 1,
        duration: float = 0.0,
        download_url: Optional[str] = None,
    ):
        self.id = id
        self.title = title
        self.artist = artist
        self.album = album
        self.track_number = track_number
        self.disc_number = disc_number
        self.duration = duration
        self.download_url = download_url

class AlbumMetadata:
    def __init__(
        self,
        id: str,
        title: str,
        artist: str,
        year: int = 0,
        cover_url: Optional[str] = None,
        tracks: Optional[List[TrackMetadata]] = None,
    ):
        self.id = id
        self.title = title
        self.artist = artist
        self.year = year
        self.cover_url = cover_url
        self.tracks = tracks or []

class MusicServicePlugin(ABC):
    @abstractmethod
    async def authenticate(self) -> None: ...

    @abstractmethod
    async def get_album_metadata(self, album_id: str) -> AlbumMetadata: ...

    @abstractmethod
    async def get_track_metadata(self, track_id: str) -> TrackMetadata: ...

    @abstractmethod
    async def download_tracks(self, tracks: List[TrackMetadata], dest_dir, quality: str) -> None: ...
```

---

## Qobuz Plugin (async auth, timeouts, filename sanitization)

```python
# flaccid/plugins/qobuz.py

import asyncio
import os
from pathlib import Path
from typing import List

import aiohttp
import typer

from flaccid.plugins.base import MusicServicePlugin, AlbumMetadata, TrackMetadata
from flaccid.core import config

def sanitize_filename(name: str, replacement: str = "-") -> str:
    # Cross-platform invalid characters
    invalid = '<>:"/\\|?*\n\r\t'
    return "".join((c if c not in invalid else replacement) for c in name).strip()

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=10, sock_read=60)

class QobuzPlugin(MusicServicePlugin):
    def __init__(self) -> None:
        self.app_id = config.settings.qobuz.get("app_id", "")
        self.username = config.settings.qobuz.get("username", "")
        self._auth_token: str | None = None

    async def authenticate(self) -> None:
        import keyring
        password = keyring.get_password("flaccid_qobuz", self.username)
        if not password or not self.app_id:
            raise RuntimeError("Qobuz credentials or app ID not set. Run 'fla set auth qobuz'.")
        url = "https://www.qobuz.com/api.json/0.2/user/login"
        params = {"username": self.username, "password": password, "app_id": self.app_id}
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
        token = data.get("user_auth_token")
        if not token:
            raise RuntimeError("Failed to authenticate with Qobuz. Check credentials.")
        self._auth_token = token

    async def get_album_metadata(self, album_id: str) -> AlbumMetadata:
        url = "https://www.qobuz.com/api.json/0.2/album/get"
        params = {"album_id": album_id, "user_auth_token": self._auth_token}
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
        album = data["album"]
        tracks = [
            TrackMetadata(
                id=str(t["id"]),
                title=t["title"],
                artist=t["performer"]["name"],
                album=album["title"],
                track_number=t.get("trackNumber", 0),
                disc_number=t.get("mediaNumber", 1),
                duration=float(t.get("duration", 0.0)),
            )
            for t in data["tracks"]["items"]
        ]
        return AlbumMetadata(
            id=str(album["id"]),
            title=album["title"],
            artist=album["artist"]["name"],
            year=int(album.get("releaseDateDigital", "0")[:4]) if album.get("releaseDateDigital") else 0,
            cover_url=album.get("image"),
            tracks=tracks,
        )

    async def get_track_metadata(self, track_id: str) -> TrackMetadata:
        url = "https://www.qobuz.com/api.json/0.2/track/get"
        params = {"track_id": track_id, "user_auth_token": self._auth_token}
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
        tr = data["track"]
        return TrackMetadata(
            id=str(tr["id"]),
            title=tr["title"],
            artist=tr["performer"]["name"],
            album=tr["album"]["title"],
            track_number=tr.get("trackNumber", 0),
            disc_number=tr.get("mediaNumber", 1),
            duration=float(tr.get("duration", 0.0)),
        )

    async def download_tracks(self, tracks: List[TrackMetadata], dest_dir: Path, quality: str) -> None:
        # Map desired quality to Qobuz format_id (example: 6=FLAC16, 27=FLAC24)
        format_id = 27 if quality.lower() in ("hi-res", "hires", "hi_res") else 6
        file_url_api = "https://www.qobuz.com/api.json/0.2/track/getFileUrl"

        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            tasks: list[asyncio.Task] = []
            for track in tracks:
                params = {
                    "track_id": track.id,
                    "format_id": format_id,
                    "user_auth_token": self._auth_token,
                    "app_id": self.app_id,
                }
                async with session.get(file_url_api, params=params) as resp:
                    resp.raise_for_status()
                    file_data = await resp.json()
                url = file_data.get("url")
                if not url:
                    typer.secho(f"No download URL for {track.title}", fg=typer.colors.RED)
                    continue
                track.download_url = url
                filename = f"{track.track_number:02d} - {sanitize_filename(track.title)}.flac"
                filepath = str(Path(dest_dir) / filename)
                tasks.append(asyncio.create_task(download_file(session, url, filepath)))
            if tasks:
                await asyncio.gather(*tasks)

# Import after definition to avoid circular import in docs snippet
from flaccid.core.downloader import download_file  # noqa: E402
```

Key changes (addresses issues 4, 5, 7, 8, 9, 10):
- `authenticate()` is async, uses `ClientSession` with timeouts, and validates response.
- Added missing imports (`typer`, `os` where needed).
- Introduced `sanitize_filename` for cross-platform-safe file names.
- Explicitly mark Tidal as experimental in the CLI.
- Use robust error handling with `raise_for_status()`.

---

## Downloader: Progress, Timeouts, Concurrent Tasks

```python
# flaccid/core/downloader.py

import aiohttp
from rich.progress import Progress, BarColumn, DownloadColumn, TimeRemainingColumn, TextColumn

async def download_file(session: aiohttp.ClientSession, url: str, dest_path: str) -> None:
    async with session.get(url) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.1f}%",
            DownloadColumn(),
            TimeRemainingColumn(),
            transient=True,
        ) as progress:
            task_id = progress.add_task(f"Downloading", total=total or None)
            with open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    if chunk:
                        f.write(chunk)
                        if total:
                            progress.update(task_id, advance=len(chunk))
            if total:
                progress.update(task_id, completed=total)
```

Notes:
- Uses a context-managed Progress to avoid flicker and ensure clean teardown.
- Honors Content-Length if present.

---

## Apple Metadata Plugin: Timeouts and Error Handling

```python
# flaccid/plugins/apple.py

from typing import Optional
import requests
from requests import RequestException

from flaccid.plugins.base import MetadataProviderPlugin, AlbumMetadata, TrackMetadata

TIMEOUT = (5, 30)  # connect, read

class AppleMusicPlugin(MetadataProviderPlugin):
    def __init__(self) -> None:
        pass  # Public iTunes endpoints don't require tokens for basic search

    def search_album(self, query: str) -> Optional[AlbumMetadata]:
        try:
            resp = requests.get("https://itunes.apple.com/search", params={"term": query, "entity": "album", "limit": 1}, timeout=TIMEOUT)
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except (RequestException, ValueError):
            return None
        if not results:
            return None
        return self.get_album_metadata(str(results[0].get("collectionId")))

    def get_album_metadata(self, album_id: str) -> Optional[AlbumMetadata]:
        try:
            resp = requests.get(f"https://itunes.apple.com/lookup?id={album_id}&entity=song", timeout=TIMEOUT)
            resp.raise_for_status()
            items = resp.json().get("results", [])
        except (RequestException, ValueError):
            return None
        if len(items) < 2:
            return None
        album_info = items[0]
        album = AlbumMetadata(
            id=str(album_info.get("collectionId")),
            title=album_info.get("collectionName", ""),
            artist=album_info.get("artistName", ""),
            year=int(album_info.get("releaseDate", "0")[:4]) if album_info.get("releaseDate") else 0,
            cover_url=album_info.get("artworkUrl100"),
        )
        tracks: list[TrackMetadata] = []
        for item in items[1:]:
            if item.get("wrapperType") == "track":
                tracks.append(
                    TrackMetadata(
                        id=str(item.get("trackId")),
                        title=item.get("trackName", ""),
                        artist=item.get("artistName", ""),
                        album=album.title,
                        track_number=int(item.get("trackNumber", 0) or 0),
                        disc_number=int(item.get("discNumber", 1) or 1),
                        duration=float(item.get("trackTimeMillis", 0) or 0) / 1000.0,
                    )
                )
        album.tracks = tracks
        return album
```

---

## Tagging Cascade (Mutagen)

```python
# flaccid/core/metadata.py (excerpt)

from mutagen.flac import FLAC, Picture
import requests

def apply_album_metadata(folder_path: str, album_meta) -> None:
    import glob, os
    flac_files = sorted(glob.glob(os.path.join(folder_path, "*.flac")))
    tracks = sorted(album_meta.tracks, key=lambda t: (t.disc_number, t.track_number))
    cover_data = None
    if getattr(album_meta, "cover_url", None):
        try:
            r = requests.get(album_meta.cover_url, timeout=(5, 30))
            r.raise_for_status()
            cover_data = r.content
        except Exception:
            cover_data = None
    for i, file_path in enumerate(flac_files):
        audio = FLAC(file_path)
        if i < len(tracks):
            t = tracks[i]
            audio["title"] = t.title
            audio["artist"] = t.artist
            audio["album"] = t.album or album_meta.title
            audio["albumartist"] = album_meta.artist
            audio["tracknumber"] = str(t.track_number)
            audio["discnumber"] = str(t.disc_number)
            if getattr(album_meta, "year", 0):
                audio["date"] = str(album_meta.year)
            if cover_data:
                audio.clear_pictures()
                pic = Picture(); pic.type = 3; pic.desc = "Cover"; pic.mime = "image/jpeg"; pic.data = cover_data
                audio.add_picture(pic)
        audio.save()
```

---

## Library Scanning and Indexing (notes)

- Use SQLAlchemy sessions per thread or queue FS events to a single writer to avoid SQLite locks.
- Prefer a user data directory for the DB path (see `platformdirs.user_data_dir("flaccid")`).
- Verify FLACs only when `--verify` is set due to performance.

---

## Configuration and Secrets Guidance

- Use Dynaconf for layered configuration and Pydantic for validation.
- Environment overrides: `FLA_*` prefix (e.g., `FLA_LIBRARY_PATH`).
- Secrets (passwords, tokens, app secrets):
  - Prefer OS keychain via `keyring` (e.g., `flaccid_qobuz`), or
  - `.secrets.toml` stored outside version control (ensure `.gitignore` excludes it).
- Do not store plaintext secrets in `settings.toml`.

Example (auth setup):

```bash
fla config auto-qobuz
# guides you through authentication and stores tokens/IDs securely
```

---

## Quality Flags and Provider Mapping

- Canonical CLI values: `--quality lossless` or `--quality hi-res`.
- Provider mapping (Qobuz example): `lossless -> format_id=6`, `hi-res -> format_id=27`.
- Document provider-specific nuances near each plugin.

---

## Testing Notes

- Use Pytest fixtures and `typer.testing.CliRunner` for CLI tests.
- Mock network with `responses` (requests) or `aiohttp` test utilities; assert retries/backoff where implemented.
- Provide small FLAC test assets for Mutagen tagging tests.

---

## Status of Providers

- Qobuz: implemented for metadata and downloads.
- Apple: metadata-only.
- Tidal: experimental (not implemented). The CLI subcommand exits with code 2 and a warning.

---

This handbook has been cleaned of duplicate content and stray artifacts, and updated to reflect secure practices, robust async usage, and consistent CLI naming. 