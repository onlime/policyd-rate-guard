from pathlib import Path

import pytest

from policyd_rate_guard.config import (
    DEFAULT_ENV_FILE,
    ConfigError,
    TcpAddress,
    load_settings,
    parse_listen_address,
    settings_from_mapping,
)

from .helpers import SECRET


def test_defaults() -> None:
    settings = settings_from_mapping({})
    assert settings.quota == 1000
    assert settings.fail_action == 'DUNNO'
    assert settings.listen == TcpAddress('127.0.0.1', 10033)
    assert settings.db.user == 'policyd-rate-guard'
    assert settings.db.unix_socket is None
    assert settings.webhook.enabled is False
    assert settings.message_retention == 0


def test_values_and_backward_compatible_names() -> None:
    settings = settings_from_mapping({
        'DB_DRIVER': 'PyMySQL',
        'DB_HOST': 'db',
        'DB_PORT': '3307',
        'DB_UNIX_SOCKET': '/run/mysqld/mysqld.sock',
        'DB_USER': 'policyd',
        'DB_PASSWORD': 'pw',
        'DB_DATABASE': 'prg',
        'DB_POOL_MAXSHARED': '10',  # 0.x option, ignored (PyMySQL connections can't be shared)
        'QUOTA': '500',
        'ACTION_TEXT_BLOCKED': 'Slow down',
        'FAIL_ACTION': 'defer_if_permit',
        'SOCKET': '[::1],10034',
        'LOG_LEVEL': 'debug',
        'LOG_FILE': '/var/log/x.log',
        'SYSLOG': 'yes',
        'MESSAGE_RETENTION': '365',
        'SENTRY_DSN': 'https://key@example.invalid/1',
    })  # fmt: skip
    assert settings.db.port == 3307
    assert settings.db.unix_socket == '/run/mysqld/mysqld.sock'
    assert settings.quota == 500
    assert settings.action_text_blocked == 'Slow down'
    assert settings.fail_action == 'DEFER_IF_PERMIT'
    assert settings.listen == TcpAddress('::1', 10034)
    assert settings.log_level == 'DEBUG'
    assert settings.log_file == Path('/var/log/x.log')
    assert settings.syslog is True
    assert settings.message_retention == 365
    assert settings.secrets() == ['pw', 'https://key@example.invalid/1']


def test_secrets_are_not_in_repr() -> None:
    settings = settings_from_mapping(
        {'DB_PASSWORD': 'hunter22', 'WEBHOOK_SECRET': SECRET, 'SENTRY_DSN': 'https://k@x/1'}
    )
    assert 'hunter22' not in repr(settings)
    assert SECRET not in repr(settings)
    assert 'https://k@x/1' not in repr(settings)


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('127.0.0.1,10033', TcpAddress('127.0.0.1', 10033)),
        ('::1,10033', TcpAddress('::1', 10033)),
        ('[::1],10033', TcpAddress('::1', 10033)),
        ('localhost, 10033', TcpAddress('localhost', 10033)),
    ],
)
def test_parse_listen_address(value: str, expected: object) -> None:
    assert parse_listen_address(value) == expected


@pytest.mark.parametrize(
    'value', ['/var/spool/postfix/private/policyd', ',10033', '127.0.0.1,http', '127.0.0.1,0', '127.0.0.1,70000']
)
def test_parse_listen_address_invalid(value: str) -> None:
    with pytest.raises(ConfigError, match='SOCKET'):
        parse_listen_address(value)


def test_all_errors_are_reported_at_once() -> None:
    with pytest.raises(ConfigError) as info:
        settings_from_mapping({
            'DB_DRIVER': 'sqlite3',
            'DB_PORT': 'abc',
            'QUOTA': '-1',
            'LOG_LEVEL': 'LOUD',
            'SYSLOG': 'maybe',
            'FAIL_ACTION': 'REJECT',
            'ACTION_TEXT_BLOCKED': 'two\nlines',
            'SOCKET': 'nonsense',
            'DB_POOL_MAXCONNECTIONS': '0',
        })  # fmt: skip
    message = str(info.value)
    for key in ('DB_DRIVER', 'DB_PORT', 'QUOTA', 'LOG_LEVEL', 'SYSLOG', 'FAIL_ACTION', 'ACTION_TEXT_BLOCKED', 'SOCKET'):
        assert key in message
    assert 'DB_POOL_MAXCONNECTIONS: 0 is out of range (1..1000)' in message


