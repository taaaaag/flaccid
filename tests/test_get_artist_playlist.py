from typer.testing import CliRunner

from flaccid.cli import app

runner = CliRunner()


def test_get_dry_run_tidal_playlist():
    result = runner.invoke(app, ["get", "-t", "abcd1234", "--playlist", "--dry-run"])
    assert result.exit_code == 0
    assert "Would download Tidal playlist abcd1234" in result.output


def test_get_dry_run_qobuz_artist():
    result = runner.invoke(app, ["get", "-q", "98765", "--artist", "--dry-run"])
    assert result.exit_code == 0
    assert "Would download Qobuz artist 98765" in result.output


def test_get_help_shows_artist_limit():
    result = runner.invoke(app, ["get", "--help"])
    assert result.exit_code == 0
    # Ensure the top-level get help documents the --limit option for artist mode
    assert "--limit" in result.output
