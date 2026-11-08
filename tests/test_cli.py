import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from policyd_rate_guard import __version__
from policyd_rate_guard.cli import main
from policyd_rate_guard.config import DbSettings

from .helpers import postfix_request

ENV_KEYS = ('POLICYD_ENV_FILE', 'SENTRY_DSN', 'LISTEN_FDS', 'LISTEN_PID', 'NOTIFY_SOCKET')


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


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
    path = env_file(
        tmp_path, LOG_FILE=log_file, SYSLOG='True', DB_HOST='127.0.0.1', DB_PORT='1', DB_CONNECT_TIMEOUT='1'
    )
    assert main(['--env-file', str(path), 'check']) == 1  # fails on the database, not on the log file
    assert not log_file.parent.exists()


def test_check_and_cleanup_fail_without_database(tmp_path: Path) -> None:
    path = env_file(tmp_path, DB_HOST='127.0.0.1', DB_PORT='1', DB_CONNECT_TIMEOUT='1', LOG_CONSOLE='True')
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