@pytest.mark.parametrize(
    ('values', 'error'),
    [
        ({'WEBHOOK_SECRET': SECRET}, 'WEBHOOK_URL: required'),
        ({'WEBHOOK_URL': 'https://example.com/{sender}'}, 'WEBHOOK_SECRET: required'),
        ({'WEBHOOK_URL': 'http://example.com/', 'WEBHOOK_SECRET': SECRET}, 'must start with https://'),
        ({'WEBHOOK_URL': 'https://example.com/{nope}', 'WEBHOOK_SECRET': SECRET}, "unknown placeholder(s) ['nope']"),
        ({'WEBHOOK_URL': 'https://example.com/{sender', 'WEBHOOK_SECRET': SECRET}, 'invalid placeholder syntax'),
        ({'WEBHOOK_URL': 'https://example.com/', 'WEBHOOK_SECRET': 'not base64!'}, 'must be base64 encoded'),
        ({'WEBHOOK_URL': 'https://example.com/', 'WEBHOOK_SECRET': 'c2VjcmV0'}, 'at least 32 bytes, has 6'),
        # the simple token of 0.x is gone: no {token} placeholder, WEBHOOK_USE_JWT=False is rejected
        ({'WEBHOOK_URL': 'https://example.com/?token={token}', 'WEBHOOK_SECRET': SECRET}, "['token']"),
        (
            {'WEBHOOK_URL': 'https://example.com/', 'WEBHOOK_SECRET': SECRET, 'WEBHOOK_USE_JWT': 'False'},
            'the simple token was removed',
        ),
    ],
)
def test_webhook_validation(values: dict[str, str], error: str) -> None:
    with pytest.raises(ConfigError) as info:
        settings_from_mapping({'WEBHOOK_ENABLED': 'True', **values})
    assert error in str(info.value)


def test_webhook_valid_and_http_for_development() -> None:
    settings = settings_from_mapping({
        'WEBHOOK_ENABLED': 'True',
        'WEBHOOK_URL': 'http://host.docker.internal:8080/api/policyd/{sender}',
        'WEBHOOK_USE_JWT': 'True',  # still accepted (JWT is the only variant now)
        'WEBHOOK_SECRET': SECRET,
        'WEBHOOK_ALLOW_HTTP': 'True',
    })  # fmt: skip
    assert settings.webhook.enabled
    assert settings.webhook.allow_http


def test_load_settings_env_file_and_environment_override(tmp_path: Path) -> None:
    env_file = tmp_path / 'test.env'
    env_file.write_text('# comment\nQUOTA=42 # inline comment\nDB_PASSWORD="quoted # not a comment"\nLOG_LEVEL=DEBUG\n')
    settings = load_settings(env_file, environ={'LOG_LEVEL': 'WARNING'})
    assert settings.quota == 42
    assert settings.db.password == 'quoted # not a comment'
    assert settings.log_level == 'WARNING'  # the environment wins


def test_load_settings_from_policyd_env_file_variable(tmp_path: Path) -> None:
    env_file = tmp_path / 'other.env'
    env_file.write_text('QUOTA=7\n')
    assert load_settings(environ={'POLICYD_ENV_FILE': str(env_file)}).quota == 7


def test_explicit_env_file_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match='Env file not found'):
        load_settings(tmp_path / 'missing.env', environ={})
    with pytest.raises(ConfigError, match='Env file not found'):
        load_settings(environ={'POLICYD_ENV_FILE': str(tmp_path / 'missing.env')})


def test_default_env_file_is_optional() -> None:
    assert not DEFAULT_ENV_FILE.exists()  # not on a development machine / CI runner
    assert load_settings(environ={'QUOTA': '9'}).quota == 9


def test_never_searches_for_dot_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """0.x called load_dotenv() without a path, which walks up parent directories (e.g. a stale /opt/…/.env)."""
    (tmp_path / '.env').write_text('QUOTA=1\n')
    nested = tmp_path / 'a' / 'b'
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert load_settings(environ={}).quota == 1000


def test_env_file_values_are_literal(tmp_path: Path) -> None:
    """No ${VAR} interpolation and no stripping: both would silently change a password."""
    env_file = tmp_path / 'test.env'
    env_file.write_text('DB_PASSWORD=" p${USER}x "\n')
    assert load_settings(env_file, environ={'USER': 'phi'}).db.password == ' p${USER}x '


def test_quota_must_fit_the_column() -> None:
    with pytest.raises(ConfigError, match='QUOTA'):
        settings_from_mapping({'QUOTA': '4294967296'})


def test_sentry_dsn_and_lock_wait_are_validated() -> None:
    with pytest.raises(ConfigError, match='SENTRY_DSN: not a valid Sentry DSN') as info:
        settings_from_mapping({'SENTRY_DSN': 'https://abc@o1.ingest.sentry.io'})  # no project ID
    assert 'abc@' not in str(info.value)  # the DSN is a secret
    with pytest.raises(ConfigError, match='DB_LOCK_WAIT_TIMEOUT'):
        settings_from_mapping({'DB_LOCK_WAIT_TIMEOUT': '9'})  # longer than Postfix waits
