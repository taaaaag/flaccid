"""
Library management commands for FLACCID (`fla lib`).

This module provides tools to manage the local music library, including:
- Scanning directories for audio files.
- Indexing metadata into a central database.
- Displaying statistics about the collection.
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from ..core.config import get_settings
from ..core.database import get_db_connection, init_db, insert_track
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
def lib_stats():
    """
    Show high-level statistics about the indexed music library.
    """
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")

    stats = get_library_stats(db_path)

    if stats.get("error"):
        raise typer.Exit(f"[red]Error:[/red] {stats['error']}")

    table = Table(title="FLACCID Library Statistics")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    for key, value in stats.items():
        table.add_row(key, str(value))

    console.print(table)
