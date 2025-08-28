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
