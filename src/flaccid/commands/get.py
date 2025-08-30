"""
Download commands for FLACCID (`fla get`).

This module provides the primary download functionality, allowing users to fetch
tracks and albums from supported streaming services like Tidal and Qobuz.
"""

import asyncio
import re
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from ..core.config import get_settings
from ..core.database import get_db_connection
from ..plugins.qobuz import QobuzPlugin
from ..plugins.tidal import TidalPlugin

console = Console()


def _is_url(value: str) -> bool:
    """Check if the input looks like a URL."""
    return value.startswith(("http://", "https://")) or "." in value


async def _download_qobuz(
    album_id: Optional[str] = None,
    track_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
    artist_id: Optional[str] = None,
    quality: str = "max",
    output_dir: Optional[Path] = None,
    allow_mp3: bool = False,
    concurrency: int = 4,
    verify: bool = False,
    correlation_id: Optional[str] = None,
    qobuz_rps: Optional[int] = None,
    prefer_29: Optional[bool] = None,
    artist_limit: int = 50,
):
    """Internal function to download from Qobuz."""
    # Quality fallback for Qobuz: hires -> lossless -> mp3
    quality_fallback = ["hires", "lossless", "mp3"] if quality == "max" else [quality]

    try:
        async with QobuzPlugin(
            correlation_id=correlation_id, rps=qobuz_rps, prefer_29=prefer_29
        ) as plugin:
            # Helper: quick DB presence check by qobuz_id (track)
            def _in_db_track(tid: str) -> bool:
                try:
                    st = get_settings()
                    db_path = st.db_path or (st.library_path / "flaccid.db")
                    conn = get_db_connection(db_path)
                    row = conn.execute(
                        "SELECT 1 FROM tracks WHERE qobuz_id=? LIMIT 1", (tid,)
                    ).fetchone()
                    conn.close()
                    return row is not None
                except Exception:
                    return False

            for q in quality_fallback:
                try:
                    if album_id:
                        count = await plugin.download_album(
                            album_id,
                            q,
                            output_dir,
                            allow_mp3,
                            concurrency,
                            verify=verify,
                        )
                        if count > 0:
                            console.print(
                                f"[green]✅ Downloaded album in {q} quality[/green]"
                            )
                            return
                        if q != quality_fallback[-1]:
                            console.print(
                                f"[yellow]⚠️ No tracks downloaded in {q}, trying lower quality...[/yellow]"
                            )
                            continue
                        else:
                            raise RuntimeError("No downloadable tracks at any quality")
                    elif playlist_id:
                        count = await plugin.download_playlist(
                            playlist_id,
                            q,
                            output_dir,
                            allow_mp3,
                            concurrency,
                            verify=verify,
                            limit=artist_limit,
                        )
                        if count > 0:
                            console.print(
                                f"[green]✅ Downloaded playlist in {q} quality[/green]"
                            )
                            return
                        # No tracks found; try lower quality won't help, break
                        raise RuntimeError("Playlist contained no downloadable tracks")
                    elif artist_id:
                        count = await plugin.download_artist_top_tracks(
                            artist_id,
                            q,
                            output_dir,
                            limit=50,
                            allow_mp3=allow_mp3,
                            concurrency=concurrency,
                            verify=verify,
                        )
                        if count > 0:
                            console.print(
                                f"[green]✅ Downloaded artist top tracks in {q} quality[/green]"
                            )
                            return
                        raise RuntimeError("No downloadable top tracks for artist")
                    else:
                        # Track pre-check: fetch metadata to check by ISRC first, then provider ID
                        if track_id:
                            try:
                                td = await plugin.api_client.get_track(str(track_id))
                                isrc = (
                                    (td or {}).get("isrc")
                                    if isinstance(td, dict)
                                    else None
                                )
                                st = get_settings()
                                db_path = st.db_path or (st.library_path / "flaccid.db")
                                conn = get_db_connection(db_path)
                                try:
                                    if isrc:
                                        row = conn.execute(
                                            "SELECT 1 FROM tracks WHERE isrc=? LIMIT 1",
                                            (str(isrc),),
                                        ).fetchone()
                                        if row is not None:
                                            console.print(
                                                "[cyan]Already in library (by ISRC); skipping download[/cyan]"
                                            )
                                            conn.close()
                                            return
                                    # Fallback: provider-specific id
                                    row2 = conn.execute(
                                        "SELECT 1 FROM tracks WHERE qobuz_id=? LIMIT 1",
                                        (str(track_id),),
                                    ).fetchone()
                                    if row2 is not None:
                                        console.print(
                                            "[cyan]Already in library (by Qobuz ID); skipping download[/cyan]"
                                        )
                                        conn.close()
                                        return
                                finally:
                                    try:
                                        conn.close()
                                    except Exception:
                                        pass
                            except Exception:
                                # If metadata fetch fails, fall back to provider-id check
                                if track_id and _in_db_track(str(track_id)):
                                    console.print(
                                        "[cyan]Already in library; skipping download[/cyan]"
                                    )
                                    return
                        ok = await plugin.download_track(
                            track_id, q, output_dir, allow_mp3, verify=verify
                        )
                        if ok:
                            console.print(
                                f"[green]✅ Downloaded in {q} quality[/green]"
                            )
                            return
                        # not ok → try lower quality if available
                        if q != quality_fallback[-1]:
                            console.print(
                                f"[yellow]⚠️ {q} quality failed, trying lower quality...[/yellow]"
                            )
                            continue
                        else:
                            raise RuntimeError("No suitable format URL found")
                except Exception as e:
                    if q != quality_fallback[-1]:  # Not the last quality option
                        console.print(
                            f"[yellow]⚠️ {q} quality failed, trying lower quality...[/yellow]"
                        )
                        continue
                    else:
                        raise e
    except Exception as e:
        raise typer.Exit(f"[red]❌ Qobuz download failed:[/red] {e}")


