"""
Diagnostics commands for FLACCID (`fla diag`).

Quick checks to validate provider/API health and local tooling.
"""

import asyncio
from typing import Optional
import json

import typer
from rich.console import Console

from ..plugins.qobuz import QobuzPlugin
from ..plugins.tidal import TidalPlugin

console = Console()
app = typer.Typer(no_args_is_help=True, help="Run diagnostics for providers and tools.")


@app.command("qobuz-status")
def diag_qobuz_status(
    track_id: str = typer.Option(
        "168662534", "--track-id", help="Qobuz track id to probe"
    ),
    quality: str = typer.Option(
        "max", "--quality", help="Quality hint for probing stream URL"
    ),
    allow_mp3: bool = typer.Option(
        False, "--allow-mp3", help="Permit MP3 probe if FLAC unavailable"
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Output machine-readable JSON"
    ),
):
    """Check Qobuz metadata + download URL health without downloading.

    - Verifies metadata access (track/get)
    - Attempts to resolve a stream URL via format negotiation
    """

    async def _run():
        ok_meta = False
        ok_stream = False
        report: dict[str, object] = {
            "provider": "qobuz",
            "track_id": track_id,
            "quality": quality,
            "metadata": {"ok": False, "title": None, "isrc": None},
            "stream": {"ok": False, "format_id": None},
        }
        async with QobuzPlugin() as plugin:
            try:
                t = await plugin.api_client.get_track(track_id)
                title = (t or {}).get("title") if isinstance(t, dict) else None
                isrc = (t or {}).get("isrc") if isinstance(t, dict) else None
                report["metadata"] = {"ok": bool(title), "title": title, "isrc": isrc}
                if not json_out:
                    console.print(
                        f"Metadata: {'OK' if title else 'FAIL'} - title='{title or '-'}', ISRC='{isrc or '-'}'"
                    )
                ok_meta = bool(title)
            except Exception as e:
                if not json_out:
                    console.print(f"[red]Metadata error:[/red] {e}")
            try:
                fmt, url = await plugin._find_stream(
                    track_id, quality, allow_mp3=allow_mp3
                )
                if url:
                    report["stream"] = {"ok": True, "format_id": fmt}
                    if not json_out:
                        console.print(f"Stream URL: OK (format_id={fmt})")
                    ok_stream = True
                else:
                    if not json_out:
                        console.print("Stream URL: FAIL")
            except Exception as e:
                if not json_out:
                    console.print(f"[yellow]Stream probe error:[/yellow] {e}")
        if json_out:
            typer.echo(json.dumps(report))
        if not ok_meta:
            raise typer.Exit(2)
        if not ok_stream:
            raise typer.Exit(3)

    asyncio.run(_run())


@app.command("tools")
def diag_tools(
    json_out: bool = typer.Option(
        False, "--json", help="Output machine-readable JSON"
    ),
):
    """Check presence of external tools and basic HTTP connectivity."""
    import shutil
    import subprocess
    import requests

    def _check_bin(name: str) -> tuple[bool, Optional[str]]:
        path = shutil.which(name)
        if not path:
            return False, None
        try:
            out = subprocess.run(
                [name, "-version"], capture_output=True, text=True, timeout=5
            )
            ver = (
                (out.stdout or out.stderr).splitlines()[0]
                if (out.stdout or out.stderr)
                else None
            )
            return True, ver
        except Exception:
            return True, None

    ok_ffmpeg, ffmpeg_ver = _check_bin("ffmpeg")
    ok_ffprobe, ffprobe_ver = _check_bin("ffprobe")
    report = {
        "tools": {
            "ffmpeg": {"ok": ok_ffmpeg, "version": ffmpeg_ver},
            "ffprobe": {"ok": ok_ffprobe, "version": ffprobe_ver},
        },
        "http": {"ok": False, "status": None},
    }
    if not json_out:
        console.print(
            f"ffmpeg: {'OK' if ok_ffmpeg else 'MISSING'}{(' - ' + ffmpeg_ver) if ffmpeg_ver else ''}"
        )
        console.print(
            f"ffprobe: {'OK' if ok_ffprobe else 'MISSING'}{(' - ' + ffprobe_ver) if ffprobe_ver else ''}"
        )

    # Simple HTTP reachability
    try:
        r = requests.get("https://httpbin.org/get", timeout=5)
        report["http"] = {"ok": r.status_code == 200, "status": r.status_code}
        if not json_out:
            console.print(
                f"HTTP: {'OK' if r.status_code == 200 else 'FAIL'} (httpbin {r.status_code})"
            )
    except Exception as e:
        if not json_out:
            console.print(f"HTTP: FAIL ({e})")
        report["http"] = {"ok": False, "status": None}
    if json_out:
        typer.echo(json.dumps(report))


