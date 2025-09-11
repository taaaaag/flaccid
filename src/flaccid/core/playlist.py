"""
Core logic for parsing, matching, and exporting playlists.
"""

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz
from rich.console import Console
from rich.progress import track

from .config import get_settings

# from .config import get_settings  # unused
from .database import get_db_connection

console = Console()


@dataclass
class PlaylistTrack:
    """Represents a track from a parsed playlist file."""

    title: str = ""
    artist: str = ""
    album: str = ""
    duration: Optional[int] = None
    isrc: Optional[str] = None
    source: str = ""


@dataclass
class MatchResult:
    """Represents the result of matching a single playlist track against the library."""

    input_track: "PlaylistTrack"
    matched_track: Optional[Dict[str, Any]] = None
    match_score: float = 0.0
    match_reasons: List[str] = field(default_factory=list)
    file_path: Optional[Path] = None


class PlaylistParser:
    """Parses various playlist file formats into a list of PlaylistTrack objects."""

    def parse_file(self, file_path: Path) -> List[PlaylistTrack]:
        """Parse a playlist file based on its format."""
        suffix = file_path.suffix.lower()
        if suffix == ".json":
            return self._parse_json(file_path)
        elif suffix in [".m3u", ".m3u8"]:
            return self._parse_m3u(file_path)
        elif suffix == ".txt":
            return self._parse_txt(file_path)
        elif suffix == ".csv":
            return self._parse_csv(file_path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}")

    def _parse_json(self, file_path: Path) -> List[PlaylistTrack]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tracks: List[PlaylistTrack] = []

        # Support multiple shapes:
        # 1) A bare list of track dicts
        # 2) A dict containing a 'tracks' list
        # 3) A list of dicts where each may be a track dict or contain 'tracks'
        def to_track(d: dict) -> PlaylistTrack:
            return PlaylistTrack(
                title=d.get("title") or d.get("track", ""),
                artist=d.get("artist", ""),
                album=d.get("album", ""),
                isrc=d.get("isrc"),
                source=f"JSON: {file_path.name}",
            )

        if isinstance(data, dict):
            if "tracks" in data and isinstance(data["tracks"], list):
                for td in data["tracks"]:
                    if isinstance(td, dict):
                        tracks.append(to_track(td))
            else:
                # Single track dict
                tracks.append(to_track(data))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "tracks" in item and isinstance(item["tracks"], list):
                    for td in item["tracks"]:
                        if isinstance(td, dict):
                            tracks.append(to_track(td))
                elif isinstance(item, dict):
                    tracks.append(to_track(item))

        return tracks

    def _parse_m3u(self, file_path: Path) -> List[PlaylistTrack]:
        tracks = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#EXTINF"):
                    info = line.split(",", 1)[1].strip()
                    artist, title = info.split(" - ", 1) if " - " in info else ("", info)
                    tracks.append(
                        PlaylistTrack(title=title, artist=artist, source=f"M3U: {file_path.name}")
                    )
        return tracks

    def _parse_txt(self, file_path: Path) -> List[PlaylistTrack]:
        tracks = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if " - " in line:
                    artist, title = line.split(" - ", 1)
                    tracks.append(
                        PlaylistTrack(
                            artist=artist.strip(),
                            title=title.strip(),
                            source=f"TXT: {file_path.name}",
                        )
                    )
        return tracks

    def _parse_csv(self, file_path: Path) -> List[PlaylistTrack]:
        tracks: List[PlaylistTrack] = []
        with open(file_path, "r", encoding="utf-8-sig") as f:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(f.read(2048), delimiters=",;\t")
            f.seek(0)
            reader = csv.DictReader(f, dialect=dialect)
            field_map = {name.lower(): name for name in (reader.fieldnames or [])}

            def get_val(row: dict, *keys: str) -> str:
                for k in keys:
                    if field_map.get(k) and row.get(field_map[k]):
                        return str(row[field_map[k]]).strip()
                return ""

            for row in reader:
                tracks.append(
                    PlaylistTrack(
                        title=get_val(row, "title", "track"),
                        artist=get_val(row, "artist"),
                        album=get_val(row, "album"),
                        isrc=get_val(row, "isrc") or None,
                        source=f"CSV: {file_path.name}",
                    )
                )
        return tracks


