import os
from pathlib import Path

from typer.testing import CliRunner

from flaccid.cli import app


runner = CliRunner()


def test_config_path_set_and_show():
    # Use isolated filesystem so settings.toml is written locally
    with runner.isolated_filesystem():
        lib = str(Path("lib").resolve())
        dl = str(Path("dl").resolve())

        res = runner.invoke(app, ["config", "path", "--library", lib, "--download", dl])
        assert res.exit_code == 0, res.output

        res2 = runner.invoke(app, ["config", "show"])
        assert res2.exit_code == 0, res2.output
        out = res2.output
        assert lib in out
        assert dl in out


def test_config_path_prints_current_paths():
    with runner.isolated_filesystem():
        # Running without options shows current paths
        res = runner.invoke(app, ["config", "path"])
        assert res.exit_code == 0, res.output
        assert "Current Paths:" in res.output


def test_config_show_json_contains_core_keys():
    """Ensure --json outputs structured keys without requiring exact formatting."""
    with runner.isolated_filesystem():
        res = runner.invoke(app, ["config", "show", "--json"])
        assert res.exit_code == 0, res.output
        out = res.output
        # Basic key presence checks (works even if Rich adds colorization)
        assert '"paths"' in out or "paths" in out
        assert '"qobuz"' in out or "qobuz" in out
        assert '"tidal"' in out or "tidal" in out
        assert '"library"' in out or "library" in out
        assert '"download"' in out or "download" in out
