"""
Metadata tagging commands for FLACCID (`fla tag`).

Provides tools to update tags on existing files from online sources or
perform simple local fixes.
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Tuple

import typer
from rich.console import Console

from ..core.metadata import apply_metadata
from ..plugins.qobuz import QobuzPlugin
import requests

console = Console()
app = typer.Typer(
    no_args_is_help=True,
    help="Apply metadata to existing files (Qobuz, fixes).",
)


def _iter_audio_files(folder: Path) -> list[Path]:
    exts = {".flac", ".mp3", ".m4a"}
    return [p for p in folder.rglob("*") if p.suffix.lower() in exts and p.is_file()]


def _read_basic_tags(p: Path) -> Tuple[Optional[int], Optional[int]]:
    try:
        import mutagen

        audio = mutagen.File(p, easy=True)
        if not audio:
            return None, None
        def _get(key, default=None):
            v = audio.get(key, [default])
            return v[0] if v else default
        def _to_int(x):
            try:
                return int(str(x).split("/")[0]) if x is not None else None
            except Exception:
                return None
        tn = _to_int(_get("tracknumber"))
        dn = _to_int(_get("discnumber"))
        return tn, dn
    except Exception:
        return None, None


@app.command("fix-artist")
def tag_fix_artist(
    folder: Path = typer.Argument(..., help="Folder to fix ARTIST tags in"),
    prefer_albumartist: bool = typer.Option(
        True, "--prefer-albumartist/--no-prefer-albumartist", help="Use ALBUMARTIST if available"
    ),
    preview: bool = typer.Option(False, "--preview", help="Show changes without writing"),
):
    """Replace verbose ARTIST tags with a cleaner value for all files in folder.

    Default behavior: set ARTIST = ALBUMARTIST when present; otherwise leave existing.
    """
    files = _iter_audio_files(folder)
    if not files:
        console.print("[yellow]No audio files found.[/yellow]")
        raise typer.Exit(0)
    changed = 0
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, TPE1
    from mutagen.mp4 import MP4

    for f in files:
        try:
            ext = f.suffix.lower()
            aa = None
            cur = None
            if ext == ".flac":
                audio = FLAC(f)
                cur = ", ".join(audio.get("artist", [])) if "artist" in audio else None
                aa = ", ".join(audio.get("albumartist", [])) if "albumartist" in audio else None
                if prefer_albumartist and aa and aa.strip() and aa != cur:
                    if preview:
                        console.print(f"FLAC: {f.name} -> ARTIST='{aa}'")
                    else:
                        audio["ARTIST"] = [aa]
                        audio.save()
                        changed += 1
            elif ext == ".mp3":
                try:
                    id3 = ID3(f)
                except Exception:
                    id3 = ID3()
                cur = str(id3.get("TPE1").text[0]) if id3.get("TPE1") else None
                # No standard ALBUMARTIST in ID3 easy tags; skip unless desired
                if prefer_albumartist:
                    # Try TXXX:ALBUMARTIST first
                    aa = None
                    for fr in id3.getall("TXXX"):
                        if getattr(fr, "desc", "") == "ALBUMARTIST" and fr.text:
                            aa = str(fr.text[0])
                            break
                    if aa and aa != cur:
                        if preview:
                            console.print(f"MP3: {f.name} -> ARTIST='{aa}'")
                        else:
                            id3.add(TPE1(encoding=3, text=aa))
                            id3.save(f)
                            changed += 1
            elif ext == ".m4a":
                mp4 = MP4(f)
                cur = (mp4.tags.get("\xa9ART") or [None])[0]
                aa = (mp4.tags.get("aART") or [None])[0]
                if prefer_albumartist and aa and aa != cur:
                    if preview:
                        console.print(f"M4A: {f.name} -> ARTIST='{aa}'")
                    else:
                        mp4.tags["\xa9ART"] = [aa]
                        mp4.save()
                        changed += 1
        except Exception:
            continue
    if not preview:
        console.print(f"[green]✅ Updated ARTIST in {changed} files[/green]")


@app.command("qobuz")
def tag_qobuz(
    album_id: str = typer.Option(
        ..., "--album-id", "-a", help="Qobuz album ID to source metadata from"
    ),
    folder: Path = typer.Argument(..., help="Local album folder to tag"),
    preview: bool = typer.Option(False, "--preview", help="Show changes without writing"),
):
    """Tag a local album folder using Qobuz album metadata.

    Files are matched by (discnumber, tracknumber) from existing tags when possible.
    """

    async def _run():
        # Build local map (disc, track) -> path
        local_files = _iter_audio_files(folder)
        if not local_files:
            console.print("[yellow]No audio files found.[/yellow]")
            return
        index: Dict[Tuple[int, int], Path] = {}
        for f in local_files:
            tn, dn = _read_basic_tags(f)
            if tn is None:
                continue
            dn = dn or 1
            key = (int(dn), int(tn))
            if key not in index:
                index[key] = f

        applied = 0
        async with QobuzPlugin() as plugin:
            # Fetch album and normalize per-track metadata
            album = await plugin.api_client.get_album(album_id)
            tracks = (album.get("tracks") or {}).get("items") or []
            if not tracks:
                console.print("[red]No tracks in Qobuz album metadata[/red]")
                return
            for t in tracks:
                try:
                    tn = int(t.get("track_number") or t.get("trackNumber") or 0)
                    dn = int(t.get("media_number") or t.get("disc_number") or 1)
                except Exception:
                    tn, dn = 0, 1
                if tn <= 0:
                    continue
                fpath = index.get((dn, tn))
                if not fpath:
                    continue
                md = plugin._normalize_metadata(t)
                # keep disc/track totals if present from album
                if isinstance(album, dict):
                    try:
                        md.setdefault("disctotal", int(album.get("media_count") or 1))
                    except Exception:
                        pass
                if preview:
                    console.print(
                        f"Would tag: [blue]{fpath.name}[/blue] -> ARTIST='{md.get('artist')}', TITLE='{md.get('title')}'"
                    )
                else:
                    apply_metadata(fpath, md)
                    applied += 1
        if not preview:
            console.print(f"[green]✅ Applied metadata to {applied} file(s)[/green]")

    asyncio.run(_run())


@app.command("cascade")
def tag_cascade(
    folder: Path = typer.Argument(..., help="Local album folder to tag"),
    order: str = typer.Option(
        "tidal,apple,qobuz,beatport,mb",
        "--order",
        help="Cascade order using any of: tidal, apple, qobuz, beatport, mb",
    ),
    preview: bool = typer.Option(False, "--preview", help="Show changes without writing"),
    fill_missing: bool = typer.Option(False, "--fill-missing", help="Only fill empty tags; do not overwrite non-empty"),
):
    """Cascade-tag a folder: try Qobuz, then MusicBrainz, then fall back to existing.

    Matching is by (disc, track) when possible; Qobuz also tried by ISRC.
    """

    async def _run():
        local_files = _iter_audio_files(folder)
        if not local_files:
            console.print("[yellow]No audio files found.[/yellow]")
            return
        # Build (disc,track) index and gather ISRCs
        index: Dict[Tuple[int, int], Path] = {}
        file_isrc: Dict[Path, str] = {}
        for f in local_files:
            tn, dn = _read_basic_tags(f)
            dn = dn or 1
            if tn:
                key = (int(dn), int(tn))
                if key not in index:
                    index[key] = f
            # Read ISRC from tags
            try:
                import mutagen
                au = mutagen.File(f, easy=True)
                if au:
                    v = au.get("isrc", [None])[0]
                    if v:
                        file_isrc[f] = str(v)
            except Exception:
                pass

        order_list = [s.strip().lower() for s in order.split(",") if s.strip()]
        applied = 0
        async with QobuzPlugin() as plugin:
            # Try Qobuz first (by track mapping, then by ISRC)
            q_done: set[Path] = set()
            if "qobuz" in order_list:
                # Attempt to infer album id from any QOBUZ_ALBUM_ID on files
                album_id = None
                for f in local_files:
                    try:
                        from mutagen.flac import FLAC
                        if f.suffix.lower() == ".flac":
                            fl = FLAC(f)
                            val = fl.get("QOBUZ_ALBUM_ID")
                            if val:
                                album_id = str(val[0])
                                break
                    except Exception:
                        pass
                if album_id:
                    try:
                        album = await plugin.api_client.get_album(album_id)
                        tracks = (album.get("tracks") or {}).get("items") or []
                        for t in tracks:
                            try:
                                tn = int(t.get("track_number") or t.get("trackNumber") or 0)
                                dn = int(t.get("media_number") or t.get("disc_number") or 1)
                            except Exception:
                                tn, dn = 0, 1
                            if tn <= 0:
                                continue
                            f = index.get((dn, tn))
                            if not f:
                                continue
                            md = plugin._normalize_metadata(t)
                            if preview:
                                console.print(f"QOBUZ map: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'")
                            else:
                                apply_metadata(f, md)
                                q_done.add(f)
                                applied += 1
                    except Exception:
                        pass
                # Try by ISRC via Qobuz track search
                for f, isrc in file_isrc.items():
                    if f in q_done:
                        continue
                    try:
                        sr = await plugin.api_client.search_track(isrc, limit=1)
                        items = (sr.get("tracks") or {}).get("items") or []
                        t = items[0] if items else None
                        if not t:
                            continue
                        md = plugin._normalize_metadata(t)
                        if preview:
                            console.print(f"QOBUZ isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'")
                        else:
                            apply_metadata(f, md)
                            applied += 1
                    except Exception:
                        continue

            # Tidal by ISRC
            if "tidal" in order_list:
                try:
                    from ..plugins.tidal import TidalPlugin

                    t = TidalPlugin()
                    await t.authenticate()
                    for f, isrc in file_isrc.items():
                        try:
                            md = await t.search_track_by_isrc(isrc)
                            if not md:
                                continue
                            if preview:
                                console.print(f"TIDAL isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'")
                            else:
                                apply_metadata(f, md)
                                applied += 1
                        except Exception:
                            continue
                except Exception:
                    pass

            # Apple (iTunes) by ISRC
            if "apple" in order_list:
                for f, isrc in file_isrc.items():
                    try:
                        resp = requests.get(
                            "https://itunes.apple.com/lookup",
                            params={"isrc": isrc, "entity": "song", "country": "US"},
                            timeout=10,
                        )
                        resp.raise_for_status()
                        js = resp.json() or {}
                        results = js.get("results") or []
                        if not results:
                            continue
                        r = results[0]
                        def _art(url: Optional[str]) -> Optional[str]:
                            if not url:
                                return None
                            # Try upscale to 1200x1200 when possible
                            return url.replace("100x100", "1200x1200")
                        md = {
                            "title": r.get("trackName"),
                            "artist": r.get("artistName"),
                            "album": r.get("collectionName"),
                            "albumartist": r.get("collectionArtistName") or r.get("artistName"),
                            "composer": r.get("composerName"),
                            "tracknumber": r.get("trackNumber"),
                            "discnumber": r.get("discNumber"),
                            "tracktotal": r.get("trackCount"),
                            "disctotal": r.get("discCount"),
                            "date": (r.get("releaseDate") or "")[:10],
                            "isrc": isrc,
                            "cover_url": _art(r.get("artworkUrl100")),
                            "apple_track_id": r.get("trackId"),
                            "apple_album_id": r.get("collectionId"),
                        }
                        if fill_missing:
                            # Read current tags and drop keys that are already set
                            try:
                                import mutagen
                                au = mutagen.File(f, easy=True)
                                if au:
                                    def _has(key: str) -> bool:
                                        v = au.get(key)
                                        if not v:
                                            return False
                                        val = v[0] if isinstance(v, list) else v
                                        return (str(val).strip() != "")
                                    for k in list(md.keys()):
                                        # Map common keys to easy tag names
                                        easy_map = {
                                            "title": "title",
                                            "artist": "artist",
                                            "album": "album",
                                            "albumartist": "albumartist",
                                            "composer": "composer",
                                            "tracknumber": "tracknumber",
                                            "discnumber": "discnumber",
                                            "date": "date",
                                            "genre": "genre",
                                            "isrc": "isrc",
                                        }
                                        em = easy_map.get(k)
                                        if em and _has(em):
                                            md.pop(k, None)
                            except Exception:
                                pass
                        if preview:
                            console.print(f"APPLE isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'")
                        else:
                            apply_metadata(f, md)
                            applied += 1
                    except Exception:
                        continue

            # Beatport (placeholder)
            if "beatport" in order_list:
                console.print("[yellow]Beatport lookup not implemented yet; skipping.[/yellow]")

            # MusicBrainz fallback by ISRC
            if "mb" in order_list:
                headers = {
                    "User-Agent": "flaccid/0.1 (+https://github.com/; tag cascade)",
                    "Accept": "application/json",
                }
                for f, isrc in file_isrc.items():
                    try:
                        url = "https://musicbrainz.org/ws/2/recording"
                        resp = requests.get(url, params={"query": f"isrc:{isrc}", "fmt": "json"}, headers=headers, timeout=12)
                        resp.raise_for_status()
                        data = resp.json() or {}
                        recs = data.get("recordings") or []
                        if not recs:
                            continue
                        rec = recs[0]
                        title = rec.get("title")
                        # Artist credit join
                        ac = rec.get("artist-credit") or []
                        artists = []
                        for a in ac:
                            n = (a.get("artist") or {}).get("name")
                            if n:
                                artists.append(n)
                        md = {}
                        if title:
                            md["title"] = title
                        if artists:
                            md["artist"] = ", ".join(artists)
                        if not md:
                            continue
                        if preview:
                            console.print(f"MB isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'")
                        else:
                            apply_metadata(f, md)
                            applied += 1
                    except Exception:
                        continue

        if not preview:
            console.print(f"[green]✅ Cascade tagging applied to {applied} file(s)[/green]")

    asyncio.run(_run())