class PlaylistMatcher:
    """Matches playlist tracks against the local library database."""

    def __init__(self, db_path: Path, service: str = "all"):
        self.conn = get_db_connection(db_path)
        self.conn.create_function("normalize", 1, self._normalize)
        self.conn.create_function("fuzz_ratio", 2, lambda s1, s2: fuzz.ratio(s1 or "", s2 or ""))
        # Matching strategy: 'isrc', 'fuzzy', 'path', or 'all'
        self.service = (service or "all").lower()

    def __del__(self):
        if self.conn:
            self.conn.close()

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        t = text.lower()
        t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
        t = re.sub(r"\s*\([^)]*\)|\s*\[[^\]]*\]", " ", t)
        t = re.sub(
            r"\b(original mix|album version|radio edit|feat\.?|featuring|remastered|extended)\b",
            " ",
            t,
        )
        t = re.sub(r"[\-_/,:;~]+", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _get_candidates(self, track: PlaylistTrack) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = """
            SELECT *, fuzz_ratio(?, normalize(title)) as title_score, fuzz_ratio(?, normalize(artist)) as artist_score
            FROM tracks
            WHERE title_score > 60 OR artist_score > 60
            ORDER BY (0.6 * title_score + 0.4 * artist_score) DESC
            LIMIT 20
        """
        cursor.execute(query, (self._normalize(track.title), self._normalize(track.artist)))
        return [dict(row) for row in cursor.fetchall()]

    def _calculate_score(self, track: PlaylistTrack, candidate: Dict[str, Any]) -> float:
        title_score = fuzz.ratio(self._normalize(track.title), self._normalize(candidate["title"]))
        artist_score = fuzz.ratio(
            self._normalize(track.artist), self._normalize(candidate["artist"])
        )
        return 0.6 * title_score + 0.4 * artist_score

    def match_playlist(self, playlist_tracks: List[PlaylistTrack]) -> List[MatchResult]:
        """
        Match a list of PlaylistTrack items, applying both fuzzy and path-based fallback.
        """
        results: List[MatchResult] = []
        for item in track(playlist_tracks, description="Matching tracks..."):
            result = self.match_one(item)
            results.append(result)
        return results

    def match_one(self, track: PlaylistTrack) -> MatchResult:
        """
        Match a single PlaylistTrack and return its MatchResult.
        """
        # Determine matching strategy
        strategy = (self.service or "all").lower()

        # Priority 1: exact ISRC match if enabled
        if strategy in ("isrc", "all") and track.isrc:
            # split on semicolon, comma, slash, pipe, or whitespace
            codes = re.split(r"[;,/\\|\s]+", track.isrc)
            for code in codes:
                code = code.strip()
                if not code:
                    continue
                cursor = self.conn.cursor()
                cursor.execute("SELECT * FROM tracks WHERE isrc = ? LIMIT 1", (code,))
                row = cursor.fetchone()
                if row:
                    candidate = dict(row)
                    raw_path = candidate.get("path")
                    file_path = Path(raw_path) if raw_path else None
                    return MatchResult(
                        input_track=track,
                        matched_track=candidate,
                        match_score=100.0,
                        match_reasons=[f"isrc_match:{code}"],
                        file_path=file_path,
                    )

        # Priority 2: fuzzy title/artist match if enabled
        if strategy in ("fuzzy", "all"):
            candidates = self._get_candidates(track)
            best_match, best_score = None, 0.0
            if candidates:
                best_match = candidates[0]
                best_score = self._calculate_score(track, best_match)
            if best_score > 85 and isinstance(best_match, dict):
                raw_path = best_match.get("path")
                file_path = Path(raw_path) if raw_path else None
                return MatchResult(
                    input_track=track,
                    matched_track=best_match,
                    match_score=best_score,
                    file_path=file_path,
                )

        # Priority 3: path-based fallback if enabled
        if strategy in ("path", "all"):
            try:
                cursor = self.conn.cursor()
                pattern = f"%{track.title.strip().lower()}%"
                cursor.execute("SELECT * FROM tracks WHERE lower(path) LIKE ? LIMIT 1", (pattern,))
                row = cursor.fetchone()
                if row:
                    candidate = dict(row)
                    raw_path = candidate.get("path")
                    fallback_path = Path(raw_path) if raw_path else None
                    return MatchResult(
                        input_track=track,
                        matched_track=candidate,
                        match_score=0.0,
                        match_reasons=["path_fallback"],
                        file_path=fallback_path,
                    )
            except Exception:
                pass

        return MatchResult(input_track=track)


class PlaylistExporter:
    """Export matched playlist results to various formats (M3U for now)."""

    def export(self, results: List[MatchResult], output: Path, format: str = "m3u") -> None:
        fmt = (format or "m3u").lower()
        if fmt not in ("m3u", "m3u8"):
            raise ValueError(f"Unsupported playlist export format: {format}")
        lines: List[str] = ["#EXTM3U"]
        for r in results:
            # Only export entries with a concrete file path
            if not r.file_path:
                continue
            title = None
            artist = None
            duration = None
            try:
                mt = r.matched_track or {}
                title = mt.get("title")
                artist = mt.get("artist")
                duration = mt.get("duration")
            except Exception:
                pass
            # Duration in seconds; default to 0 if unavailable
            dur_val = 0
            try:
                if duration is not None:
                    dur_val = int(duration)
            except Exception:
                dur_val = 0
            name = f"{(artist or '').strip()} - {(title or '').strip()}".strip(" -")
            lines.append(f"#EXTINF:{dur_val},{name}")
            # Write path as-is
            lines.append(str(r.file_path))
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