async def _download_tidal(
    album_id: Optional[str] = None,
    track_id: Optional[str] = None,
    playlist_id: Optional[str] = None,
    artist_id: Optional[str] = None,
    quality: str = "max",
    output_dir: Optional[Path] = None,
    allow_mp3: bool = False,
    concurrency: int = 4,
    correlation_id: Optional[str] = None,
    tidal_rps: Optional[int] = None,
    verify: bool = False,
    artist_limit: int = 50,
):
    """Internal function to download from Tidal."""
    # Quality fallback for Tidal: hires -> lossless -> mp3
    quality_fallback = ["hires", "lossless", "mp3"] if quality == "max" else [quality]
    try:
        plugin = TidalPlugin(correlation_id=correlation_id, rps=tidal_rps)
        for q in quality_fallback:
            try:
                if album_id:
                    await plugin.download_album(
                        album_id, q, output_dir, concurrency=concurrency, verify=verify
                    )
                elif playlist_id:
                    await plugin.download_playlist(
                        playlist_id,
                        q,
                        output_dir,
                        concurrency=concurrency,
                        verify=verify,
                        limit=artist_limit,
                    )
                elif artist_id:
                    await plugin.download_artist_top_tracks(
                        artist_id,
                        q,
                        output_dir,
                        concurrency=concurrency,
                        verify=verify,
                        limit=artist_limit,
                    )
                else:
                    # Track pre-check: authenticate and fetch metadata to check ISRC/provider in DB
                    try:
                        await plugin.authenticate()
                    except Exception:
                        pass
                    try:
                        md = await plugin._get_track_metadata(str(track_id))
                    except Exception:
                        md = None
                    try:
                        st = get_settings()
                        db_path = st.db_path or (st.library_path / "flaccid.db")
                        conn = get_db_connection(db_path)
                        try:
                            isrc = (
                                (md or {}).get("isrc") if isinstance(md, dict) else None
                            )
                            if isrc:
                                row = conn.execute(
                                    "SELECT 1 FROM tracks WHERE isrc=? LIMIT 1",
                                    (str(isrc),),
                                ).fetchone()
                                if row is not None:
                                    console.print(
                                        "[cyan]Already in library (by ISRC); skipping download[/cyan]"
                                    )
                                    conn.close()
                                    return
                            row2 = conn.execute(
                                "SELECT 1 FROM tracks WHERE tidal_id=? LIMIT 1",
                                (str(track_id),),
                            ).fetchone()
                            if row2 is not None:
                                console.print(
                                    "[cyan]Already in library (by Tidal ID); skipping download[/cyan]"
                                )
                                conn.close()
                                return
                        finally:
                            try:
                                conn.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    await plugin.download_track(track_id, q, output_dir, verify=verify)
                console.print(f"[green]✅ Downloaded in {q} quality[/green]")
                return
            except Exception as e:
                if q != quality_fallback[-1]:  # Not the last quality option
                    console.print(
                        f"[yellow]⚠️ {q} quality failed, trying lower quality...[/yellow]"
                    )
                    continue
                else:
                    raise e
    except Exception as e:
        raise typer.Exit(f"[red]❌ Tidal download failed:[/red] {e}")


