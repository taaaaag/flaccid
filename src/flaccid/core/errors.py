# src/flaccid/core/errors.py


class FlaccidError(Exception):
    """Base application error for FLACCID.

    Use this for predictable, user-facing error messages that should be
    caught by the CLI and displayed nicely. Keep it minimal; we can extend
    with specific subclasses later if needed.
    """

    pass
