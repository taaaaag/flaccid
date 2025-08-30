from pathlib import Path

from flaccid.core.playlist import MatchResult, PlaylistExporter, PlaylistTrack


def test_playlist_export_m3u(tmp_path: Path):
    # Create dummy audio files to satisfy exporter existence checks
    f1 = tmp_path / "A - Song 1.flac"
    f2 = tmp_path / "B - Song 2.flac"
    f1.write_bytes(b"flacdata")
    f2.write_bytes(b"flacdata")

    # Compose results with matched tracks pointing to real files
    results = [
        MatchResult(
            input_track=PlaylistTrack(title="Song 1", artist="A"),
            matched_track={"title": "Song 1", "artist": "A", "duration": 123},
            match_score=95.0,
            file_path=f1,
        ),
        MatchResult(
            input_track=PlaylistTrack(title="Song 2", artist="B"),
            matched_track={"title": "Song 2", "artist": "B", "duration": 200},
            match_score=92.0,
            file_path=f2,
        ),
    ]

    out = tmp_path / "pl.m3u"
    PlaylistExporter().export(results, out, format="m3u")

    text = out.read_text(encoding="utf-8")
    assert text.startswith("#EXTM3U")
    assert "A - Song 1" in text
    assert "B - Song 2" in text
