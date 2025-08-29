"""
Library management commands for FLACCID (`fla lib`).

This module provides tools to manage the local music library, including:
- Scanning directories for audio files.
- Indexing metadata into a central database.
- Displaying statistics about the collection.
"""

import sqlite3
import json
import time
import requests
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from ..core.config import get_settings
from ..core.database import (
    get_db_connection,
    init_db,
    insert_track,
    upsert_track_id,
    upsert_album_id,
)
from ..core.library import (
    get_library_stats,
    index_file,
    refresh_library,
    scan_library_paths,
)

console = Console()
app = typer.Typer(
    no_args_is_help=True,
    help="Manage your local music library (scan, index, view stats).",
)


@app.command("scan")
def lib_scan(
    path: Optional[Path] = typer.Option(
        None, "--path", "-p", help="Directory to scan (defaults to library path)"
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Continuously watch the library for changes."
    ),
    verify: bool = typer.Option(
        False, "--verify", help="Verify file integrity via hashing during scan."
    ),
):
    """
    Scan the library for new, changed, or deleted files and update the database.

    This performs a quick, incremental scan by default, checking file modification
    times. Use --verify for a slower but more thorough hash-based check.
    Use --watch to keep the scanner running and update automatically.
    """
    settings = get_settings()
    scan_path = (path or settings.library_path).resolve()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")

    if not scan_path.is_dir():
        raise typer.Exit(f"[red]Error: Path is not a directory: {scan_path}[/red]")

    def run_scan():
        """Helper function to run a single scan pass."""
        try:
            conn = get_db_connection(db_path)
            init_db(conn)
            refresh_library(conn, scan_path, verify=verify)
            conn.close()
        except Exception as e:
            console.print(f"[red]An error occurred during scan: {e}[/red]")

    # Run the initial scan immediately
    run_scan()

    if watch:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            console.print(
                "[red]Error: `watchdog` is not installed. Please run `pip install watchdog`.[/red]"
            )
            raise typer.Exit(1)

        console.print(
            f"[cyan]Watching {scan_path} for changes... (Press Ctrl+C to stop)[/cyan]"
        )

        class ScanHandler(FileSystemEventHandler):
            def on_any_event(self, event):
                # Simple approach: re-run the full incremental scan on any change.
                # A more advanced implementation could debounce or handle specific events.
                if event.is_directory:
                    return
                console.print(f"\n[yellow]Change detected: {event.src_path}[/yellow]")
                run_scan()

        event_handler = ScanHandler()
        observer = Observer()
        observer.schedule(event_handler, str(scan_path), recursive=True)
        observer.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            console.print("\n[yellow]Watcher stopped.[/yellow]")
        observer.join()


@app.command("index")
def lib_index(
    path: Optional[Path] = typer.Option(
        None, "-p", "--path", help="Directory to index (defaults to your library path)."
    ),
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        help="Delete the existing database and rebuild from scratch.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview files to index without writing to the database.",
    ),
):
    """
    Scan a directory and store metadata for all audio files in the database.

    This is the core command for building your library. It reads the tags from
    each audio file, computes a file hash, and saves the information to the
    `flaccid.db` file in your library root.
    """
    settings = get_settings()
    scan_path = (path or settings.library_path).resolve()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")

    if rebuild and db_path.exists():
        console.print(
            f"[yellow]--rebuild specified. Deleting existing database at {db_path}[/yellow]"
        )
        db_path.unlink()

    conn = get_db_connection(db_path)
    init_db(conn)

    files_to_index = scan_library_paths(scan_path)
    if dry_run:
        console.print(
            f"[cyan]Dry-run:[/cyan] Would index {len(files_to_index)} files from {scan_path}"
        )
        for p in files_to_index[:50]:
            console.print(f"  - {p}")
        if len(files_to_index) > 50:
            console.print(f"  ... and {len(files_to_index)-50} more")
        conn.close()
        return
    if not files_to_index:
        conn.close()
        raise typer.Exit("No audio files found to index.")

    with Progress(console=console) as progress:
        task = progress.add_task("[cyan]Indexing...[/cyan]", total=len(files_to_index))
        for file_path in files_to_index:
            track_data = index_file(
                file_path, verify=True
            )  # Always verify on full index
            if track_data:
                insert_track(conn, track_data)
            progress.update(task, advance=1, description=f"Indexing {file_path.name}")

    conn.close()
    console.print("\n[green]✅ Library indexing complete![/green]")


@app.command("stats")
def lib_stats(json_output: bool = typer.Option(False, "--json", help="Output JSON")):
    """
    Show high-level statistics about the indexed music library.
    """
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")

    stats = get_library_stats(db_path)

    if stats.get("error"):
        raise typer.Exit(f"[red]Error:[/red] {stats['error']}")

    if json_output:
        typer.echo(json.dumps(stats))
        return

    table = Table(title="FLACCID Library Statistics")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    for key, value in stats.items():
        table.add_row(key, str(value))

    console.print(table)


@app.command("vacuum")
def lib_vacuum():
    """Optimize the library database (VACUUM + ANALYZE)."""
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")
    if not db_path.exists():
        raise typer.Exit("No database found. Run `fla lib index` first.")
    with sqlite3.connect(db_path) as conn:
        conn.execute("VACUUM")
        conn.execute("ANALYZE")
    console.print("[green]✅ Database optimized.[/green]")


