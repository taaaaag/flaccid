"""
Database management using the built-in `sqlite3` module.

This module defines the data models (`Album`, `Track`) for the library and provides
all the necessary functions for interacting with the SQLite database. It handles
database initialization, connection management, and inserting/updating records.

It uses standard `sqlite3` to avoid heavy dependencies like SQLAlchemy, keeping
the application lightweight and portable.
"""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple

from rich.console import Console

console = Console()

# Python 3.12 deprecates the default datetime adapter; register explicit adapter.
sqlite3.register_adapter(datetime, lambda d: d.isoformat())

# --- Data Models ---


@dataclass
class Album:
    """Dataclass representing an album in the library."""

    id: Optional[int] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    albumartist: Optional[str] = None
    release_date: Optional[str] = None
    upc: Optional[str] = None
    qobuz_id: Optional[str] = None
    apple_id: Optional[str] = None
    tidal_id: Optional[str] = None
    path: Optional[str] = None
    added_at: datetime = datetime.now()


@dataclass
class Track:
    """Dataclass representing a track in the library."""

    id: Optional[int] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    albumartist: Optional[str] = None
    tracknumber: Optional[int] = None
    discnumber: Optional[int] = None
    duration: Optional[int] = None
    isrc: Optional[str] = None
    qobuz_id: Optional[str] = None
    apple_id: Optional[str] = None
    tidal_id: Optional[str] = None
    path: Optional[str] = None
    hash: Optional[str] = None
    last_modified: Optional[float] = None
    added_at: datetime = datetime.now()