@app.command("all-status")
def diag_all_status(
    qobuz_track: str = typer.Option("168662534", help="Qobuz track id"),
    tidal_track: str = typer.Option("86902482", help="Tidal track id"),
    quality: str = typer.Option("max", help="Quality hint for streams"),
    allow_mp3: bool = typer.Option(False, help="Permit MP3 for Qobuz probe"),
    json_out: bool = typer.Option(False, "--json", help="Output JSON report"),
):
    """Run both Qobuz and Tidal checks and summarize results."""

    async def _run():
        from contextlib import suppress

        report = {"qobuz": None, "tidal": None}

        async with QobuzPlugin() as qp:
            q = {"ok": False, "metadata": {}, "stream": {}}
            with suppress(Exception):
                t = await qp.api_client.get_track(qobuz_track)
                title = (t or {}).get("title") if isinstance(t, dict) else None
                isrc = (t or {}).get("isrc") if isinstance(t, dict) else None
                q["metadata"] = {"ok": bool(title), "title": title, "isrc": isrc}
            with suppress(Exception):
                fmt, url = await qp._find_stream(qobuz_track, quality, allow_mp3=allow_mp3)
                q["stream"] = {"ok": bool(url), "format_id": fmt}
            q["ok"] = bool(q.get("metadata", {}).get("ok")) and bool(q.get("stream", {}).get("ok"))
            report["qobuz"] = q

        t = TidalPlugin()
        with suppress(Exception):
            await t.authenticate()
        td = {"ok": False, "metadata": {}, "stream": {}}
        with suppress(Exception):
            md = await t._get_track_metadata(str(tidal_track))
            title = (md or {}).get("title") if isinstance(md, dict) else None
            isrc = (md or {}).get("isrc") if isinstance(md, dict) else None
            td["metadata"] = {"ok": bool(title), "title": title, "isrc": isrc}
        with suppress(Exception):
            si = await t._get_stream_info(str(tidal_track), quality)
            td["stream"] = {"ok": bool(si and si[0])}
        td["ok"] = bool(td.get("metadata", {}).get("ok")) and bool(td.get("stream", {}).get("ok"))
        report["tidal"] = td

        if json_out:
            typer.echo(json.dumps(report))
        else:
            console.print(
                f"Qobuz: {'OK' if report['qobuz']['ok'] else 'FAIL'} | "
                f"Tidal: {'OK' if report['tidal']['ok'] else 'FAIL'}"
            )

    asyncio.run(_run())


@app.command("tidal-status")
def diag_tidal_status(
    track_id: str = typer.Option(
        "86902482", "--track-id", help="Tidal track id to probe"
    ),
    quality: str = typer.Option(
        "max", "--quality", help="Quality hint for probing stream URL"
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Output machine-readable JSON"
    ),
):
    """Check Tidal metadata + stream URL health without downloading."""

    async def _run():
        ok_meta = False
        ok_stream = False
        report: dict[str, object] = {
            "provider": "tidal",
            "track_id": track_id,
            "quality": quality,
            "metadata": {"ok": False, "title": None, "isrc": None},
            "stream": {"ok": False},
        }
        t = TidalPlugin()
        try:
            await t.authenticate()
        except Exception as e:
            if not json_out:
                console.print(f"[red]Auth error:[/red] {e}")
        try:
            md = await t._get_track_metadata(str(track_id))
            title = (md or {}).get("title") if isinstance(md, dict) else None
            isrc = (md or {}).get("isrc") if isinstance(md, dict) else None
            report["metadata"] = {"ok": bool(title), "title": title, "isrc": isrc}
            if not json_out:
                console.print(
                    f"Metadata: {'OK' if title else 'FAIL'} - title='{title or '-'}', ISRC='{isrc or '-'}'"
                )
            ok_meta = bool(title)
        except Exception as e:
            if not json_out:
                console.print(f"[red]Metadata error:[/red] {e}")
        try:
            si = await t._get_stream_info(str(track_id), quality)
            if si and si[0]:
                report["stream"] = {"ok": True}
                if not json_out:
                    console.print("Stream URL: OK")
                ok_stream = True
            else:
                if not json_out:
                    console.print("Stream URL: FAIL")
        except Exception as e:
            if not json_out:
                console.print(f"[yellow]Stream probe error:[/yellow] {e}")
        if json_out:
            typer.echo(json.dumps(report))
        if not ok_meta:
            raise typer.Exit(2)
        if not ok_stream:
            raise typer.Exit(3)

    asyncio.run(_run())
