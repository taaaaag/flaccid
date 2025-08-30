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
                if (
                    isinstance(item, dict)
                    and "tracks" in item
                    and isinstance(item["tracks"], list)
                ):
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
                    artist, title = (
                        info.split(" - ", 1) if " - " in info else ("", info)
                    )
                    tracks.append(
                        PlaylistTrack(
                            title=title, artist=artist, source=f"M3U: {file_path.name}"
                        )
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

    def __init__(self, db_path: Path):
        self.conn = get_db_connection(db_path)
        self.conn.create_function("normalize", 1, self._normalize)
        self.conn.create_function(
            "fuzz_ratio", 2, lambda s1, s2: fuzz.ratio(s1 or "", s2 or "")
        )

    def __del__(self):
        if self.conn:
            self.conn.close()

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        t = text.lower()
        t = "".join(
            c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c)
        )
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
        cursor.execute(
            query, (self._normalize(track.title), self._normalize(track.artist))
        )
        return [dict(row) for row in cursor.fetchall()]

    def _calculate_score(
        self, track: PlaylistTrack, candidate: Dict[str, Any]
    ) -> float:
        title_score = fuzz.ratio(
            self._normalize(track.title), self._normalize(candidate["title"])
        )
        artist_score = fuzz.ratio(
            self._normalize(track.artist), self._normalize(candidate["artist"])
        )
        return 0.6 * title_score + 0.4 * artist_score

    def match_playlist(self, playlist_tracks: List[PlaylistTrack]) -> List[MatchResult]:
        results = []
        for item in track(playlist_tracks, description="Matching tracks..."):
            candidates = self._get_candidates(item)
            best_match, best_score = None, 0.0
            if candidates:
                best_match = candidates[0]
                best_score = self._calculate_score(item, best_match)

            if best_score > 85:  # High-confidence threshold
                results.append(
                    MatchResult(
                        input_track=item,
                        matched_track=best_match,
                        match_score=best_score,
                        file_path=Path(best_match["path"]),
                    )
                )
            else:
                results.append(MatchResult(input_track=item))
        return results


class PlaylistExporter:
    """Exports matched playlist results to various file formats."""

    def export(self, results: List[MatchResult], output_path: Path, format: str):
        if format == "m3u":
            self._export_m3u(results, output_path)
        elif format == "json":
            self._export_json(results, output_path)
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def _export_m3u(self, results: List[MatchResult], output_path: Path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for result in results:
                if result.file_path and result.file_path.exists():
                    duration = (
                        result.matched_track.get("duration", -1)
                        if result.matched_track
                        else -1
                    )
                    artist = (
                        result.matched_track.get("artist", "")
                        if result.matched_track
                        else result.input_track.artist
                    )
                    title = (
                        result.matched_track.get("title", "")
                        if result.matched_track
                        else result.input_track.title
                    )
                    f.write(f"#EXTINF:{duration},{artist} - {title}\n")
                    f.write(f"{result.file_path.resolve()}\n")

    def _export_json(self, results: List[MatchResult], output_path: Path):
        report = {
            "exported_at": datetime.now().isoformat(),
            "results": [
                {
                    "input_track": asdict(r.input_track),
                    "matched_track": r.matched_track,
                    "match_score": r.match_score,
                    "file_path": str(r.file_path.resolve()) if r.file_path else None,
                }
                for r in results
            ],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
