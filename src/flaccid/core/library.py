"""
Core logic for library management.

This module contains functions for scanning the filesystem, computing hashes,
extracting metadata, and performing incremental updates to the library database.
"""

import hashlib
import sqlite3
from pathlib import Path

import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TPOS, TSRC
from mutagen.mp4 import MP4
from rich.console import Console

from .database import Track, get_all_tracks, insert_track, remove_track_by_path

console = Console()


def compute_hash(file_path: Path, algo: str = "sha1") -> str:
    """Computes a hash (SHA1 by default) for a given file."""
    h = hashlib.new(algo)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_library_paths(library_root: Path) -> list[Path]:
    """Scans a directory recursively for all supported audio files."""
    audio_exts = {".flac", ".mp3", ".m4a", ".alac", ".wav"}
    return [
        p
        for p in library_root.rglob("*")
        if p.suffix.lower() in audio_exts
        and p.is_file()
        and not p.name.startswith(".")
        and not p.name.startswith("._")
    ]


def index_file(file_path: Path, verify: bool = False) -> Track | None:
    """Extracts metadata from a single audio file and returns a Track object."""
    try:
        try:
            audio = mutagen.File(file_path, easy=True)
        except Exception:
            # If the container lacks audio frames (ID3-only), continue with fallback
            audio = None

        title = file_path.stem
        artist = "Unknown Artist"
        album = "Unknown Album"
        albumartist = None
        tracknumber = 0
        discnumber = 0
        isrc = None
        duration = None
        apple_id = None

        if audio:

            def get_tag(key, default=None):
                val = audio.get(key, [default])
                return val[0] if val else default

            title = get_tag("title", title)
            artist = get_tag("artist", artist)
            album = get_tag("album", album)
            albumartist = get_tag("albumartist", albumartist)
            try:
                tracknumber = int(str(get_tag("tracknumber", "0")).split("/")[0])
            except Exception:
                tracknumber = 0
            try:
                discnumber = int(str(get_tag("discnumber", "0")).split("/")[0])
            except Exception:
                discnumber = 0
            isrc = get_tag("isrc", None)
            # Provider IDs from FLAC/Vorbis comments (easy tags lowercased)
            try:
                qobuz_id = get_tag("qobuz_track_id", None)
            except Exception:
                qobuz_id = None
            try:
                tidal_id = get_tag("tidal_track_id", None)
            except Exception:
                tidal_id = None
            try:
                apple_id = get_tag("apple_track_id", None)
            except Exception:
                apple_id = None
            duration = int(audio.info.length) if getattr(audio, "info", None) else None
        else:
            # Fallback: bare ID3 tags without audio frames
            try:
                id3 = ID3(file_path)
                if id3.get("TIT2"):
                    title = str(id3.get("TIT2").text[0]) or title
                if id3.get("TPE1"):
                    artist = str(id3.get("TPE1").text[0]) or artist
                if id3.get("TALB"):
                    album = str(id3.get("TALB").text[0]) or album
                if id3.get("TRCK"):
                    try:
                        tracknumber = int(
                            str(id3.get("TRCK").text[0]).split("/")[0] or 0
                        )
                    except Exception:
                        tracknumber = 0
                if id3.get("TPOS"):
                    try:
                        discnumber = int(
                            str(id3.get("TPOS").text[0]).split("/")[0] or 0
                        )
                    except Exception:
                        discnumber = 0
                if id3.get("TSRC"):
                    isrc = str(id3.get("TSRC").text[0])
                # Provider IDs from TXXX frames
                def _get_txxx(desc: str):
                    frames = id3.getall("TXXX")
                    for fr in frames:
                        try:
                            if getattr(fr, 'desc', '') == desc and fr.text:
                                return str(fr.text[0])
                        except Exception:
                            continue
                    return None
                qobuz_id = _get_txxx("QOBUZ_TRACK_ID")
                tidal_id = _get_txxx("TIDAL_TRACK_ID")
                apple_id = _get_txxx("APPLE_TRACK_ID")
            except Exception:
                return None

        # MP4/M4A freeform atoms (----:com.apple.iTunes:<NAME>)
        try:
            if file_path.suffix.lower() == ".m4a":
                mp4 = MP4(file_path)
                def _get_ff(name: str):
                    key = f"----:com.apple.iTunes:{name}"
                    val = mp4.tags.get(key)
                    if val and isinstance(val, list) and len(val) > 0:
                        raw = val[0]
                        try:
                            return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                        except Exception:
                            return None
                    return None
                if 'qobuz_id' not in locals() or qobuz_id is None:
                    qobuz_id = _get_ff("QOBUZ_TRACK_ID")
                if 'tidal_id' not in locals() or tidal_id is None:
                    tidal_id = _get_ff("TIDAL_TRACK_ID")
                if 'apple_id' not in locals() or apple_id is None:
                    apple_id = _get_ff("APPLE_TRACK_ID")
                if not isrc:
                    isrc = _get_ff("ISRC")
        except Exception:
            pass

        track = Track(
            title=title,
            artist=artist,
            album=album,
            albumartist=albumartist,
            tracknumber=tracknumber,
            discnumber=discnumber,
            isrc=isrc,
            qobuz_id=locals().get("qobuz_id"),
            tidal_id=locals().get("tidal_id"),
            apple_id=locals().get("apple_id"),
            duration=duration,
            path=str(file_path.resolve()),
            hash=compute_hash(file_path) if verify else None,
            last_modified=file_path.stat().st_mtime,
        )
        return track
    except Exception as e:
        console.print(f"[red]Error indexing {file_path}: {e}[/red]")
        return None


