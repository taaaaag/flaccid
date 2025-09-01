"""
Metadata tagging commands for FLACCID (`fla tag`).

Provides tools to update tags on existing files from online sources or
perform simple local fixes.
"""

import asyncio
import re
import csv
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
import typer
from rich.console import Console
import mutagen  # noqa: F401
from mutagen.id3 import ID3, TALB, TCON, TIT2, TPE1

from ..core.metadata import apply_metadata
from ..plugins.qobuz import QobuzPlugin

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


@app.command("audit")
def tag_audit(
    folder: Path = typer.Argument(..., help="Folder to audit/fix basic tags in"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without modifying files"
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Fix simple metadata issues (title/artist/album/date/genre)",
    ),
    report: Optional[Path] = typer.Option(
        None, "--report", help="Write CSV report to this path"
    ),
):
    """Audit and optionally fix missing basic tags across a folder.

    This is a lightweight wrapper inspired by contrib/legacy/metadata_mafioso.py.
    """
    files = _iter_audio_files(folder)
    if not files:
        console.print("[yellow]No audio files found.[/yellow]")
        raise typer.Exit(0)
    # imports moved to module level

    def _get_easy(audio, key):
        try:
            v = audio.get(key)
            if isinstance(v, list) and v:
                return v[0]
            return v
        except Exception:
            return None

    def _fix_easy(audio, path: Path) -> bool:
        changed = False

        def _ensure(key: str, default: str):
            nonlocal changed
            try:
                v = audio.get(key)
                empty = (
                    (v is None)
                    or (isinstance(v, list) and not v)
                    or (str(v).strip() == "")
                )
                if empty:
                    if not dry_run:
                        audio[key] = default
                    changed = True
            except Exception:
                pass

        _ensure("title", path.stem)
        _ensure("artist", "Unknown Artist")
        _ensure("album", "Unknown Album")
        _ensure("date", "0000")
        _ensure("genre", "Unknown Genre")
        if changed and not dry_run:
            try:
                audio.save()
            except Exception:
                pass
        return changed

    report_rows = []
    total = 0
    fixed = 0
    for f in files:
        try:
            ext = f.suffix.lower()
            audio = None
            id3 = None
            if ext == ".mp3":
                # Work with ID3 tag directly for ID3-only containers
                try:
                    id3 = ID3(f)
                except Exception:
                    id3 = ID3()
            else:
                audio = mutagen.File(f, easy=True)
                if not audio:
                    continue
            total += 1
            if report:
                if id3 is not None:
                    t = id3.get("TIT2").text[0] if id3.get("TIT2") else None
                    a = id3.get("TPE1").text[0] if id3.get("TPE1") else None
                    al = id3.get("TALB").text[0] if id3.get("TALB") else None
                    g = id3.get("TCON").text[0] if id3.get("TCON") else None
                    report_rows.append(
                        {
                            "file": str(f),
                            "title": t,
                            "artist": a,
                            "album": al,
                            "date": None,
                            "genre": g,
                        }
                    )
                else:
                    report_rows.append(
                        {
                            "file": str(f),
                            "title": _get_easy(audio, "title"),
                            "artist": _get_easy(audio, "artist"),
                            "album": _get_easy(audio, "album"),
                            "date": _get_easy(audio, "date")
                            or _get_easy(audio, "year"),
                            "genre": _get_easy(audio, "genre"),
                        }
                    )
            if fix or dry_run:
                if id3 is not None:
                    # Minimal defaulting for ID3-only files
                    changed = False
                    if not id3.get("TIT2"):
                        if not dry_run:
                            id3.add(TIT2(encoding=3, text=f.stem))
                        changed = True
                    if not id3.get("TPE1"):
                        if not dry_run:
                            id3.add(TPE1(encoding=3, text="Unknown Artist"))
                        changed = True
                    if not id3.get("TALB"):
                        if not dry_run:
                            id3.add(TALB(encoding=3, text="Unknown Album"))
                        changed = True
                    if not id3.get("TCON"):
                        if not dry_run:
                            id3.add(TCON(encoding=3, text="Unknown Genre"))
                        changed = True
                    if changed and not dry_run:
                        id3.save(f)
                    if changed:
                        fixed += 1
                else:
                    if _fix_easy(audio, f):
                        fixed += 1
        except Exception:
            continue
    if report and report_rows:
        try:
            with open(report, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(
                    fh, fieldnames=["file", "title", "artist", "album", "date", "genre"]
                )
                w.writeheader()
                w.writerows(report_rows)
            console.print(f"[cyan]Report written:[/cyan] {report}")
        except Exception as e:
            console.print(f"[yellow]Could not write report {report}: {e}[/yellow]")
    console.print(
        f"[green]Audit complete[/green]: {total} files inspected; {fixed} {'would be fixed' if dry_run else 'fixed' if fix else 'fixable'}"
    )


def _filter_missing_only(file_path: Path, md: Dict) -> Dict:
    """Return a copy of metadata with keys removed if file already has non-empty values.

    Uses Mutagen easy tags where possible.
    """
    try:
        import mutagen

        au = mutagen.File(file_path, easy=True)
        if not au:
            return md

        def _has(key: str) -> bool:
            v = au.get(key)
            if not v:
                return False
            val = v[0] if isinstance(v, list) else v
            return str(val).strip() != ""

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
        out = dict(md)
        for k, ek in easy_map.items():
            if k in out and _has(ek):
                out.pop(k, None)
        return out
    except Exception:
        return md


def _extract_qobuz_album_id(files: list[Path]) -> Optional[str]:
    """Try extract Qobuz album id from any file: FLAC, MP3(ID3 TXXX), M4A(freeform)."""
    for f in files:
        try:
            ext = f.suffix.lower()
            if ext == ".flac":
                from mutagen.flac import FLAC

                fl = FLAC(f)
                val = fl.get("QOBUZ_ALBUM_ID") or fl.get("qobuz_album_id")
                if val:
                    return str(val[0])
            elif ext == ".mp3":
                from mutagen.id3 import ID3

                id3 = ID3(f)
                for fr in id3.getall("TXXX"):
                    if getattr(fr, "desc", "").upper() == "QOBUZ_ALBUM_ID" and fr.text:
                        return str(fr.text[0])
            elif ext == ".m4a":
                from mutagen.mp4 import MP4

                mp4 = MP4(f)
                key = "----:com.apple.iTunes:QOBUZ_ALBUM_ID"
                if mp4.tags and key in mp4.tags and mp4.tags[key]:
                    raw = mp4.tags[key][0]
                    try:
                        return (
                            raw.decode("utf-8")
                            if isinstance(raw, (bytes, bytearray))
                            else str(raw)
                        )
                    except Exception:
                        return str(raw)
        except Exception:
            continue
    return None


@app.command("fix-artist")
def tag_fix_artist(
    folder: Path = typer.Argument(..., help="Folder to fix ARTIST tags in"),
    prefer_albumartist: bool = typer.Option(
        True,
        "--prefer-albumartist/--no-prefer-albumartist",
        help="Use ALBUMARTIST if available",
    ),
    strip_feat: bool = typer.Option(
        False, "--strip-feat", help="Remove 'feat.'/'ft.'/'featuring' from ARTIST"
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Show changes without writing"
    ),
):
    """Replace verbose ARTIST tags with a cleaner value for all files in folder.

    Default behavior: set ARTIST = ALBUMARTIST when present; otherwise leave existing.
    """
    files = _iter_audio_files(folder)
    if not files:
        console.print("[yellow]No audio files found.[/yellow]")
        raise typer.Exit(0)
    changed = 0
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, TPE1, TPE2, TXXX
    from mutagen.mp4 import MP4

    def _strip_feat(s: Optional[str]) -> Optional[str]:
        if not s:
            return s
        # Cut anything from feat./featuring/ft. marker to end (optionally bracketed)
        parts = re.split(
            r"\s*(?:[\(\[\-]\s*)?(?:feat\.?|featuring|ft\.?)[\s:]+",
            s,
            flags=re.IGNORECASE,
        )
        return parts[0].strip(" -([") if parts else s

    for f in files:
        try:
            ext = f.suffix.lower()
            aa = None
            cur = None
            if ext == ".flac":
                audio = FLAC(f)
                cur_list = audio.get("artist", []) if "artist" in audio else []
                cur = ", ".join(cur_list) if cur_list else None
                aa_list = audio.get("albumartist", []) if "albumartist" in audio else []
                aa = ", ".join(aa_list) if aa_list else None
                # Decide desired value
                desired = None
                used_aa_list = False
                if prefer_albumartist and aa and aa.strip():
                    desired = aa
                    used_aa_list = True
                else:
                    desired = cur
                    used_aa_list = False
                if strip_feat and desired:
                    if used_aa_list and aa_list:
                        san_list = [_strip_feat(x) or "" for x in aa_list]
                        san_list = [x for x in san_list if x]
                        desired = (
                            ", ".join(san_list) if san_list else _strip_feat(desired)
                        )
                    else:
                        desired = _strip_feat(desired)
                if desired and desired != cur:
                    if preview:
                        console.print(f"FLAC: {f.name} -> ARTIST='{desired}'")
                    else:
                        # Preserve list semantics when possible
                        if used_aa_list and aa_list:
                            san_list = [
                                _strip_feat(x) if strip_feat else x for x in aa_list
                            ]
                            san_list = [x for x in san_list if x]
                            audio["artist"] = san_list if san_list else [desired]
                        else:
                            audio["artist"] = [desired]
                        audio.save()
                        changed += 1
            elif ext == ".mp3":
                try:
                    id3 = ID3(f)
                except Exception:
                    id3 = ID3()
                cur = str(id3.get("TPE1").text[0]) if id3.get("TPE1") else None
                # ID3: Album Artist is commonly stored in TPE2 or custom TXXX
                aa = None
                if id3.get("TPE2") and getattr(id3.get("TPE2"), "text", None):
                    try:
                        aa = str(id3.get("TPE2").text[0])
                    except Exception:
                        aa = None
                if not aa:
                    for fr in id3.getall("TXXX"):
                        desc = getattr(fr, "desc", "") or ""
                        if (
                            desc.upper().replace(" ", "")
                            in {"ALBUMARTIST", "ALBUMARTISTSORT"}
                            and fr.text
                        ):
                            aa = str(fr.text[0])
                            break
                desired = None
                if prefer_albumartist and aa and aa.strip():
                    desired = aa
                else:
                    desired = cur
                if strip_feat and desired:
                    desired = _strip_feat(desired)
                if desired and desired != cur:
                    if preview:
                        console.print(f"MP3: {f.name} -> ARTIST='{desired}'")
                    else:
                        # Replace any existing TPE1 instead of adding duplicates
                        try:
                            id3.delall("TPE1")
                        except Exception:
                            pass
                        id3.add(TPE1(encoding=3, text=[desired]))
                        # Ensure TPE2 mirrors Album Artist if missing and we sourced from album artist
                        if (prefer_albumartist and aa and aa.strip()) and not id3.get(
                            "TPE2"
                        ):
                            id3.add(TPE2(encoding=3, text=[aa]))
                        # Optionally persist a TXXX marker for interoperability
                        has_txxx = any(
                            (getattr(fr, "desc", "") or "").upper() == "ALBUMARTIST"
                            for fr in id3.getall("TXXX")
                        )
                        if (prefer_albumartist and aa and aa.strip()) and not has_txxx:
                            id3.add(TXXX(encoding=3, desc="ALBUMARTIST", text=[aa]))
                        id3.save(f)
                        changed += 1
            elif ext == ".m4a":
                mp4 = MP4(f)
                cur = (mp4.tags.get("\xa9ART") or [None])[0]
                aa = (mp4.tags.get("aART") or [None])[0]
                desired = aa if (prefer_albumartist and aa and str(aa).strip()) else cur
                if strip_feat and desired:
                    desired = _strip_feat(str(desired))
                if desired and desired != cur:
                    if preview:
                        console.print(f"M4A: {f.name} -> ARTIST='{desired}'")
                    else:
                        mp4.tags["\xa9ART"] = [desired]
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
    preview: bool = typer.Option(
        False, "--preview", help="Show changes without writing"
    ),
    fill_missing: bool = typer.Option(
        False, "--fill-missing", help="Only fill empty tags; do not overwrite non-empty"
    ),
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
                if fill_missing:
                    md = _filter_missing_only(fpath, md)
                if preview:
                    console.print(
                        f"Would tag: [blue]{fpath.name}[/blue] -> ARTIST='{md.get('artist')}', TITLE='{md.get('title')}'"
                    )
                else:
                    if md:
                        apply_metadata(fpath, md)
                        applied += 1
        if not preview:
            console.print(f"[green]✅ Applied metadata to {applied} file(s)[/green]")

    asyncio.run(_run())


@app.command("apple")
def tag_apple(
    album_id: int = typer.Option(
        ...,
        "--album-id",
        "-a",
        help="Apple collection (album) ID to source metadata from",
    ),
    folder: Path = typer.Argument(..., help="Local album folder to tag"),
    preview: bool = typer.Option(
        False, "--preview", help="Show changes without writing"
    ),
    fill_missing: bool = typer.Option(
        False, "--fill-missing", help="Only fill empty tags; do not overwrite non-empty"
    ),
):
    """Tag a local album folder using Apple iTunes album metadata.

    Fetches album tracks via iTunes Lookup API (entity=song) and matches by (disc, track).
    """

    def _normalize_art(url: str | None) -> str | None:
        if not url:
            return None
        # Upgrade common artworkUrl100 pattern to 1200x1200
        try:
            return (
                str(url)
                .replace("100x100bb", "1200x1200bb")
                .replace("100x100-999", "1200x1200-999")
            )
        except Exception:
            return url

    async def _run():
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

        # Fetch album + tracks from iTunes Lookup API
        import requests as _requests

        try:
            resp = _requests.get(
                "https://itunes.apple.com/lookup",
                params={"id": int(album_id), "entity": "song", "limit": 500},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as e:
            raise typer.Exit(f"[red]Apple lookup failed:[/red] {e}")

        results = data.get("results") or []
        album_info = (
            results[0]
            if results and results[0].get("wrapperType") == "collection"
            else None
        )
        tracks = [r for r in results if r.get("wrapperType") == "track"]
        if not tracks:
            console.print("[red]No tracks found for Apple album.[/red]")
            return

        applied = 0
        for t in tracks:
            try:
                tn = int(t.get("trackNumber") or 0)
                dn = int(t.get("discNumber") or 1)
            except Exception:
                tn, dn = 0, 1
            if tn <= 0:
                continue
            fpath = index.get((dn, tn))
            if not fpath:
                continue
            md = {
                "title": t.get("trackName"),
                "artist": t.get("artistName"),
                "album": t.get("collectionName"),
                "albumartist": (album_info or {}).get("artistName")
                or t.get("artistName"),
                "tracknumber": tn,
                "discnumber": dn,
                "tracktotal": (
                    album_info.get("trackCount")
                    if isinstance(album_info, dict)
                    else None
                ),
                "disctotal": None,
                "date": (album_info or {}).get("releaseDate"),
                "isrc": t.get("isrc") or None,
                "cover_url": _normalize_art(
                    t.get("artworkUrl100") or (album_info or {}).get("artworkUrl100")
                ),
                "apple_track_id": t.get("trackId"),
                "apple_album_id": t.get("collectionId"),
            }
            if fill_missing:
                md = _filter_missing_only(fpath, md)
            if preview:
                console.print(
                    f"Would tag: [blue]{fpath.name}[/blue] -> ARTIST='{md.get('artist')}', TITLE='{md.get('title')}'"
                )
            else:
                if md:
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
    preview: bool = typer.Option(
        False, "--preview", help="Show changes without writing"
    ),
    fill_missing: bool = typer.Option(
        False, "--fill-missing", help="Only fill empty tags; do not overwrite non-empty"
    ),
):
    """Cascade-tag a folder: try sources in order, e.g., Qobuz, then Tidal, etc.

    Matching is by (disc, track) when possible; most sources also tried by ISRC.
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
        tagged_files: set[Path] = set()

        for source in order_list:
            if source == "qobuz":
                async with QobuzPlugin() as plugin:
                    # Attempt to infer album id from any provider tag on files
                    album_id = _extract_qobuz_album_id(local_files)
                    if album_id:
                        try:
                            album = await plugin.api_client.get_album(album_id)
                            tracks = (album.get("tracks") or {}).get("items") or []
                            for t in tracks:
                                if len(tagged_files) == len(local_files) and not fill_missing:
                                    break
                                try:
                                    tn = int(
                                        t.get("track_number") or t.get("trackNumber") or 0
                                    )
                                    dn = int(
                                        t.get("media_number") or t.get("disc_number") or 1
                                    )
                                except Exception:
                                    tn, dn = 0, 1
                                if tn <= 0:
                                    continue
                                f = index.get((dn, tn))
                                if not f or f in tagged_files:
                                    continue
                                md = plugin._normalize_metadata(t)
                                if fill_missing:
                                    md = _filter_missing_only(f, md)
                                if preview:
                                    console.print(
                                        f"QOBUZ map: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'"
                                    )
                                else:
                                    if md:
                                        apply_metadata(f, md)
                                        applied += 1
                                        if not fill_missing:
                                            tagged_files.add(f)
                        except Exception:
                            pass
                    # Try by ISRC via Qobuz track search
                    for f, isrc in file_isrc.items():
                        if f in tagged_files:
                            continue
                        try:
                            sr = await plugin.api_client.search_track(isrc, limit=1)
                            items = (sr.get("tracks") or {}).get("items") or []
                            t = items[0] if items else None
                            if not t:
                                continue
                            md = plugin._normalize_metadata(t)
                            if fill_missing:
                                md = _filter_missing_only(f, md)
                            if preview:
                                console.print(
                                    f"QOBUZ isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'"
                                )
                            else:
                                if md:
                                    apply_metadata(f, md)
                                    applied += 1
                                    if not fill_missing:
                                        tagged_files.add(f)
                        except Exception:
                            continue

            elif source == "tidal":
                try:
                    from ..plugins.tidal import TidalPlugin

                    t = TidalPlugin()
                    await t.authenticate()
                    for f, isrc in file_isrc.items():
                        if f in tagged_files:
                            continue
                        try:
                            md = await t.search_track_by_isrc(isrc)
                            if not md:
                                continue
                            if fill_missing:
                                md = _filter_missing_only(f, md)
                            if preview:
                                console.print(
                                    f"TIDAL isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'"
                                )
                            else:
                                if md:
                                    apply_metadata(f, md)
                                    applied += 1
                                    if not fill_missing:
                                        tagged_files.add(f)
                        except Exception:
                            continue
                except Exception:
                    pass

            elif source == "apple":
                for f, isrc in file_isrc.items():
                    if f in tagged_files:
                        continue
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
                            return url.replace("100x100", "1200x1200")

                        md = {
                            "title": r.get("trackName"),
                            "artist": r.get("artistName"),
                            "album": r.get("collectionName"),
                            "albumartist": r.get("collectionArtistName")
                            or r.get("artistName"),
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
                            md = _filter_missing_only(f, md)
                        if preview:
                            console.print(
                                f"APPLE isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'"
                            )
                        else:
                            if md:
                                apply_metadata(f, md)
                                applied += 1
                                if not fill_missing:
                                    tagged_files.add(f)
                    except Exception:
                        continue
            
            elif source == "beatport":
                headers = {
                    "User-Agent": "flaccid/0.2 (+https://github.com/tagslut/flaccid)",
                    "Accept": "application/json",
                }
                for f, isrc in file_isrc.items():
                    if f in tagged_files:
                        continue
                    try:
                        # This is a hypothetical API endpoint, actual may differ
                        url = "https://api.beatport.com/v4/catalog/tracks"
                        resp = requests.get(
                            url, params={"isrc": isrc}, headers=headers, timeout=15
                        )
                        resp.raise_for_status()
                        data = resp.json() or {}
                        tracks = data.get("results", [])
                        if not tracks:
                            continue
                        
                        track = tracks[0]
                        artists = ", ".join([a["name"] for a in track.get("artists", []) if a.get("name")])
                        title = track.get("name")
                        if track.get("mix_name"):
                            title = f'{title} ({track.get("mix_name")})'

                        md = {
                            "title": title,
                            "artist": artists,
                            "album": track.get("release", {}).get("name"),
                            "albumartist": artists,
                            "tracknumber": track.get("number"),
                            "date": (track.get("release", {}).get("publish_date") or "")[:10],
                            "genre": (track.get("genre") or {}).get("name"),
                            "isrc": isrc,
                            "cover_url": (track.get("release", {}).get("image") or {}).get("uri"),
                        }
                        md = {k: v for k, v in md.items() if v is not None}
                        if not md:
                            continue

                        if fill_missing:
                            md = _filter_missing_only(f, md)
                        
                        if preview:
                            console.print(
                                f"BEATPORT isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'"
                            )
                        else:
                            if md:
                                apply_metadata(f, md)
                                applied += 1
                                if not fill_missing:
                                    tagged_files.add(f)
                    except Exception:
                        continue

            elif source == "mb":
                headers = {
                    "User-Agent": "flaccid/0.2 (+https://github.com/tagslut/flaccid)",
                    "Accept": "application/json",
                }
                for f, isrc in file_isrc.items():
                    if f in tagged_files:
                        continue
                    try:
                        url = "https://musicbrainz.org/ws/2/recording"
                        resp = requests.get(
                            url,
                            params={"query": f"isrc:{isrc}", "fmt": "json"},
                            headers=headers,
                            timeout=12,
                        )
                        resp.raise_for_status()
                        data = resp.json() or {}
                        recs = data.get("recordings") or []
                        if not recs:
                            continue
                        rec = recs[0]
                        title = rec.get("title")
                        ac = rec.get("artist-credit") or []
                        artists = [a.get("artist", {}).get("name") for a in ac if a.get("artist", {}).get("name")]
                        
                        md = {}
                        if title:
                            md["title"] = title
                        if artists:
                            md["artist"] = ", ".join(artists)
                        if not md:
                            continue

                        if fill_missing:
                            md = _filter_missing_only(f, md)
                        if preview:
                            console.print(
                                f"MB isrc: {f.name} -> '{md.get('artist')}' / '{md.get('title')}'"
                            )
                        else:
                            if md:
                                apply_metadata(f, md)
                                applied += 1
                                if not fill_missing:
                                    tagged_files.add(f)
                    except Exception:
                        continue

        if not preview:
            console.print(
                f"[green]✅ Cascade tagging applied to {applied} file(s)[/green]"
            )

    asyncio.run(_run())
