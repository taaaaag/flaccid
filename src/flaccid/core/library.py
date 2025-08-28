"""
Core logic for library management.

This module contains functions for scanning the filesystem, computing hashes,
extracting metadata, and performing incremental updates to the library database.
"""
import hashlib
import sqlite3
from pathlib import Path

import mutagen
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
    return [p for p in library_root.rglob("*") if p.suffix.lower() in audio_exts and p.is_file()]

def index_file(file_path: Path, verify: bool = False) -> Track | None:
    """Extracts metadata from a single audio file and returns a Track object."""
    try:
        audio = mutagen.File(file_path, easy=True)
        if not audio:
            return None

        def get_tag(key, default=None):
            val = audio.get(key, [default])
            return val[0] if val else default

        track = Track(
            title=get_tag("title", file_path.stem),
            artist=get_tag("artist", "Unknown Artist"),
            album=get_tag("album", "Unknown Album"),
            albumartist=get_tag("albumartist"),
            tracknumber=int(get_tag("tracknumber", "0").split('/')[0]),
            discnumber=int(get_tag("discnumber", "0").split('/')[0]),
            isrc=get_tag("isrc"),
            duration=int(audio.info.length) if audio.info else None,
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
                insert_track(conn, track_data) # Upsert handles the update
    
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
            "Total Albums": cur.execute("SELECT COUNT(DISTINCT album) FROM tracks").fetchone()[0],
            "Total Artists": cur.execute("SELECT COUNT(DISTINCT artist) FROM tracks").fetchone()[0],
            "Tracks with ISRC": cur.execute("SELECT COUNT(*) FROM tracks WHERE isrc IS NOT NULL").fetchone()[0],
            "Tracks with Hash": cur.execute("SELECT COUNT(*) FROM tracks WHERE hash IS NOT NULL").fetchone()[0],
        }
        conn.close()
        return stats
    except sqlite3.Error as e:
        return {"error": f"Database error: {e}"}
