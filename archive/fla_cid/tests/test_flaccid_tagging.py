from pathlib import Path
import json

from mutagen.id3 import ID3
from flaccid.core.metadata import apply_metadata


def test_apply_metadata_mp3(tmp_path: Path):
    # Create an empty MP3 container with just an ID3 tag (no audio frames)
    p = tmp_path / "test.mp3"
    ID3().save(p)
    md = {
        "title": "Song",
        "artist": "Artist",
        "album": "Album",
        "tracknumber": 1,
        "tracktotal": 10,
        "discnumber": 1,
        "disctotal": 1,
        "lyrics": "La la la",
        "upc": "1234567890",
    }
    apply_metadata(p, md)  # should not raise


def test_playlist_parser_minimal(tmp_path: Path):
    from flaccid.core.playlist import PlaylistParser

    data = [
        {"title": "A", "artist": "X", "album": "Z"},
        {"title": "B", "artist": "Y", "album": "Z"},
    ]
    f = tmp_path / "pl.json"
    f.write_text(json.dumps(data))

    tracks = PlaylistParser().parse_file(f)
    assert len(tracks) == 2
    assert tracks[0].title == "A"
