import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pymysql
import pytest

from policyd_rate_guard import __version__
from policyd_rate_guard import cli as cli_module
from policyd_rate_guard.cli import main
from policyd_rate_guard.config import DbSettings

from .helpers import postfix_request

ENV_KEYS = {'POLICYD_ENV_FILE', 'LISTEN_FDS', 'LISTEN_PID', 'NOTIFY_SOCKET', 'QUOTA', 'SOCKET', 'SYSLOG',
            'FAIL_ACTION', 'ACTION_TEXT_BLOCKED', 'MESSAGE_RETENTION'}  # fmt: skip
ENV_PREFIXES = ('DB_', 'LOG_', 'WEBHOOK_', 'SENTRY_')


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's exported configuration must not change the results (the environment wins over env files)."""
    for key in list(os.environ):
        if key in ENV_KEYS or key.startswith(ENV_PREFIXES):
            monkeypatch.delenv(key)


def env_file(tmp_path: Path, db: DbSettings | None = None, **values: object) -> Path:
    lines = [f'{key}={value}' for key, value in values.items()]
    if db is not None:
        d = asdict(db)
        lines += [f'DB_HOST={d["host"]}', f'DB_PORT={d["port"]}', f'DB_USER={d["user"]}',
                  f'DB_PASSWORD="{d["password"]}"', f'DB_DATABASE={d["database"]}']  # fmt: skip
    path = tmp_path / 'policyd.env'
    path.write_text('\n'.join(lines) + '\n')
    return path


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(['--version'])
    assert info.value.code == 0
    assert capsys.readouterr().out.strip() == f'policyd-rate-guard {__version__}'


def test_config_errors_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(['--env-file', str(tmp_path / 'missing.env'), 'check']) == 2
    assert 'Env file not found' in capsys.readouterr().err
    assert main(['--env-file', str(env_file(tmp_path, QUOTA='lots')), 'check']) == 2
    assert 'QUOTA: expected an integer' in capsys.readouterr().err


def test_serve_requires_socket_activation_when_asked(tmp_path: Path) -> None:
    path = env_file(tmp_path, LOG_CONSOLE='True')
    assert main(['--env-file', str(path), 'serve', '--require-socket-activation']) == 1


def test_check_never_touches_the_log_file(tmp_path: Path) -> None:
    """`check` runs as root before the service starts: it must not create the service's log file (as root)."""
    log_file = tmp_path / 'missing-dir' / 'policyd.log'
    path = env_file(tmp_path, LOG_FILE=log_file, SYSLOG='True', DB_HOST='127.0.0.1', DB_PORT='1')
    assert main(['--env-file', str(path), 'check']) == 1  # fails on the database, not on the log file
    assert not log_file.parent.exists()


def test_check_and_cleanup_fail_without_database(tmp_path: Path) -> None:
    path = env_file(tmp_path, DB_HOST='127.0.0.1', DB_PORT='1', LOG_CONSOLE='True')
    assert main(['--env-file', str(path), 'check']) == 1
    assert main(['--env-file', str(path), 'cleanup']) == 1


@pytest.mark.db
def test_check_and_cleanup(tmp_path: Path, db_settings: DbSettings, capsys: pytest.CaptureFixture[str]) -> None:
    path = env_file(tmp_path, db_settings, MESSAGE_RETENTION='365', LOG_CONSOLE='True')
    assert main(['--env-file', str(path), 'check']) == 0
    assert 'configuration and database OK' in capsys.readouterr().out
    assert main(['--env-file', str(path), 'cleanup']) == 0
    assert 'Deleted 0 old messages (retention: 365 days)' in capsys.readouterr().err


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port: int = sock.getsockname()[1]
        return port