def refresh_library(conn: sqlite3.Connection, library_root: Path, verify: bool = False):
    """Performs an incremental scan of the library and updates the database."""
    console.print(f"Scanning [blue]{library_root}[/blue] for changes...")

    db_tracks = {track.path: track for track in get_all_tracks(conn)}
    disk_paths = {str(p.resolve()) for p in scan_library_paths(library_root)}

    # Find new, deleted, and potentially modified files
    new_paths = disk_paths - set(db_tracks.keys())
    deleted_paths = set(db_tracks.keys()) - disk_paths
    existing_paths = disk_paths.intersection(db_tracks.keys())

    # Process deletions
    if deleted_paths:
        console.print(f"[yellow]Found {len(deleted_paths)} deleted files.[/yellow]")
        for path in deleted_paths:
            remove_track_by_path(conn, path)

    # Process new files
    if new_paths:
        console.print(f"[green]Found {len(new_paths)} new files.[/green]")
        for path_str in new_paths:
            track_data = index_file(Path(path_str), verify=verify)
            if track_data:
                insert_track(conn, track_data)

    # Process existing files (check for modifications)
    updated_count = 0
    for path_str in existing_paths:
        path = Path(path_str)
        db_track = db_tracks[path_str]

        is_modified = False
        if verify:
            # Verification is slow but thorough: re-hash and compare
            current_hash = compute_hash(path)
            if current_hash != db_track.hash:
                is_modified = True
        else:
            # Default is fast: check modification time
            if path.stat().st_mtime > (db_track.last_modified or 0):
                is_modified = True

        if is_modified:
            updated_count += 1
            track_data = index_file(path, verify=verify)
            if track_data:
                insert_track(conn, track_data)  # Upsert handles the update

    if updated_count:
        console.print(f"[cyan]Found {updated_count} modified files.[/cyan]")

    console.print("Scan complete.")


def get_library_stats(db_path: Path) -> dict:
    """Retrieves statistics from the library database."""
    if not db_path.exists():
        return {"error": "Database not found. Please run `fla lib index` first."}

    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        stats = {
            "Total Tracks": cur.execute("SELECT COUNT(*) FROM tracks").fetchone()[0],
            "Total Albums": cur.execute(
                "SELECT COUNT(DISTINCT album) FROM tracks"
            ).fetchone()[0],
            "Total Artists": cur.execute(
                "SELECT COUNT(DISTINCT artist) FROM tracks"
            ).fetchone()[0],
            "Tracks with ISRC": cur.execute(
                "SELECT COUNT(*) FROM tracks WHERE isrc IS NOT NULL"
            ).fetchone()[0],
            "Tracks with Hash": cur.execute(
                "SELECT COUNT(*) FROM tracks WHERE hash IS NOT NULL"
            ).fetchone()[0],
        }
        conn.close()
        return stats
    except sqlite3.Error as e:
        return {"error": f"Database error: {e}"}
