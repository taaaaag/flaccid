from pathlib import Path
import sqlite3

from typer.testing import CliRunner

from flaccid.cli import app


def _make_mp3_with_id3(path: Path, title: str, artist: str, album: str) -> None:
    from mutagen.id3 import ID3, TIT2, TPE1, TALB

    id3 = ID3()
    id3.add(TIT2(encoding=3, text=title))
    id3.add(TPE1(encoding=3, text=artist))
    id3.add(TALB(encoding=3, text=album))
    id3.save(path)


def test_flaccid_library_index_and_rescan(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem():
        libdir = Path("lib")
        libdir.mkdir(parents=True, exist_ok=True)
        # Create two minimal MP3s with ID3-only tags
        _make_mp3_with_id3(libdir / "track1.mp3", "Song A", "Artist X", "Album Z")
        _make_mp3_with_id3(libdir / "track2.mp3", "Song B", "Artist Y", "Album Z")

        # Point flaccid to our temp library
        r = runner.invoke(app, ["config", "path", "--library", str(libdir.resolve())])
        assert r.exit_code == 0, r.output

        # Full index
        r2 = runner.invoke(app, ["lib", "index"])
        assert r2.exit_code == 0, r2.output

        # Verify DB has 2 tracks
        db_path = libdir / "flaccid.db"
        assert db_path.exists()
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            assert count == 2

        # Rescan should keep count the same
        r3 = runner.invoke(app, ["lib", "scan"])
        assert r3.exit_code == 0, r3.output
        with sqlite3.connect(db_path) as conn:
            count2 = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            assert count2 == 2
