from pathlib import Path

from mutagen.id3 import ID3, TPE1, TPE2


def test_fix_artist_prefers_albumartist_mp3(tmp_path: Path):
    # Arrange: create an ID3-only MP3 with differing artist/albumartist
    p = tmp_path / "song.mp3"
    id3 = ID3()
    id3.add(TPE1(encoding=3, text=["Track Artist"]))
    id3.add(TPE2(encoding=3, text=["Album Artist"]))
    id3.save(p)

    # Act: run fix-artist on the folder
    from flaccid.commands import tag as tag_cmd

    tag_cmd.tag_fix_artist(folder=tmp_path, prefer_albumartist=True, preview=False)

    # Assert: TPE1 should now equal Album Artist
    after = ID3(p)
    assert after.get("TPE1") is not None
    assert after.get("TPE1").text[0] == "Album Artist"
    # TPE2 should be preserved
    assert after.get("TPE2") is not None
    assert after.get("TPE2").text[0] == "Album Artist"


def test_fix_artist_strip_feat_with_albumartist(tmp_path: Path):
    p = tmp_path / "song.mp3"
    id3 = ID3()
    id3.add(TPE1(encoding=3, text=["Track Artist feat. Guest"]))
    id3.add(TPE2(encoding=3, text=["Album Artist feat Guest"]))
    id3.save(p)

    from flaccid.commands import tag as tag_cmd

    tag_cmd.tag_fix_artist(
        folder=tmp_path, prefer_albumartist=True, strip_feat=True, preview=False
    )

    after = ID3(p)
    assert after.get("TPE1").text[0] == "Album Artist"


def test_fix_artist_strip_feat_without_albumartist(tmp_path: Path):
    p = tmp_path / "song2.mp3"
    id3 = ID3()
    id3.add(TPE1(encoding=3, text=["Track Artist ft. Guest"]))
    id3.save(p)

    from flaccid.commands import tag as tag_cmd

    tag_cmd.tag_fix_artist(
        folder=tmp_path, prefer_albumartist=False, strip_feat=True, preview=False
    )

    after = ID3(p)
    assert after.get("TPE1").text[0] == "Track Artist"
