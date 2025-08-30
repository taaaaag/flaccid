import json as _json
import logging
import sys
from typing import Any, Dict


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return _json.dumps(payload, ensure_ascii=False)


def setup_logging(
    *, json_logs: bool = False, verbose: bool | None = None, quiet: bool | None = None
) -> None:
    """Configure root logging.

    - json_logs: emit JSON lines to stdout
    - verbose: DEBUG level if True
    - quiet: WARNING level if True
    Default level is INFO when neither verbose nor quiet is set.
    """
    level = logging.INFO
    if verbose:
        level = logging.DEBUG
    if quiet:
        level = max(level, logging.WARNING)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(stream=sys.stdout)
    if json_logs:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