async def _download_from_url(
    url: str,
    output_dir: Path,
    allow_mp3: bool = False,
    correlation_id: Optional[str] = None,
    qobuz_rps: Optional[int] = None,
    tidal_rps: Optional[int] = None,
    verify: bool = False,
    prefer_29: Optional[bool] = None,
    concurrency: int = 4,
):
    """Auto-detect service from URL and download."""
    console.print(f"🔍 Detecting service from URL: [blue]{url}[/blue]")

    tidal_match = re.search(
        r"tidal\.com/(browse/)?(track|album|playlist|artist)/([\w-]+)", url
    )
    if tidal_match:
        media_type, media_id = tidal_match.group(2), tidal_match.group(3)
        console.print(f"Detected Tidal {media_type} with ID: {media_id}")
        if media_type == "track":
            await _download_tidal(
                track_id=media_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                tidal_rps=tidal_rps,
            )
        elif media_type == "album":
            await _download_tidal(
                album_id=media_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                tidal_rps=tidal_rps,
            )
        elif media_type == "playlist":
            await _download_tidal(
                playlist_id=media_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                tidal_rps=tidal_rps,
                concurrency=concurrency,
                verify=verify,
            )
        else:
            await _download_tidal(
                artist_id=media_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                tidal_rps=tidal_rps,
                concurrency=concurrency,
                verify=verify,
            )
        return

    # Support qobuz album/track/playlist URLs including open.qobuz.com and locale paths
    qobuz_match = re.search(
        r"qobuz\.com/(?:[a-z]{2}-[a-z]{2}/)?(album|track|playlist|artist)/([^?#]+)", url
    )
    if qobuz_match:
        media_type, media_tail = qobuz_match.group(1), qobuz_match.group(2)
        # Take last path segment as the canonical id (handles slug/id and id-only)
        final_id = media_tail.split("/")[-1]
        console.print(f"Detected Qobuz {media_type} with ID: {final_id}")
        if media_type == "track":
            await _download_qobuz(
                track_id=final_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                qobuz_rps=qobuz_rps,
                prefer_29=prefer_29,
            )
        elif media_type == "album":
            await _download_qobuz(
                album_id=final_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                qobuz_rps=qobuz_rps,
                prefer_29=prefer_29,
                concurrency=concurrency,
            )
        elif media_type == "playlist":
            await _download_qobuz(
                playlist_id=final_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                qobuz_rps=qobuz_rps,
                prefer_29=prefer_29,
                concurrency=concurrency,
            )
        else:  # artist
            await _download_qobuz(
                artist_id=final_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                qobuz_rps=qobuz_rps,
                prefer_29=prefer_29,
                concurrency=concurrency,
            )
        return

    console.print("[red]❌ Unsupported or invalid URL.[/red]")
    raise typer.Exit(1)


