import types
from typing import Any

import pymysql
import pytest

from policyd_rate_guard import db as db_module
from policyd_rate_guard.config import DbSettings
from policyd_rate_guard.db import Database, connect_kwargs, session_statements
from policyd_rate_guard.ratelimit import count_message


def test_connect_over_unix_socket_or_tcp() -> None:
    unix = connect_kwargs(DbSettings(unix_socket='/run/mysqld/mysqld.sock', password='secret'))
    assert unix['unix_socket'] == '/run/mysqld/mysqld.sock'
    assert 'host' not in unix
    assert 'port' not in unix
    tcp = connect_kwargs(DbSettings(host='db.example.net', port=3307))
    assert (tcp['host'], tcp['port']) == ('db.example.net', 3307)
    assert 'unix_socket' not in tcp
    for kwargs in (unix, tcp):
        assert kwargs['connect_timeout'] > 0
        assert kwargs['read_timeout'] > 0
        assert kwargs['write_timeout'] > 0
        assert kwargs['autocommit'] is False


def test_session_statements() -> None:
    assert session_statements(DbSettings(lock_wait_timeout=7)) == [
        'SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED',
        'SET SESSION innodb_lock_wait_timeout = 7',
        'SET SESSION lock_wait_timeout = 7',
    ]


class FakeServer:
    """A DB-API driver for the real DBUtils pool: one committed counter row, statements per connection."""

    def __init__(self, fail: str) -> None:
        self.fail = fail
        self.committed = {'msg': 5, 'rcpt': 5}
        self.statements: list[tuple[int, str]] = []
        self.connections = 0

    def connect(self, **_: Any) -> 'FakeConnection':
        self.connections += 1
        return FakeConnection(self, self.connections)


class FakeConnection:
    def __init__(self, server: FakeServer, number: int) -> None:
        self.server, self.number, self.pending = server, number, None

    def cursor(self, *_: Any) -> 'FakeCursor':
        return FakeCursor(self)

    def begin(self) -> None:
        pass

    def commit(self) -> None:
        if self.pending:
            self.server.committed = self.pending
        self.pending = None

    def rollback(self) -> None:
        self.pending = None

    def ping(self, *_: Any) -> bool:
        return True

    def close(self) -> None:
        pass


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn, self.row = conn, None

    def execute(self, sql: str, args: object = None) -> int:
        if sql.startswith('SET '):
            return 0
        kind = 'INSERT' if 'INSERT' in sql else 'SELECT'
        server = self.conn.server
        server.statements.append((self.conn.number, kind))
        if server.fail == 'lock wait' and kind == 'INSERT':
            raise pymysql.err.OperationalError(1205, 'Lock wait timeout exceeded')
        if server.fail == 'lost connection' and kind == 'SELECT' and self.conn.number == 1:
            self.conn.pending = None  # the server rolls back the uncommitted upsert
            raise pymysql.err.OperationalError(2013, 'Lost connection to MySQL server during query')
        if kind == 'INSERT':
            c = server.committed
            self.conn.pending = {'msg': c['msg'] + 1, 'rcpt': c['rcpt'] + 1}
        else:
            r = self.conn.pending or server.committed
            self.row = {'id': 1, 'quota': 1000, 'quota_reset': 1000, 'msg_counter': r['msg'], 'rcpt_counter': r['rcpt']}
        return 1

    def fetchone(self) -> Any:
        return self.row

    def close(self) -> None:
        pass


@pytest.mark.parametrize('fail', ['lost connection', 'lock wait'])
def test_database_errors_in_a_transaction_are_raised_at_once(fail: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without begin(), DBUtils retried a failed statement on a new connection: after a lost connection the SELECT
    read the old counters there (the mail was answered OK and not counted, without any error), and a lock wait
    timeout took three times as long as configured."""
    server = FakeServer(fail)
    driver = types.SimpleNamespace(
        connect=server.connect, threadsafety=1, err=pymysql.err, cursors=pymysql.cursors,
        OperationalError=pymysql.err.OperationalError, InterfaceError=pymysql.err.InterfaceError,
        InternalError=pymysql.err.InternalError,
    )  # fmt: skip
    monkeypatch.setattr(db_module, 'pymysql', driver)
    database = Database(DbSettings())
    with database.connection() as conn, pytest.raises(pymysql.err.OperationalError):
        count_message(conn, 'u@example.com', 1, 1000)
    database.close()
    assert server.committed == {'msg': 5, 'rcpt': 5}
    expected = [(1, 'INSERT'), (1, 'SELECT')] if fail == 'lost connection' else [(1, 'INSERT')]
    assert server.statements == expected  # nothing repeated, on no other connection
