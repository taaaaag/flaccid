import pytest
from typer.testing import CliRunner
from flaccid.cli import app

runner = CliRunner()

def test_app_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "FLACCID" in result.output

# Add more tests...
