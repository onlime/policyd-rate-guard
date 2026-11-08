"""Database connection pool (DBUtils PooledDB over PyMySQL) with timeouts on every level.

Without timeouts, a slow or locked MySQL server lets requests pile up until ``max_connections`` of the server is
exhausted, which on a mail server also breaks Postfix's own MySQL lookups.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import pymysql
import pymysql.cursors
from dbutils.pooled_db import PooledDB

from .config import DbSettings

# MySQL/MariaDB error numbers
ER_LOCK_WAIT_TIMEOUT = 1205
ER_LOCK_DEADLOCK = 1213


class Cursor(Protocol):
    rowcount: int

    def execute(self, query: str, args: object = None) -> int: ...
    def fetchone(self) -> dict[str, Any] | None: ...
    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


def session_statements(settings: DbSettings) -> list[str]:
    """Statements run once per new connection (both syntaxes work on MySQL 8.4+/9.x and MariaDB)."""
    timeout = int(settings.lock_wait_timeout)
    return [
        'SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED',
        f'SET SESSION innodb_lock_wait_timeout = {timeout}',
        f'SET SESSION lock_wait_timeout = {timeout}',
    ]


def connect_kwargs(settings: DbSettings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        'user': settings.user,
        'password': settings.password,
        'database': settings.database,
        'charset': 'utf8mb4',
        'connect_timeout': settings.connect_timeout,
        'read_timeout': settings.read_timeout,
        'write_timeout': settings.write_timeout,
        'autocommit': False,
        'cursorclass': pymysql.cursors.DictCursor,
    }
    if settings.unix_socket:
        kwargs['unix_socket'] = settings.unix_socket
    else:
        kwargs['host'] = settings.host
        kwargs['port'] = settings.port
    return kwargs


class Database:
    def __init__(self, settings: DbSettings) -> None:
        self._pool = PooledDB(
            creator=pymysql,
            mincached=settings.pool_mincached,
            maxcached=settings.pool_maxcached,
            maxconnections=settings.pool_maxconnections,
            blocking=True,  # wait for a free connection instead of failing (callers are bounded by the executor)
            maxusage=settings.pool_maxusage,
            setsession=session_statements(settings),
            ping=1,  # check connections when taken from the pool (server-side wait_timeout)
            reset=True,  # roll back on return
            **connect_kwargs(settings),
        )

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        conn: Connection = self._pool.connection()
        try:
            yield conn
        finally:
            conn.close()  # returns it to the pool

    def close(self) -> None:
        self._pool.close()


def mysql_errno(error: BaseException) -> int | None:
    """The MySQL error number of a PyMySQL error, if any."""
    if isinstance(error, pymysql.err.MySQLError) and error.args and isinstance(error.args[0], int):
        return error.args[0]
    return None