def test_daemon_process_serves_and_stops_on_sigterm(tmp_path: Path) -> None:
    port = free_port()
    log_file = tmp_path / 'policyd.log'
    path = env_file(tmp_path, SOCKET=f'"127.0.0.1,{port}"', LOG_FILE=log_file, DB_PORT='1')
    env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    proc = subprocess.Popen([sys.executable, '-m', 'policyd_rate_guard', '--env-file', str(path)], env=env)  # noqa: S603
    try:
        for _ in range(100):
            try:
                conn = socket.create_connection(('127.0.0.1', port), timeout=5)
                break
            except ConnectionRefusedError:
                time.sleep(0.05)
        else:
            pytest.fail('daemon did not start')
        with conn:
            conn.sendall(postfix_request(None))  # no sasl_username: answered without the DB
            assert conn.recv(100) == b'action=DUNNO\n\n'
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(10) == 0
    finally:
        if proc.poll() is None:  # pragma: no cover
            proc.kill()
    log = log_file.read_text()
    assert f'policyd-rate-guard {__version__} starting' in log
    assert f'Listening on inet:127.0.0.1:{port}' in log
    assert log.rstrip().endswith('INFO Stopped')


def raise_error(*_: object) -> int:
    raise RuntimeError('boom')


def test_cleanup_fails_only_when_the_reset_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """systemd retries the unit on failure: after a failed reset, not after a failed purge (it would reset again)."""
    path = env_file(tmp_path, MESSAGE_RETENTION='365', LOG_CONSOLE='True')
    monkeypatch.setattr(cli_module, 'reset_counters', raise_error)
    assert main(['--env-file', str(path), 'cleanup']) == 1
    assert 'Resetting the counters failed' in capsys.readouterr().err
    monkeypatch.setattr(cli_module, 'reset_counters', lambda db: 3)
    monkeypatch.setattr(cli_module, 'purge_messages', raise_error)
    assert main(['--env-file', str(path), 'cleanup']) == 0
    assert 'Purging old messages failed' in capsys.readouterr().err


def test_sentry_failure_does_not_stop_the_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = env_file(tmp_path, LOG_CONSOLE='True')
    monkeypatch.setattr(cli_module, 'init_sentry', raise_error)
    monkeypatch.setattr(cli_module, 'reset_counters', lambda db: 0)
    assert main(['--env-file', str(path), 'cleanup']) == 0
    assert 'Sentry could not be initialized, continuing without it' in capsys.readouterr().err


@pytest.mark.db
def test_check_fails_without_write_privileges(
    tmp_path: Path, db_settings: DbSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    """A SELECT alone passed with a read-only user, and then every request failed open."""
    admin = pymysql.connect(host=db_settings.host, port=db_settings.port, user=db_settings.user,
                            password=db_settings.password, autocommit=True)  # fmt: skip
    try:
        with admin.cursor() as cursor:
            cursor.execute("CREATE USER IF NOT EXISTS 'prg_readonly'@'%' IDENTIFIED BY 'Readonly-1234'")
            cursor.execute(f"GRANT SELECT ON `{db_settings.database}`.* TO 'prg_readonly'@'%'")
        readonly = DbSettings(host=db_settings.host, port=db_settings.port, user='prg_readonly',
                              password='Readonly-1234', database=db_settings.database)  # fmt: skip
        path = env_file(tmp_path, readonly, LOG_CONSOLE='True')
        assert main(['--env-file', str(path), 'check']) == 1
        assert 'Database check failed' in capsys.readouterr().err
    finally:
        with admin.cursor() as cursor:
            cursor.execute("DROP USER IF EXISTS 'prg_readonly'@'%'")
        admin.close()


@pytest.mark.db
def test_cleanup_fails_on_a_locked_row(
    tmp_path: Path, db_settings: DbSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reset is one statement: a row locked longer than the lock wait makes it fail (and systemd retry it)."""
    other = pymysql.connect(host=db_settings.host, port=db_settings.port, user=db_settings.user,
                            password=db_settings.password, database=db_settings.database)  # fmt: skip
    try:
        with other.cursor() as cursor:
            cursor.execute("INSERT INTO `ratelimits` (`sender`) VALUES ('locked@example.com') "
                           'ON DUPLICATE KEY UPDATE `msg_counter` = `msg_counter`')  # fmt: skip
            other.commit()
            cursor.execute("SELECT * FROM `ratelimits` WHERE `sender` = 'locked@example.com' FOR UPDATE")
        path = env_file(tmp_path, db_settings, DB_LOCK_WAIT_TIMEOUT='1', LOG_CONSOLE='True')
        started = time.monotonic()
        assert main(['--env-file', str(path), 'cleanup']) == 1
        assert time.monotonic() - started < 5
        assert 'Resetting the counters failed' in capsys.readouterr().err
    finally:
        other.rollback()
        other.close()
