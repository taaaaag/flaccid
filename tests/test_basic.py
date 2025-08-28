"""Basic tests for flaccid."""

from importlib.util import find_spec


def test_import():
    """Test that package is importable without side effects."""
    assert find_spec("flaccid") is not None


def test_cli_import():
    """Test that CLI can be imported."""
    try:
        from flaccid.cli import app

        assert app is not None
    except ImportError:
        assert False, "Failed to import CLI"