async def get_main(
    input_value: str,
    qobuz_id: Optional[str],
    tidal_id: Optional[str],
    track: bool,
    album: bool,
    playlist: bool,
    artist: bool,
    allow_mp3: bool = False,
    dry_run: bool = False,
    concurrency: int = 4,
    correlation_id: Optional[str] = None,
    qobuz_rps: Optional[int] = None,
    tidal_rps: Optional[int] = None,
    verify: bool = False,
    try_29: bool = False,
    artist_limit: int = 50,
):
    """Internal function to handle the main download logic."""
    settings = get_settings()
    output_dir = settings.download_path.resolve()

    # Validate mutually-exclusive content-type flags
    selected_types = sum(bool(x) for x in (track, album, playlist, artist))
    if selected_types > 1:
        console.print(
            "[red]Error:[/red] Only one of --track, --album, --playlist or"
            " --artist may be specified."
        )
        raise typer.Exit(1)

    # If it's a URL, auto-detect and download
    if _is_url(input_value):
        if dry_run:
            console.print(
                f"[cyan]Dry-run:[/cyan] Would download from URL: {input_value}"
            )
        else:
            await _download_from_url(
                input_value,
                output_dir,
                allow_mp3,
                correlation_id,
                qobuz_rps,
                tidal_rps,
                verify,
                prefer_29=try_29,
                concurrency=concurrency,
            )
            return

    # Handle service-specific IDs
    if qobuz_id:
        if dry_run:
            console.print(
                f"[cyan]Dry-run:[/cyan] Would download Qobuz {'album' if album else ('playlist' if playlist else ('artist' if artist else 'track'))} {qobuz_id}"
            )
            return
        else:
            if album:
                await _download_qobuz(
                    album_id=qobuz_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    concurrency=concurrency,
                    correlation_id=correlation_id,
                    qobuz_rps=qobuz_rps,
                    verify=verify,
                    prefer_29=try_29,
                    artist_limit=artist_limit,
                )
            elif playlist:
                await _download_qobuz(
                    playlist_id=qobuz_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    concurrency=concurrency,
                    correlation_id=correlation_id,
                    qobuz_rps=qobuz_rps,
                    verify=verify,
                    prefer_29=try_29,
                    artist_limit=artist_limit,
                )
            elif artist:
                await _download_qobuz(
                    artist_id=qobuz_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    concurrency=concurrency,
                    correlation_id=correlation_id,
                    qobuz_rps=qobuz_rps,
                    verify=verify,
                    prefer_29=try_29,
                    artist_limit=artist_limit,
                )
            else:
                # Default to track if no explicit type provided
                await _download_qobuz(
                    track_id=qobuz_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    correlation_id=correlation_id,
                    qobuz_rps=qobuz_rps,
                    verify=verify,
                    prefer_29=try_29,
                    artist_limit=artist_limit,
                )
            return

    if tidal_id:
        if dry_run:
            console.print(
                f"[cyan]Dry-run:[/cyan] Would download Tidal {'album' if album else ('playlist' if playlist else ('artist' if artist else 'track'))} {tidal_id}"
            )
            return
        else:
            if album:
                await _download_tidal(
                    album_id=tidal_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    concurrency=concurrency,
                    correlation_id=correlation_id,
                    tidal_rps=tidal_rps,
                    verify=verify,
                    artist_limit=artist_limit,
                )
            elif playlist:
                await _download_tidal(
                    playlist_id=tidal_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    concurrency=concurrency,
                    correlation_id=correlation_id,
                    tidal_rps=tidal_rps,
                    verify=verify,
                    artist_limit=artist_limit,
                )
            elif playlist:
                await _download_tidal(
                    playlist_id=tidal_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    concurrency=concurrency,
                    correlation_id=correlation_id,
                    tidal_rps=tidal_rps,
                    verify=verify,
                    artist_limit=artist_limit,
                )
            elif artist:
                await _download_tidal(
                    artist_id=tidal_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    concurrency=concurrency,
                    correlation_id=correlation_id,
                    tidal_rps=tidal_rps,
                    verify=verify,
                    artist_limit=artist_limit,
                )
            else:
                # Default to track if no explicit type provided
                await _download_tidal(
                    track_id=tidal_id,
                    quality="max",
                    output_dir=output_dir,
                    allow_mp3=allow_mp3,
                    correlation_id=correlation_id,
                    tidal_rps=tidal_rps,
                    verify=verify,
                    artist_limit=artist_limit,
                )
            return

    # If no service flags but we have an input_value, try to guess
    if input_value:
        # Check if it looks like a numeric ID (common for both services)
        if input_value.isdigit():
            console.print(
                "[red]Error:[/red] Numeric ID provided but no service specified. "
                "Use -q for Qobuz or -t for Tidal."
            )
            raise typer.Exit(1)
        else:
            # Maybe it's a URL without http://
            try:
                if dry_run:
                    console.print(
                        f"[cyan]Dry-run:[/cyan] Would download from URL: https://{input_value}"
                    )
                else:
                    await _download_from_url(
                        "https://" + input_value,
                        output_dir,
                        allow_mp3,
                        correlation_id,
                        qobuz_rps,
                        tidal_rps,
                        prefer_29=try_29,
                        concurrency=concurrency,
                    )
                return
            except Exception:
                pass

    console.print(
        "[red]Error:[/red] Please provide a URL or use -q/--qobuz or -t/--tidal with an ID."
    )
    raise typer.Exit(1)


