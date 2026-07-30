"""Centralised application logging for Vinbot.

Every module imports its logger from here instead of using ``print()``. Two
handlers are attached to one shared logger:

  * a ``RotatingFileHandler`` writing to ``/var/log/vinbot/app.log`` (rotated
    at 10 MB, 10 backups kept), for durable, host-persisted logs
  * a ``StreamHandler`` writing to stdout, so ``docker logs`` / ``podman
    logs`` show the same lines in real time with no extra configuration

Deliberately does NOT import ``app.config`` (or anything requiring
``OPENAI_API_KEY``): ``tables.py``, ``intent.py`` and ``followup.py`` are
written to stay importable without a real API key (see their own module
comments), so every one of them can safely import THIS module too. Log
settings are therefore read directly from the environment here, independent
of config.py.

If the log directory can't be created or written to (wrong permissions, or a
non-container dev/test environment where /var/log/vinbot simply doesn't make
sense — e.g. a developer's own machine, or the pytest suite), logging falls
back to console-only rather than raising. A logging system that can crash the
whole application on import is not production-grade; every other module in
this codebase already follows the same "degrade, don't crash" rule (see
``rag.load_knowledge``, ``intent.normalise``), and this file follows it too.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "/var/log/vinbot")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

MAX_BYTES = 10 * 1024 * 1024  # 10 MB per requirement
BACKUP_COUNT = 10

_LOGGER_NAME = "vinbot"
_configured = False


def _configure() -> None:
    """Attach the file + console handlers to the shared logger, once per process."""
    global _configured
    if _configured:
        return
    _configured = True  # set first: never retry-loop on a persistently broken path

    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(LOG_LEVEL)
    root.propagate = False  # keep these records off the real stdlib root logger

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        # No file logging available (missing volume mount, read-only path, a
        # local dev machine with no /var/log/vinbot, ...). Console logging
        # above already works, so the application keeps running normally.
        root.warning(
            "Could not open log file %s (%s) — continuing with console logging only.",
            LOG_FILE, exc,
        )


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the shared Vinbot logger.

    ``get_logger()`` with no arguments returns the shared logger itself — this
    is what ``logger = get_logger()`` below exposes. Modules that want
    ``%(name)s`` in the log line to show which module logged something should
    instead call ``get_logger(__name__)``, which returns a CHILD logger
    (``vinbot.app.chat``, ``vinbot.app.rag``, ...) that still writes through
    the exact same two handlers configured above — nothing about the file,
    rotation, format, or console output changes, only the name recorded on
    each line.
    """
    _configure()
    if not name:
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(_LOGGER_NAME).getChild(name)


# The required module-level contract: `from .logger import logger`.
logger = get_logger()
