"""Logging setup.

The line format is kept byte-identical to 0.x, because operations scripts parse the log file:

    2026-11-08 12:34:56,789 INFO 4XyZ1abc2: client=…[…], helo=…, sasl_method=…, sasl_username=…, …

The queue ID prefix comes from a context variable (set per request, also in worker threads), injected by a
filter on each handler, so it's always the queue ID of the request being logged, even under concurrency.
"""

import contextvars
import logging
import logging.handlers
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from .config import Settings

LOGGER_NAME = 'policyd-rate-guard'
LOG_FORMAT = '%(asctime)s %(levelname)s %(queue_id_prefix)s%(message)s'
SYSLOG_FORMAT = '%(name)s[%(process)d]: %(levelname)s %(queue_id_prefix)s%(message)s'

queue_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar('queue_id', default=None)

logger = logging.getLogger(LOGGER_NAME)


@contextmanager
def queue_id_context(queue_id: str | None) -> Iterator[None]:
    token = queue_id_var.set(queue_id)
    try:
        yield
    finally:
        queue_id_var.reset(token)


class ContextFilter(logging.Filter):
    """Add ``queue_id_prefix`` to every record (never drops a record)."""

    def filter(self, record: logging.LogRecord) -> bool:
        queue_id = queue_id_var.get()
        record.queue_id_prefix = f'{queue_id}: ' if queue_id else ''
        return True


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure the application logger. Handlers are attached to it only, not to the root logger, so logs of
    third-party libraries (urllib3, yoyo, sentry) don't end up in the policy log."""
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    handlers: list[logging.Handler] = []
    if settings.log_file:
        # WatchedFileHandler reopens the file after logrotate moved it, no restart needed
        handlers.append(logging.handlers.WatchedFileHandler(settings.log_file, encoding='utf-8'))
    if settings.log_console:
        handlers.append(logging.StreamHandler(sys.stderr))
    if settings.syslog:
        syslog = logging.handlers.SysLogHandler(address='/dev/log', facility=logging.handlers.SysLogHandler.LOG_MAIL)
        syslog.setFormatter(logging.Formatter(SYSLOG_FORMAT))
        handlers.append(syslog)
    if not handlers:
        # Under systemd, stderr goes to the journal
        handlers.append(logging.StreamHandler(sys.stderr))

    context_filter = ContextFilter()
    for handler in handlers:
        if handler.formatter is None:
            handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler.addFilter(context_filter)
        logger.addHandler(handler)

    logger.setLevel(settings.log_level)
    logger.propagate = False
    return logger