app = typer.Typer(
    no_args_is_help=True,
    help="🚀 Download tracks or albums from supported services.",
)


def _normalize_quality(q: Optional[str]) -> str:
    if not q:
        return "max"
    s = q.strip().lower()
    if s in {"4", "max", "best", "hires", "hi-res", "hi_res"}:
        return "max"
    if s in {"3"}:
        return "hires"
    if s in {"2", "lossless", "flac"}:
        return "lossless"
    if s in {"1", "mp3", "320"}:
        return "mp3"
    return s


@app.command("qobuz")
def get_qobuz(
    album_id: Optional[str] = typer.Option(
        None, "--album-id", help="Qobuz album ID to download"
    ),
    track_id: Optional[str] = typer.Option(
        None, "--track-id", help="Qobuz track ID to download"
    ),
    quality: Optional[str] = typer.Option(
        "max", "--quality", "-q", help="Quality: max|hires|lossless|mp3|1-4"
    ),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o", help="Output directory (defaults to download path)"
    ),
    allow_mp3: bool = typer.Option(
        False, "--allow-mp3", help="Permit MP3 fallback if FLAC unavailable"
    ),
    concurrency: int = typer.Option(
        4, "--concurrency", help="Max concurrent downloads for album tasks"
    ),
    verify: bool = typer.Option(
        False, "--verify", help="Run ffprobe to verify outputs"
    ),
    qobuz_rps: Optional[int] = typer.Option(
        None, "--qobuz-rps", help="Qobuz API rate limit (requests per second)"
    ),
    try_29: bool = typer.Option(
        False,
        "--try-29",
        "-29",
        help="Try Qobuz format 29 before 27 (default skips 29)",
    ),
):
    """Download from Qobuz by album or track ID (Toolkit-style)."""
    if not album_id and not track_id:
        raise typer.Exit("Specify either --album-id or --track-id")
    settings = get_settings()
    dst = (out or settings.download_path).resolve()
    q = _normalize_quality(quality)
    import uuid as _uuid

    if album_id:
        asyncio.run(
            _download_qobuz(
                album_id=album_id,
                quality=q,
                output_dir=dst,
                allow_mp3=allow_mp3,
                concurrency=concurrency,
                correlation_id=_uuid.uuid4().hex,
                qobuz_rps=qobuz_rps,
                verify=verify,
                prefer_29=try_29,
            )
        )
    else:
        asyncio.run(
            _download_qobuz(
                track_id=track_id,
                quality=q,
                output_dir=dst,
                allow_mp3=allow_mp3,
                correlation_id=_uuid.uuid4().hex,
                qobuz_rps=qobuz_rps,
                verify=verify,
                prefer_29=try_29,
            )
        )