# --- Database Initialization and Connection ---


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    """Establishes a connection to the SQLite database."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        console.print(f"[red]Database connection error: {e}[/red]")
        raise


def init_db(conn: sqlite3.Connection):
    """Creates the database tables (`albums`, `tracks`) if they don't exist."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT,
                album TEXT,
                albumartist TEXT,
                tracknumber INTEGER,
                discnumber INTEGER,
                duration INTEGER,
                isrc TEXT,
                qobuz_id TEXT,
                apple_id TEXT,
                tidal_id TEXT,
                path TEXT NOT NULL UNIQUE,
                hash TEXT,
                last_modified REAL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_path ON tracks (path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_album ON tracks (album)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_artist ON tracks (artist)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_isrc ON tracks (isrc)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_qobuz ON tracks (qobuz_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_tidal ON tracks (tidal_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_apple ON tracks (apple_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_hash ON tracks (hash)")

        # Optional FTS5 index for fast search over title/artist/album.
        # Use content-based FTS so rows stay in sync with triggers.
        try:
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
                    title, artist, album,
                    content='tracks', content_rowid='id'
                )
                """
            )
            # Triggers to keep FTS in sync
            cur.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS tracks_ai AFTER INSERT ON tracks BEGIN
                    INSERT INTO tracks_fts(rowid, title, artist, album)
                    VALUES (new.id, new.title, new.artist, new.album);
                END;
                CREATE TRIGGER IF NOT EXISTS tracks_ad AFTER DELETE ON tracks BEGIN
                    INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album)
                    VALUES ('delete', old.id, old.title, old.artist, old.album);
                END;
                CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE ON tracks BEGIN
                    INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album)
                    VALUES ('delete', old.id, old.title, old.artist, old.album);
                    INSERT INTO tracks_fts(rowid, title, artist, album)
                    VALUES (new.id, new.title, new.artist, new.album);
                END;
                """
            )
        except sqlite3.Error:
            # FTS5 may be unavailable; continue without it
            pass
        # Auxiliary table for multiple external IDs per track
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS track_ids (
                id INTEGER PRIMARY KEY,
                track_rowid INTEGER NOT NULL,
                namespace TEXT NOT NULL,
                external_id TEXT NOT NULL,
                preferred INTEGER DEFAULT 0,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(namespace, external_id),
                FOREIGN KEY(track_rowid) REFERENCES tracks(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_track_ids_track ON track_ids (track_rowid)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_track_ids_ns ON track_ids (namespace)"
        )
        # Optional album-level identifiers without creating a full albums table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS album_ids (
                id INTEGER PRIMARY KEY,
                albumartist TEXT,
                album TEXT,
                date TEXT,
                namespace TEXT NOT NULL,
                external_id TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(albumartist, album, date, namespace, external_id)
            )
            """
        )
        # A convenience view that picks the best available identifier per track.
        # Preference order: mb:recording > isrc > qobuz > tidal > apple > hash:sha1
        try:
            cur.execute(
                """
                CREATE VIEW IF NOT EXISTS track_best_identifier AS
                SELECT
                    t.id AS track_id,
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM track_ids i
                            WHERE i.track_rowid = t.id AND i.namespace = 'mb:recording'
                        ) THEN 'mb:recording'
                        WHEN t.isrc IS NOT NULL THEN 'isrc'
                        WHEN t.qobuz_id IS NOT NULL THEN 'qobuz'
                        WHEN t.tidal_id IS NOT NULL THEN 'tidal'
                        WHEN t.apple_id IS NOT NULL THEN 'apple'
                        WHEN t.hash IS NOT NULL THEN 'hash:sha1'
                        ELSE NULL
                    END AS namespace,
                    COALESCE(
                        (SELECT external_id FROM track_ids i WHERE i.track_rowid = t.id AND i.namespace = 'mb:recording' LIMIT 1),
                        t.isrc,
                        t.qobuz_id,
                        t.tidal_id,
                        t.apple_id,
                        t.hash
                    ) AS external_id
                FROM tracks t
                """
            )
        except Exception:
            pass
        conn.commit()
    except sqlite3.Error as e:
        console.print(f"[red]Database initialization error: {e}[/red]")
        raise


# --- Database Operations ---


def get_all_tracks(conn: sqlite3.Connection) -> list[Track]:
    """Fetches all tracks from the database and returns them as Track objects."""
    tracks = []
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tracks")
        for row in cur.fetchall():
            tracks.append(Track(**dict(row)))
    except sqlite3.Error as e:
        console.print(f"[red]Failed to fetch tracks: {e}[/red]")
    return tracks


def remove_track_by_path(conn: sqlite3.Connection, path: str):
    """Removes a track from the database by its file path."""
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM tracks WHERE path = ?", (path,))
        conn.commit()
    except sqlite3.Error as e:
        console.print(f"[red]Failed to remove track {path}: {e}[/red]")


def insert_track(conn: sqlite3.Connection, track: Track) -> Optional[int]:
    """Inserts or updates a track in the database."""
    track_dict = asdict(track)
    track_dict.pop("id", None)

    columns = ", ".join(track_dict.keys())
    placeholders = ", ".join([f":{key}" for key in track_dict.keys()])

    update_clauses = ", ".join(
        [f"{key}=excluded.{key}" for key in track_dict if key != "path"]
    )
    sql = f"INSERT INTO tracks ({columns}) VALUES ({placeholders}) ON CONFLICT(path) DO UPDATE SET {update_clauses}"

    try:
        cur = conn.cursor()
        cur.execute(sql, track_dict)
        conn.commit()
        # Always return the row id for the path (lastrowid can be 0 on update)
        row = cur.execute(
            "SELECT id FROM tracks WHERE path = ?", (track.path,)
        ).fetchone()
        return row[0] if row else None
    except sqlite3.Error as e:
        console.print(f"[red]Failed to insert track {track.path}: {e}[/red]")
        return None


def upsert_track_id(
    conn: sqlite3.Connection,
    track_rowid: int,
    namespace: str,
    external_id: str,
    preferred: bool = False,
) -> None:
    """Upserts a single external ID for a given track."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO track_ids (track_rowid, namespace, external_id, preferred)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, external_id) DO UPDATE SET
                track_rowid=excluded.track_rowid,
                preferred=CASE WHEN excluded.preferred=1 THEN 1 ELSE track_ids.preferred END
            """,
            (track_rowid, namespace, external_id, 1 if preferred else 0),
        )
        conn.commit()
    except sqlite3.Error as e:
        console.print(
            f"[yellow]Warning: could not upsert track_id {namespace}:{external_id}: {e}[/yellow]"
        )


def upsert_track_ids(
    conn: sqlite3.Connection,
    track_rowid: int,
    ids: Iterable[Tuple[str, str]],
    preferred_ns: set[str] | None = None,
) -> None:
    preferred_ns = preferred_ns or set()
    for ns, ext_id in ids:
        if not ns or not ext_id:
            continue
        upsert_track_id(conn, track_rowid, ns, ext_id, preferred=(ns in preferred_ns))


def upsert_album_id(
    conn: sqlite3.Connection,
    albumartist: Optional[str],
    album: Optional[str],
    date: Optional[str],
    namespace: str,
    external_id: str,
) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO album_ids (albumartist, album, date, namespace, external_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(albumartist, album, date, namespace, external_id) DO NOTHING
            """,
            (albumartist, album, date, namespace, external_id),
        )
        conn.commit()
    except sqlite3.Error as e:
        console.print(
            f"[yellow]Warning: could not upsert album_id {namespace}:{external_id}: {e}[/yellow]"
        )
