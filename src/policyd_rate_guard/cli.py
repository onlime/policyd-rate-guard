"""Command line interface.

policyd-rate-guard [--env-file PATH] [serve [--require-socket-activation]]
policyd-rate-guard [--env-file PATH] cleanup
policyd-rate-guard [--env-file PATH] check
"""

import argparse
import asyncio
import logging
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .config import ConfigError, Settings, load_settings
from .db import Database
from .log import configure_logging
from .ratelimit import purge_messages, reset_counters
from .sentry import init_sentry
from .server import PolicyServer, bind_listen_socket
from .service import PolicyService
from .systemd import listen_sockets
from .webhook import Webhook

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='policyd-rate-guard', description='Sender rate limit policy daemon for Postfix'
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument(
        '--env-file',
        type=Path,
        help='env file with the configuration '
        '(default: $POLICYD_ENV_FILE or /etc/policyd-rate-guard/policyd-rate-guard.env)',
    )
    commands = parser.add_subparsers(dest='command', metavar='COMMAND')
    serve = commands.add_parser('serve', help='run the policy daemon (default)')
    serve.add_argument(
        '--require-socket-activation',
        action='store_true',
        help='refuse to start without sockets from systemd instead of binding SOCKET',
    )
    commands.add_parser('cleanup', help='reset counters and quotas, purge old messages (daily timer)')
    commands.add_parser('check', help='validate the configuration and the database connection')
    return parser


def serve(settings: Settings, logger: logging.Logger, require_socket_activation: bool) -> int:
    sockets = listen_sockets()
    if not sockets:
        if require_socket_activation:
            logger.critical('No sockets from systemd (LISTEN_FDS), refusing to bind SOCKET myself')
            return EXIT_FAILURE
        sockets = [bind_listen_socket(settings)]
    db = Database(settings.db)
    webhook = Webhook(settings.webhook, logger) if settings.webhook.enabled else None
    server = PolicyServer(settings, PolicyService(settings, db, logger), webhook, logger)
    logger.info('policyd-rate-guard %s starting', __version__)
    try:
        asyncio.run(server.run(sockets))
    finally:
        db.close()
    return EXIT_OK


def cleanup(settings: Settings, logger: logging.Logger) -> int:
    db = Database(settings.db)
    try:
        changed = reset_counters(db)
        logger.info('Reset counters of %d senders', changed)
        if settings.message_retention > 0:
            deleted = purge_messages(db, settings.message_retention)
            logger.info('Deleted %d old messages (retention: %d days)', deleted, settings.message_retention)
    except Exception:
        logger.exception('Cleanup failed')
        return EXIT_FAILURE
    finally:
        db.close()
    return EXIT_OK


def check(settings: Settings, logger: logging.Logger) -> int:
    db = Database(settings.db)
    try:
        with db.connection() as conn:
            cursor = conn.cursor()
            for table in ('ratelimits', 'messages'):
                cursor.execute(f'SELECT 1 FROM `{table}` LIMIT 1')
                cursor.fetchone()
            cursor.close()
    except Exception as e:  # report any failure as a failed check
        logger.error('Database check failed: %s', e)
        return EXIT_FAILURE
    finally:
        db.close()
    sys.stdout.write(f'policyd-rate-guard {__version__}: configuration and database OK\n')
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.env_file)
    except ConfigError as e:
        sys.stderr.write(f'{e}\n')
        return EXIT_CONFIG
    if args.command == 'check':
        # Typically run as root (e.g. by Ansible before a restart): never create or touch the service's log file
        return check(settings, configure_logging(replace(settings, log_file=None, syslog=False, log_console=True)))
    logger = configure_logging(settings)
    init_sentry(settings)
    match args.command:
        case 'cleanup':
            return cleanup(settings, logger)
        case _:
            return serve(settings, logger, getattr(args, 'require_socket_activation', False))
