from pathlib import Path

from typer.testing import CliRunner

from flaccid.cli import app


def test_tag_audit_fixes_missing_fields(tmp_path: Path):
    # Create an empty MP3 with just ID3 tag
    from mutagen.id3 import ID3

    p = tmp_path / "song.mp3"
    ID3().save(p)

    runner = CliRunner()
    # Run audit with --fix
    r = runner.invoke(app, ["tag", "audit", str(tmp_path), "--fix"])
    assert r.exit_code == 0

    # Verify fields via ID3 frames (ID3-only container)
    from mutagen.id3 import ID3

    after = ID3(p)
    assert after.get("TIT2") is not None and after.get("TIT2").text[0] == "song"
    assert after.get("TPE1") is not None and after.get("TPE1").text[0] == "Unknown Artist"
    assert after.get("TALB") is not None and after.get("TALB").text[0] == "Unknown Album"
