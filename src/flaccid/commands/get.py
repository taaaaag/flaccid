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
from ..plugins.qobuz import QobuzPlugin
from ..plugins.tidal import TidalPlugin

console = Console()


def _is_url(value: str) -> bool:
    """Check if the input looks like a URL."""
    return value.startswith(("http://", "https://")) or "." in value


async def _download_qobuz(
    album_id: Optional[str] = None,
    track_id: Optional[str] = None,
    quality: str = "max",
    output_dir: Optional[Path] = None,
    allow_mp3: bool = False,
    concurrency: int = 4,
    verify: bool = False,
    correlation_id: Optional[str] = None,
    qobuz_rps: Optional[int] = None,
):
    """Internal function to download from Qobuz."""
    # Quality fallback for Qobuz: hires -> lossless -> mp3
    quality_fallback = ["hires", "lossless", "mp3"] if quality == "max" else [quality]

    try:
        async with QobuzPlugin(correlation_id=correlation_id, rps=qobuz_rps) as plugin:
            for q in quality_fallback:
                try:
                    if album_id:
                        await plugin.download_album(
                            album_id, q, output_dir, allow_mp3, concurrency, verify=verify
                        )
                    else:
                        await plugin.download_track(track_id, q, output_dir, allow_mp3, verify=verify)
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
        raise typer.Exit(f"[red]❌ Qobuz download failed:[/red] {e}")


async def _download_tidal(
    album_id: Optional[str] = None,
    track_id: Optional[str] = None,
    quality: str = "max",
    output_dir: Optional[Path] = None,
    allow_mp3: bool = False,
    concurrency: int = 4,
    correlation_id: Optional[str] = None,
    tidal_rps: Optional[int] = None,
    verify: bool = False,
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
                else:
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
):
    """Auto-detect service from URL and download."""
    console.print(f"🔍 Detecting service from URL: [blue]{url}[/blue]")

    tidal_match = re.search(r"tidal.com/(browse/)?(track|album)/(\d+)", url)
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
        else:
            await _download_tidal(
                album_id=media_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                tidal_rps=tidal_rps,
            )
        return

    qobuz_match = re.search(
        r"qobuz.com/([a-z]{2}-[a-z]{2})/(album|track)/([\w\d-]+)", url
    )
    if qobuz_match:
        media_type, media_id = qobuz_match.group(2), qobuz_match.group(3)
        # Qobuz IDs are often at the end of a slug, so we take the last part
        final_id = media_id.split("/")[-1]
        console.print(f"Detected Qobuz {media_type} with ID: {final_id}")
        if media_type == "track":
            await _download_qobuz(
                track_id=final_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                qobuz_rps=qobuz_rps,
            )
        else:
            await _download_qobuz(
                album_id=final_id,
                quality="max",
                output_dir=output_dir,
                allow_mp3=allow_mp3,
                correlation_id=correlation_id,
                qobuz_rps=qobuz_rps,
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
            )
            return

    # Handle service-specific IDs
    if qobuz_id:
        if dry_run:
            console.print(
                f"[cyan]Dry-run:[/cyan] Would download Qobuz {'album' if album else 'track'} {qobuz_id}"
            )
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
                )
            return

    if tidal_id:
        if dry_run:
            console.print(
                f"[cyan]Dry-run:[/cyan] Would download Tidal {'album' if album else 'track'} {tidal_id}"
            )
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
