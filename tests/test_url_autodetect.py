from typer.testing import CliRunner

from flaccid.cli import app

runner = CliRunner()


def test_autodetect_tidal_playlist_dry_run():
    url = "https://tidal.com/playlist/abc123"
    res = runner.invoke(app, ["get", "--dry-run", url])
    assert res.exit_code == 0
    assert "Dry-run: Would download from URL:" in res.output


def test_autodetect_qobuz_artist_dry_run():
    url = "https://www.qobuz.com/us-en/artist/99999"
    res = runner.invoke(app, ["get", "--dry-run", url])
    assert res.exit_code == 0
    assert "Dry-run: Would download from URL:" in res.output
