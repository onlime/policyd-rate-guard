"""Typed, validated configuration from environment variables and an optional env file.

The variable names are the same as in 0.x. The env file is always read from an explicit path,
never searched for (python-dotenv's ``find_dotenv()`` walks up parent directories).
"""

import binascii
import os
import string
from base64 import b64decode
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from sentry_sdk.utils import BadDsn, Dsn

from .webhook import WebhookPayload

DEFAULT_ENV_FILE = Path('/etc/policyd-rate-guard/policyd-rate-guard.env')

# Keys of the webhook payload, usable as {placeholder} in WEBHOOK_URL
WEBHOOK_PLACEHOLDERS = frozenset(f.name for f in fields(WebhookPayload))

_TRUE = frozenset({'y', 'yes', 't', 'true', 'on', '1'})
_FALSE = frozenset({'n', 'no', 'f', 'false', 'off', '0'})
_ACTIONS = ('DUNNO', 'DEFER_IF_PERMIT')
_LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')


class ConfigError(ValueError):
    """Invalid configuration, reported at startup."""


@dataclass(frozen=True, slots=True)
class TcpAddress:
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class DbSettings:
    host: str = 'localhost'
    port: int = 3306
    unix_socket: str | None = None
    user: str = 'policyd-rate-guard'
    password: str = field(default='', repr=False)
    database: str = 'policyd-rate-guard'
    pool_maxcached: int = 10
    pool_maxconnections: int = 10
    lock_wait_timeout: int = 5


@dataclass(frozen=True, slots=True)
class WebhookSettings:
    enabled: bool = False
    url: str = ''
    secret: str = field(default='', repr=False)
    allow_http: bool = False


@dataclass(frozen=True, slots=True)
class Settings:
    db: DbSettings = field(default_factory=DbSettings)
    webhook: WebhookSettings = field(default_factory=WebhookSettings)
    quota: int = 1000
    action_text_blocked: str = 'Rate limit reached, retry later'
    fail_action: Literal['DUNNO', 'DEFER_IF_PERMIT'] = 'DUNNO'
    listen: TcpAddress = field(default_factory=lambda: TcpAddress('127.0.0.1', 10033))
    log_level: str = 'INFO'
    log_file: Path | None = None
    log_console: bool = False
    syslog: bool = False
    message_retention: int = 0
    sentry_dsn: str | None = field(default=None, repr=False)
    sentry_environment: str = 'dev'

    def secrets(self) -> list[str]:
        """Secret values that must never show up in logs or error reports."""
        return [s for s in (self.db.password, self.webhook.secret, self.sentry_dsn) if s]


