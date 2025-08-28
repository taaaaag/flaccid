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
from typing import Any, Optional

from rich.console import Console

console = Console()

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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT,
                album TEXT,
                albumartist TEXT,
                tracknumber INTEGER,
                discnumber INTEGER,
                duration INTEGER,
                isrc TEXT UNIQUE,
                qobuz_id TEXT UNIQUE,
                apple_id TEXT UNIQUE,
                tidal_id TEXT UNIQUE,
                path TEXT NOT NULL UNIQUE,
                hash TEXT UNIQUE,
                last_modified REAL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_track_path ON tracks (path)")
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

    update_clauses = ", ".join([f"{key}=excluded.{key}" for key in track_dict if key != 'path'])
    sql = f"INSERT INTO tracks ({columns}) VALUES ({placeholders}) ON CONFLICT(path) DO UPDATE SET {update_clauses}"

    try:
        cur = conn.cursor()
        cur.execute(sql, track_dict)
        conn.commit()
        return cur.lastrowid
    except sqlite3.Error as e:
        console.print(f"[red]Failed to insert track {track.path}: {e}[/red]")
        return None
