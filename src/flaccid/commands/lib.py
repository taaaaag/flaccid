"""
Library management commands for FLACCID (`fla lib`).

This module provides tools to manage the local music library, including:
- Scanning directories for audio files.
- Indexing metadata into a central database.
- Displaying statistics about the collection.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests
import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from ..core.config import get_settings
from ..core.database import (
    get_db_connection,
    init_db,
    insert_track,
    upsert_album_id,
    upsert_track_id,
    upsert_track_ids,
)
from ..core.library import (
    compute_hash,
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

    console.print(
        f"[cyan]Enriching up to {len(rows)} tracks via MusicBrainz (by ISRC)...[/cyan]"
    )
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

    for rowid, title, artist, album, albumartist, isrc, duration in rows:
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
                console.print(
                    f"would add mb:recording {rec_id} for '{artist} - {title}'"
                )
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
                        upsert_album_id(
                            conn, albumartist, album, None, "mb:release", rel_id
                        )
                    if rg_id:
                        upsert_album_id(
                            conn, albumartist, album, None, "mb:release-group", rg_id
                        )
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


@app.command("enrich-mb-fuzzy")
def lib_enrich_mb_fuzzy(
    limit: int = typer.Option(100, "--limit", help="Max tracks to enrich this run"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    rps: float = typer.Option(1.0, "--rps", help="Max requests/sec to MusicBrainz"),
    duration_tolerance: int = typer.Option(
        6, "--tolerance", help="Max seconds off duration"
    ),
    only_missing: bool = typer.Option(
        True, "--only-missing/--all", help="Only tracks without provider IDs/ISRC"
    ),
):
    """Fuzzy-enrich tracks with MusicBrainz IDs using title+artist matching.

    This complements ISRC-based enrichment by attempting a best-effort match on
    (title, artist) and optional duration tolerance.
    """
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")
    conn = get_db_connection(db_path)
    init_db(conn)

    cond_missing = (
        "AND t.isrc IS NULL AND t.qobuz_id IS NULL AND t.tidal_id IS NULL AND t.apple_id IS NULL"
        if only_missing
        else ""
    )
    cur = conn.cursor()
    rows = cur.execute(
        f"""
        SELECT t.id, t.title, t.artist, t.duration
        FROM tracks t
        WHERE t.title IS NOT NULL AND t.artist IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM track_ids i
              WHERE i.track_rowid = t.id AND i.namespace = 'mb:recording'
          )
          {cond_missing}
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not rows:
        console.print("[green]No tracks need fuzzy MB enrichment.[/green]")
        return

    console.print(
        f"[cyan]Fuzzy-enriching up to {len(rows)} tracks via MusicBrainz (title+artist)…[/cyan]"
    )
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

        # filter by duration tolerance if provided
        candidates = rec_list
        if duration and duration_tolerance is not None:
            try:
                candidates = [
                    r
                    for r in rec_list
                    if r.get("length") is None
                    or abs(int(r.get("length")) / 1000 - int(duration))
                    <= int(duration_tolerance)
                ] or rec_list
            except Exception:
                candidates = rec_list
        return sorted(candidates, key=score_key)[0]

    for rowid, title, artist, duration in rows:
        try:
            # Quote title/artist for better precision
            q = f'recording:"{title}" AND artist:"{artist}"'
            params = {"query": q, "fmt": "json", "limit": 5}
            resp = requests.get(base, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json() or {}
            recs = data.get("recordings") or []
            best = pick_best(recs, duration)
            if not best:
                time.sleep(delay)
                continue
            rec_id = best.get("id")
            if not rec_id:
                time.sleep(delay)
                continue
            if dry_run:
                console.print(
                    f"would add mb:recording {rec_id} for '{artist} - {title}' (fuzzy)"
                )
            else:
                upsert_track_id(conn, rowid, "mb:recording", rec_id, preferred=False)
                added += 1
            time.sleep(delay)
        except requests.RequestException as e:
            console.print(
                f"[yellow]MB request failed for '{artist} - {title}': {e}[/yellow]"
            )
            time.sleep(delay)
            continue
        except Exception as e:
            console.print(f"[yellow]Skipping '{artist} - {title}': {e}[/yellow]")
            continue

    if not dry_run:
        console.print(
            f"[green]✅ Added {added} fuzzy MusicBrainz recording IDs.[/green]"
        )


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


@app.command("ensure-ids")
def lib_ensure_ids(
    prefer: str = typer.Option(
        "mb:recording,isrc,qobuz,tidal,apple,hash:sha1",
        "--prefer",
        help="Comma list of identifier namespaces in priority order",
    ),
    compute_missing_hash: bool = typer.Option(
        True,
        "--compute-hash/--no-compute-hash",
        help="Compute file hash when no other IDs are present",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Limit number of tracks to process"
    ),
):
    """Ensure every track has at least one identifier recorded.

    Populates `track_ids` from provider IDs (Qobuz/Tidal/Apple), ISRC, and file hash.
    Sets a preferred ID per track according to `--prefer` precedence.
    """
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")
    conn = get_db_connection(db_path)
    init_db(conn)

    order = [p.strip() for p in prefer.split(",") if p.strip()]
    ns_rank = {ns: i for i, ns in enumerate(order)}

    cur = conn.cursor()
    sql = "SELECT id, path, isrc, qobuz_id, tidal_id, apple_id, hash FROM tracks"
    if limit is not None:
        sql += " LIMIT ?"
        rows = cur.execute(sql, (limit,)).fetchall()
    else:
        rows = cur.execute(sql).fetchall()

    updated = 0
    hashed = 0
    preferred_changed = 0

    for row in rows:
        tid = int(row[0])
        path = row[1]
        isrc = row[2]
        qid = row[3]
        tidl = row[4]
        aid = row[5]
        fh = row[6]

        # Gather existing ids for track
        existing = cur.execute(
            "SELECT namespace, external_id, preferred FROM track_ids WHERE track_rowid = ?",
            (tid,),
        ).fetchall()

        candidates: list[tuple[str, str]] = []
        if isrc:
            candidates.append(("isrc", str(isrc)))
        if qid:
            candidates.append(("qobuz", str(qid)))
        if tidl:
            candidates.append(("tidal", str(tidl)))
        if aid:
            candidates.append(("apple", str(aid)))

        # Ensure we have at least a hash-based id
        if not candidates and (compute_missing_hash or fh):
            if not fh and compute_missing_hash:
                try:
                    p = Path(path)
                    if p.exists():
                        fh = compute_hash(p)
                        cur.execute(
                            "UPDATE tracks SET hash = ? WHERE id = ?", (fh, tid)
                        )
                        conn.commit()
                        hashed += 1
                except Exception:
                    fh = None
            if fh:
                candidates.append(("hash:sha1", str(fh)))

        if not candidates and not existing:
            # Nothing we can do for this track
            continue

        # Upsert all candidates
        if candidates:
            upsert_track_ids(conn, tid, candidates)
            updated += 1

        # Determine preferred
        all_ids = cur.execute(
            "SELECT namespace, external_id, preferred FROM track_ids WHERE track_rowid = ?",
            (tid,),
        ).fetchall()
        # Current preferred
        current_pref = None
        for ns, ext_id, pref in all_ids:
            if int(pref or 0) == 1:
                current_pref = (ns, ext_id)
                break

        # Select best according to precedence
        def key_of(ns: str) -> int:
            return ns_rank.get(ns, 999)

        best = None
        for ns, ext_id, _ in all_ids:
            k = key_of(ns)
            if best is None or k < key_of(best[0]):
                best = (ns, ext_id)

        if best and best != current_pref:
            # Update flags atomically for this track
            cur.execute(
                "UPDATE track_ids SET preferred = CASE WHEN namespace = ? AND external_id = ? THEN 1 ELSE 0 END WHERE track_rowid = ?",
                (best[0], best[1], tid),
            )
            conn.commit()
            preferred_changed += 1

    console.print(
        f"[green]✅ Ensured identifiers for {updated} tracks[/green] (hashed {hashed}, changed preferred {preferred_changed})."
    )


@app.command("show-ids")
def lib_show_ids(
    limit: int = typer.Option(50, "--limit", help="Rows to display"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON"),
    missing_only: bool = typer.Option(
        False, "--missing", help="Only show tracks that rely on hash:sha1 as identifier"
    ),
):
    """List each track's best identifier along with path and basic tags."""
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")
    if not db_path.exists():
        raise typer.Exit("No database found. Run `fla lib index` first.")
    with sqlite3.connect(db_path) as conn:
        # Ensure schema objects (view) exist
        init_db(conn)
        if missing_only:
            rows = conn.execute(
                """
                SELECT t.title, t.artist, t.album, t.path, b.namespace, b.external_id
                FROM tracks t
                LEFT JOIN track_best_identifier b ON b.track_id = t.id
                WHERE b.namespace = 'hash:sha1'
                ORDER BY t.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT t.title, t.artist, t.album, t.path, b.namespace, b.external_id
                FROM tracks t
                LEFT JOIN track_best_identifier b ON b.track_id = t.id
                ORDER BY t.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    data = [
        {
            "title": r[0],
            "artist": r[1],
            "album": r[2],
            "path": r[3],
            "namespace": r[4],
            "id": r[5],
        }
        for r in rows
    ]
    if json_output:
        typer.echo(json.dumps({"count": len(data), "results": data}))
        return
    table = Table(title="Track Identifiers")
    table.add_column("Title", style="cyan")
    table.add_column("Artist", style="magenta")
    table.add_column("Album", style="green")
    table.add_column("Namespace", style="yellow")
    table.add_column("Identifier", style="white")
    for r in data:
        table.add_row(
            r["title"] or "",
            r["artist"] or "",
            r["album"] or "",
            r["namespace"] or "-",
            r["id"] or "-",
        )
    console.print(table)


@app.command("ids-stats")
def lib_ids_stats(
    json_output: bool = typer.Option(False, "--json", help="Output JSON"),
):
    """Show identifier coverage and distribution across the library."""
    settings = get_settings()
    db_path = settings.db_path or (settings.library_path / "flaccid.db")
    if not db_path.exists():
        raise typer.Exit("No database found. Run `fla lib index` first.")
    with sqlite3.connect(db_path) as conn:
        init_db(conn)
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        with_best = cur.execute(
            "SELECT COUNT(*) FROM track_best_identifier WHERE external_id IS NOT NULL"
        ).fetchone()[0]
        without_best = total - with_best
        ns_rows = cur.execute(
            "SELECT namespace, COUNT(*) FROM track_ids GROUP BY namespace ORDER BY COUNT(*) DESC"
        ).fetchall()
        # How many have no provider IDs nor ISRC
        none_provider = cur.execute(
            "SELECT COUNT(*) FROM tracks WHERE isrc IS NULL AND qobuz_id IS NULL AND tidal_id IS NULL AND apple_id IS NULL"
        ).fetchone()[0]
    data = {
        "total_tracks": total,
        "with_identifier": with_best,
        "without_identifier": without_best,
        "by_namespace": {r[0]: r[1] for r in ns_rows},
        "no_provider_or_isrc": none_provider,
    }
    if json_output:
        typer.echo(json.dumps(data))
        return
    table = Table(title="Identifier Coverage")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    for k in [
        "total_tracks",
        "with_identifier",
        "without_identifier",
        "no_provider_or_isrc",
    ]:
        table.add_row(k.replace("_", " ").title(), str(data[k]))
    console.print(table)
    if ns_rows:
        ns_table = Table(title="Identifiers by Namespace")
        ns_table.add_column("Namespace", style="yellow")
        ns_table.add_column("Count", style="white")
        for ns, cnt in ns_rows:
            ns_table.add_row(ns, str(cnt))
        console.print(ns_table)
