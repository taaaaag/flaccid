import asyncio
from pathlib import Path

import pytest

from flaccid.core.config import FlaccidSettings
from flaccid.core.database import Track, get_db_connection, init_db, insert_track


@pytest.mark.asyncio
async def test_qobuz_download_track_skips_if_in_db(tmp_path, monkeypatch):
    """Qobuz download_track should skip when track exists in library DB."""
    from flaccid.plugins.qobuz import QobuzPlugin

    db_path = tmp_path / "flaccid.db"
    settings = FlaccidSettings(library_path=tmp_path, download_path=tmp_path, db_path=db_path)
    monkeypatch.setattr("flaccid.plugins.qobuz._get_settings_cfg", lambda: settings)

    conn = get_db_connection(db_path)
    init_db(conn)
    tr = Track(
        title="t",
        artist="a",
        album="al",
        albumartist="aa",
        tracknumber=1,
        discnumber=1,
        duration=None,
        isrc="ISRC1",
        qobuz_id="1",
        path="p",
        hash=None,
        last_modified=0,
    )
    insert_track(conn, tr)
    conn.close()

    plugin = QobuzPlugin()

    async def fake_get_track(tid):
        return {
            "id": tid,
            "title": "t",
            "artist": {"name": "a"},
            "album": {"title": "al"},
            "isrc": "ISRC1",
        }

    plugin.api_client = type("C", (), {"get_track": staticmethod(fake_get_track)})()

    async def fake_find_stream(self, tid, quality, allow_mp3):
        raise AssertionError("_find_stream should not be called")

    monkeypatch.setattr(QobuzPlugin, "_find_stream", fake_find_stream)
    monkeypatch.setattr("flaccid.plugins.qobuz.apply_metadata", lambda *a, **k: None)
    called = []

    async def fake_download_file(url, path):
        called.append(url)

    monkeypatch.setattr("flaccid.plugins.qobuz.download_file", fake_download_file)

    result = await plugin.download_track("1", "hires", tmp_path)
    assert result is False
    assert called == []


@pytest.mark.asyncio
async def test_tidal_download_track_skips_if_in_db(tmp_path, monkeypatch):
    """Tidal download_track should skip when track exists in library DB."""
    from flaccid.plugins.tidal import TidalPlugin

    db_path = tmp_path / "flaccid.db"
    settings = FlaccidSettings(library_path=tmp_path, download_path=tmp_path, db_path=db_path)
    monkeypatch.setattr("flaccid.core.config.get_settings", lambda: settings)

    conn = get_db_connection(db_path)
    init_db(conn)
    tr = Track(
        title="t",
        artist="a",
        album="al",
        albumartist="aa",
        tracknumber=1,
        discnumber=1,
        duration=None,
        isrc="ISRC1",
        tidal_id="1",
        path="p",
        hash=None,
        last_modified=0,
    )
    insert_track(conn, tr)
    conn.close()

    plugin = TidalPlugin()
    plugin.access_token = "tok"

    async def fake_get_track_metadata(self, tid):
        return {"title": "t", "tracknumber": 1, "isrc": "ISRC1"}

    async def fake_get_stream_info(self, tid, quality):
        raise AssertionError("_get_stream_info should not be called")

    monkeypatch.setattr(TidalPlugin, "_get_track_metadata", fake_get_track_metadata)
    monkeypatch.setattr(TidalPlugin, "_get_stream_info", fake_get_stream_info)
    monkeypatch.setattr("flaccid.plugins.tidal.apply_metadata", lambda *a, **k: None)
    called = []

    async def fake_download_file(url, path):
        called.append(url)

    monkeypatch.setattr("flaccid.plugins.tidal.download_file", fake_download_file)

    result = await plugin.download_track("1", "LOSSLESS", tmp_path)
    assert result is False
    assert called == []
