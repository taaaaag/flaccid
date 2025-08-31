import os
from pathlib import Path

from flaccid.core.config import (
    create_default_settings,
    get_settings,
    reset_settings,
    save_settings,
)


def test_env_override_for_library_path(tmp_path, monkeypatch):
    # Ensure a clean state and isolate to tmp dir
    monkeypatch.chdir(tmp_path)
    settings_file = tmp_path / "settings.json"
    monkeypatch.setenv("FLA_SETTINGS_PATH", str(settings_file))
    reset_settings()

    lib = tmp_path / "MyLib"
    monkeypatch.setenv("FLA_LIBRARY_PATH", str(lib))

    s = get_settings()
    assert s.library_path == lib


def test_save_and_reload_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings_file = tmp_path / "settings.json"
    monkeypatch.setenv("FLA_SETTINGS_PATH", str(settings_file))
    reset_settings()

    s = create_default_settings()
    s.library_path = tmp_path / "L1"
    s.download_path = tmp_path / "D1"
    save_settings(s)

    # New process simulation: clear singleton, reload from file
    reset_settings()
    s2 = get_settings()
    assert s2.library_path == s.library_path
    assert s2.download_path == s.download_path