@app.command("tidal")
def get_tidal(
    album_id: Optional[str] = typer.Option(
        None, "--album-id", help="Tidal album ID to download"
    ),
    track_id: Optional[str] = typer.Option(
        None, "--track-id", help="Tidal track ID to download"
    ),
    quality: Optional[str] = typer.Option(
        "max", "--quality", "-q", help="Quality: max|hires|lossless|mp3"
    ),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o", help="Output directory (defaults to download path)"
    ),
    concurrency: int = typer.Option(
        4, "--concurrency", help="Max concurrent downloads for album tasks"
    ),
    verify: bool = typer.Option(
        False, "--verify", help="Run ffprobe to verify outputs"
    ),
    tidal_rps: Optional[int] = typer.Option(
        None, "--tidal-rps", help="Tidal API rate limit (requests per second)"
    ),
):
    """Download from Tidal by album or track ID (Toolkit-style)."""
    if not album_id and not track_id:
        raise typer.Exit("Specify either --album-id or --track-id")
    settings = get_settings()
    dst = (out or settings.download_path).resolve()
    q = _normalize_quality(quality)
    import uuid as _uuid

    if album_id:
        asyncio.run(
            _download_tidal(
                album_id=album_id,
                quality=q,
                output_dir=dst,
                concurrency=concurrency,
                correlation_id=_uuid.uuid4().hex,
                tidal_rps=tidal_rps,
                verify=verify,
            )
        )
    else:
        asyncio.run(
            _download_tidal(
                track_id=track_id,
                quality=q,
                output_dir=dst,
                correlation_id=_uuid.uuid4().hex,
                tidal_rps=tidal_rps,
                verify=verify,
            )
        )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    input_value: Optional[str] = typer.Argument(
        None, help="URL, or use with -q/-t flags for service-specific IDs"
    ),
    qobuz_id: Optional[str] = typer.Option(
        None, "-q", "--qobuz", help="Qobuz track/album ID"
    ),
    tidal_id: Optional[str] = typer.Option(
        None, "-t", "--tidal", help="Tidal track/album ID"
    ),
    track: bool = typer.Option(
        False,
        "--track",
        help="Treat ID/URL as track",
    ),
    album: bool = typer.Option(
        False,
        "--album",
        "-a",
        help="Treat ID/URL as album",
    ),
    playlist: bool = typer.Option(
        False,
        "--playlist",
        help="Treat ID/URL as playlist",
    ),
    artist: bool = typer.Option(
        False,
        "--artist",
        help="Treat ID/URL as artist",
    ),
    artist_limit: int = typer.Option(
        50,
        "--limit",
        help="For --artist, maximum number of top tracks to download",
    ),
    allow_mp3: bool = typer.Option(
        False,
        "--allow-mp3",
        help="Allow MP3 (lossy) fallbacks when no FLAC is available.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview download actions without downloading"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output a summary JSON after completion"
    ),
    concurrency: int = typer.Option(
        4, "--concurrency", help="Max concurrent downloads for album tasks"
    ),
    verify: bool = typer.Option(
        False,
        "--verify",
        help="Run ffprobe on output to verify codec, duration, and container.",
    ),
    qobuz_rps: Optional[int] = typer.Option(
        None, "--qobuz-rps", help="Qobuz API rate limit (requests per second)"
    ),
    tidal_rps: Optional[int] = typer.Option(
        None, "--tidal-rps", help="Tidal API rate limit (requests per second)"
    ),
    try_29: bool = typer.Option(
        False,
        "--try-29",
        "-29",
        help="Try Qobuz format 29 before 27 (default skips 29)",
    ),
):
    """
    🚀 Download tracks or albums from supported services.

    Examples:
      fla get https://tidal.com/album/12345         # Auto-detect from URL
      fla get -q 12345                            # Qobuz track ID
      fla get -q 12345 -a                         # Qobuz album ID
      fla get -t 12345                            # Tidal track ID
      fla get -t 12345 --album                    # Tidal album ID
    """
    # If no arguments provided, show help
    if not input_value and not qobuz_id and not tidal_id:
        console.print(ctx.get_help())
        raise typer.Exit(0)

    # Run the async function
    import uuid as _uuid

    corr = _uuid.uuid4().hex
    asyncio.run(
        get_main(
            input_value or "",
            qobuz_id,
            tidal_id,
            track,
            album,
            playlist,
            artist,
            allow_mp3,
            dry_run,
            concurrency,
            corr,
            qobuz_rps,
            tidal_rps,
            verify,
            try_29,
        )
    )
    if json_output:
        result = {
            "input": input_value or qobuz_id or tidal_id,
            "service": (
                "qobuz"
                if qobuz_id or (input_value or "").find("qobuz") != -1
                else (
                    "tidal"
                    if tidal_id or (input_value or "").find("tidal") != -1
                    else None
                )
            ),
            "mode": "album" if album else ("track" if track else None),
            "allow_mp3": allow_mp3,
            "status": "ok",
            "corr": corr,
        }
        import json as _json

        typer.echo(_json.dumps(result))
