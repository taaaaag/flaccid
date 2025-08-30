from typer.testing import CliRunner

from flaccid.cli import app


def test_help_footer_contains_usage_tip(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # flaccid help includes an epilog with usage guidance
    assert "Use `fla [COMMAND] --help`" in result.output
