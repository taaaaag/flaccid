"""Command groups for the FLACCID CLI.

This package provides sub-apps that are mounted by flaccid.cli.
"""

from . import config as config  # noqa: F401
from . import get as get  # noqa: F401
from . import lib as lib  # noqa: F401
from . import tag as tag  # noqa: F401

__all__ = [
    "get",
    "tag",
    "lib",
    "config",
]