class _Reader:
    def __init__(self, values: Mapping[str, str | None]) -> None:
        self._values = values
        self.errors: list[str] = []

    def raw(self, key: str) -> str | None:
        value = self._values.get(key)
        if value is None:
            return None
        value = value.strip()
        return value or None

    def text(self, key: str, default: str) -> str:
        return self.raw(key) or default

    def secret(self, key: str) -> str:
        """Unstripped: whitespace may be part of a password."""
        return self._values.get(key) or ''

    def integer(self, key: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
        value = self.raw(key)
        if value is None:
            return default
        try:
            number = int(value)
        except ValueError:
            self.errors.append(f'{key}: expected an integer, got {value!r}')
            return default
        if number < minimum or (maximum is not None and number > maximum):
            upper = f'..{maximum}' if maximum is not None else ' or more'
            self.errors.append(f'{key}: {number} is out of range ({minimum}{upper})')
            return default
        return number

    def flag(self, key: str, default: bool) -> bool:
        value = self.raw(key)
        if value is None:
            return default
        if value.lower() in _TRUE:
            return True
        if value.lower() in _FALSE:
            return False
        self.errors.append(f'{key}: expected True or False, got {value!r}')
        return default


def parse_listen_address(value: str) -> TcpAddress:
    """Parse ``SOCKET`` as ``host,port`` (IPv6 hosts with or without brackets).

    A unix socket is set up by systemd socket activation (``ListenStream=/path``), not by the daemon.
    """
    host, sep, port = value.rpartition(',')
    if not sep:
        raise ConfigError(f'SOCKET: expected host,port, got {value!r} (use a systemd socket unit for a unix socket)')
    host = host.strip().removeprefix('[').removesuffix(']')
    if not host:
        raise ConfigError(f'SOCKET: missing host in {value!r}')
    try:
        port_number = int(port)
    except ValueError:
        raise ConfigError(f'SOCKET: invalid port in {value!r}') from None
    if not 0 < port_number < 65536:
        raise ConfigError(f'SOCKET: port out of range in {value!r}')
    return TcpAddress(host, port_number)


WEBHOOK_SECRET_MIN_BYTES = 32


def _validate_webhook(webhook: WebhookSettings, errors: list[str]) -> None:
    if not webhook.enabled:
        return
    if not webhook.url:
        errors.append('WEBHOOK_URL: required when WEBHOOK_ENABLED=True')
    elif not (webhook.url.startswith('https://') or (webhook.allow_http and webhook.url.startswith('http://'))):
        errors.append('WEBHOOK_URL: must start with https:// (set WEBHOOK_ALLOW_HTTP=True for local development)')
    else:
        try:
            fields = [
                (name, spec, conv) for _, name, spec, conv in string.Formatter().parse(webhook.url) if name is not None
            ]
        except ValueError as e:
            errors.append(f'WEBHOOK_URL: invalid placeholder syntax ({e})')
        else:
            if unknown := {name for name, _, _ in fields} - WEBHOOK_PLACEHOLDERS:
                errors.append(f'WEBHOOK_URL: unknown placeholder(s) {sorted(unknown)}')
            elif any(spec or conv for _, spec, conv in fields):
                errors.append('WEBHOOK_URL: placeholders take no format spec or conversion, only {name}')
    if not webhook.secret:
        errors.append('WEBHOOK_SECRET: required when WEBHOOK_ENABLED=True')
    else:
        try:
            key = b64decode(webhook.secret, validate=True)
        except binascii.Error:
            errors.append('WEBHOOK_SECRET: must be base64 encoded')
        else:
            # HS256 needs a key of at least 256 bits: shorter ones are rejected by the receiving side (lcobucci/jwt 5)
            if len(key) < WEBHOOK_SECRET_MIN_BYTES:
                errors.append(
                    f'WEBHOOK_SECRET: must decode to at least {WEBHOOK_SECRET_MIN_BYTES} bytes, has {len(key)} '
                    '(generate one with: openssl rand -base64 32)'
                )


def settings_from_mapping(values: Mapping[str, str | None]) -> Settings:
    """Build validated settings, collecting all errors before raising."""
    r = _Reader(values)
    errors = r.errors

    driver = r.text('DB_DRIVER', 'pymysql').lower()
    if driver != 'pymysql':
        errors.append(f'DB_DRIVER: only pymysql is supported, got {driver!r}')

    db = DbSettings(
        host=r.text('DB_HOST', 'localhost'),
        port=r.integer('DB_PORT', 3306, 1, 65535),
        unix_socket=r.raw('DB_UNIX_SOCKET'),
        user=r.text('DB_USER', 'policyd-rate-guard'),
        password=r.secret('DB_PASSWORD'),
        database=r.text('DB_DATABASE', 'policyd-rate-guard'),
        pool_maxcached=r.integer('DB_POOL_MAXCACHED', 10),
        pool_maxconnections=r.integer('DB_POOL_MAXCONNECTIONS', 10, 1, 1000),
        lock_wait_timeout=r.integer('DB_LOCK_WAIT_TIMEOUT', 5, 1, 7),  # ends before DECIDE_TIMEOUT (8 s)
    )
    webhook = WebhookSettings(
        enabled=r.flag('WEBHOOK_ENABLED', False),
        url=r.text('WEBHOOK_URL', ''),
        secret=r.raw('WEBHOOK_SECRET') or '',
        allow_http=r.flag('WEBHOOK_ALLOW_HTTP', False),
    )
    _validate_webhook(webhook, errors)
    if webhook.enabled and not r.flag('WEBHOOK_USE_JWT', True):
        errors.append('WEBHOOK_USE_JWT: the simple token was removed in 1.0, the webhook always sends a JWT')

    fail_action = r.text('FAIL_ACTION', 'DUNNO').upper()
    if fail_action not in _ACTIONS:
        errors.append(f'FAIL_ACTION: must be one of {", ".join(_ACTIONS)}, got {fail_action!r}')
        fail_action = 'DUNNO'

    action_text = r.text('ACTION_TEXT_BLOCKED', 'Rate limit reached, retry later')
    if any(ch in action_text for ch in '\r\n\0'):
        errors.append('ACTION_TEXT_BLOCKED: must be a single line')

    log_level = r.text('LOG_LEVEL', 'INFO').upper()
    if log_level not in _LOG_LEVELS:
        errors.append(f'LOG_LEVEL: must be one of {", ".join(_LOG_LEVELS)}, got {log_level!r}')
        log_level = 'INFO'

    listen = TcpAddress('127.0.0.1', 10033)
    if socket_value := r.raw('SOCKET'):
        try:
            listen = parse_listen_address(socket_value)
        except ConfigError as e:
            errors.append(str(e))

    sentry_dsn = r.raw('SENTRY_DSN')
    if sentry_dsn:
        try:
            Dsn(sentry_dsn)
        except BadDsn:
            errors.append('SENTRY_DSN: not a valid Sentry DSN')  # without the value, it's a secret

    log_file = r.raw('LOG_FILE')
    settings = Settings(
        db=db,
        webhook=webhook,
        quota=r.integer('QUOTA', 1000, 0, 4294967295),  # int unsigned columns
        action_text_blocked=action_text,
        fail_action='DEFER_IF_PERMIT' if fail_action == 'DEFER_IF_PERMIT' else 'DUNNO',
        listen=listen,
        log_level=log_level,
        log_file=Path(log_file) if log_file else None,
        log_console=r.flag('LOG_CONSOLE', False),
        syslog=r.flag('SYSLOG', False),
        message_retention=r.integer('MESSAGE_RETENTION', 0),
        sentry_dsn=sentry_dsn,
        sentry_environment=r.text('SENTRY_ENVIRONMENT', 'dev'),
    )
    if errors:
        raise ConfigError('Invalid configuration:\n  ' + '\n  '.join(errors))
    return settings


def load_settings(env_file: Path | None = None, environ: Mapping[str, str] | None = None) -> Settings:
    """Load settings from ``env_file`` (if any) overlaid by the process environment.

    An explicitly given ``env_file`` (argument or ``POLICYD_ENV_FILE``) must exist; the default path is optional,
    so a container can be configured through its environment alone.
    """
    environ = os.environ if environ is None else environ
    explicit = env_file or (Path(environ['POLICYD_ENV_FILE']) if environ.get('POLICYD_ENV_FILE') else None)
    path = explicit or DEFAULT_ENV_FILE
    values: dict[str, str | None] = {}
    if path.is_file():
        values.update(dotenv_values(path, interpolate=False))  # a $ in a password is literal
    elif explicit is not None:
        raise ConfigError(f'Env file not found: {path}')
    values.update(environ)
    return settings_from_mapping(values)