@app.command("enrich-mb")
def lib_enrich_mb(
    limit: int = typer.Option(100, "--limit", help="Max tracks to enrich this run"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    rps: float = typer.Option(1.0, "--rps", help="Max requests/sec to MusicBrainz"),
):
    """Enrich tracks with MusicBrainz IDs using ISRC after the fact.

    For each track missing an MB recording ID, queries MusicBrainz by ISRC and
    stores the best match as `track_ids(namespace='mb:recording')`. Also stores
    album-level IDs when available (mb:release, mb:release-group, UPC barcode).
    """
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")
    conn = get_db_connection(db_path)
    init_db(conn)

    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT t.id, t.title, t.artist, t.album, t.albumartist, t.isrc, t.duration
        FROM tracks t
        WHERE t.isrc IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM track_ids i
              WHERE i.track_rowid = t.id AND i.namespace = 'mb:recording'
          )
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not rows:
        console.print("[green]No tracks need MB enrichment.[/green]")
        return

    console.print(f"[cyan]Enriching up to {len(rows)} tracks via MusicBrainz (by ISRC)...[/cyan]")
    base = "https://musicbrainz.org/ws/2/recording"
    headers = {
        "User-Agent": "flaccid/0.1 (+https://github.com/; CLI enrichment)",
        "Accept": "application/json",
    }
    delay = max(1.0 / max(rps, 0.1), 0.0)
    added = 0

    def pick_best(rec_list: list, duration: int | None):
        if not rec_list:
            return None
        def score_key(r: dict):
            s = int(r.get("score") or 0)
            d = None
            try:
                if duration and r.get("length"):
                    d = abs(int(r.get("length")) / 1000 - int(duration))
            except Exception:
                d = None
            # Higher score first, then smaller duration diff
            return (-s, d if d is not None else 999999)
        return sorted(rec_list, key=score_key)[0]

    for (rowid, title, artist, album, albumartist, isrc, duration) in rows:
        try:
            params = {"query": f"isrc:{isrc}", "fmt": "json", "inc": "releases"}
            resp = requests.get(base, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json() or {}
            recs = data.get("recordings") or []
            best = pick_best(recs, duration)
            if not best:
                continue
            rec_id = best.get("id")
            if not rec_id:
                continue
            if dry_run:
                console.print(f"would add mb:recording {rec_id} for '{artist} - {title}'")
            else:
                upsert_track_id(conn, rowid, "mb:recording", rec_id, preferred=True)
                added += 1
            # Album-level IDs
            rels = best.get("releases") or []
            if rels:
                rel = rels[0]
                rel_id = rel.get("id")
                rg = rel.get("release-group") or {}
                rg_id = rg.get("id")
                barcode = rel.get("barcode")
                if not dry_run:
                    if rel_id:
                        upsert_album_id(conn, albumartist, album, None, "mb:release", rel_id)
                    if rg_id:
                        upsert_album_id(conn, albumartist, album, None, "mb:release-group", rg_id)
                    if barcode:
                        upsert_album_id(conn, albumartist, album, None, "upc", barcode)
            time.sleep(delay)
        except requests.RequestException as e:
            console.print(f"[yellow]MB request failed for ISRC {isrc}: {e}[/yellow]")
            time.sleep(delay)
            continue
        except Exception as e:
            console.print(f"[yellow]Skipping '{artist} - {title}': {e}[/yellow]")
            continue

    if not dry_run:
        console.print(f"[green]✅ Added {added} MusicBrainz recording IDs.[/green]")


@app.command("search")
def lib_search(
    query: str = typer.Argument(..., help="Search text for title/artist/album"),
    limit: int = typer.Option(25, "--limit", help="Max results to return"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON results"),
):
    """Search the library using FTS (if available), else fallback to LIKE.

    Matches title OR artist OR album.
    """
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")
    if not db_path.exists():
        raise typer.Exit("No database found. Run `fla lib index` first.")
    with sqlite3.connect(db_path) as conn:
        has_fts = bool(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tracks_fts'"
            ).fetchone()
        )
        if has_fts:
            sql = (
                "SELECT t.title, t.artist, t.album, t.path, bm25(tracks_fts) as rank "
                "FROM tracks_fts JOIN tracks t ON t.id = tracks_fts.rowid "
                "WHERE tracks_fts MATCH ? ORDER BY rank LIMIT ?"
            )
            rows = conn.execute(sql, (query, limit)).fetchall()
        else:
            like = f"%{query}%"
            sql = (
                "SELECT title, artist, album, path FROM tracks "
                "WHERE title LIKE ? OR artist LIKE ? OR album LIKE ? LIMIT ?"
            )
            rows = conn.execute(sql, (like, like, like, limit)).fetchall()
    results = [
        {"title": r[0], "artist": r[1], "album": r[2], "path": r[3]} for r in rows
    ]
    if json_output:
        typer.echo(
            json.dumps({"query": query, "count": len(results), "results": results})
        )
        return
    table = Table(title=f"Search results for '{query}'")
    table.add_column("Title", style="cyan")
    table.add_column("Artist", style="magenta")
    table.add_column("Album", style="green")
    table.add_column("Path", style="dim")
    for r in results:
        table.add_row(
            r["title"] or "", r["artist"] or "", r["album"] or "", r["path"] or ""
        )
    console.print(table)
