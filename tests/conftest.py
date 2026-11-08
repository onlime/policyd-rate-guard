"""Shared fixtures.

DB tests (marker ``db``) need ``TEST_DATABASE_URL``, e.g. ``mysql://root:test@127.0.0.1:3306``. A fresh database
is created per test session (migrations applied with yoyo) and dropped afterwards. Without the variable, DB
tests are skipped.
"""

import logging
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pymysql
import pytest

from policyd_rate_guard.config import DbSettings, Settings
from policyd_rate_guard.db import Database
from policyd_rate_guard.log import LOGGER_NAME

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / 'database' / 'migrations'


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get('TEST_DATABASE_URL'):
        return
    skip = pytest.mark.skip(reason='TEST_DATABASE_URL not set')
    for item in items:
        if 'db' in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        return replace(Settings(), **overrides)

    return factory


@pytest.fixture
def logger() -> Iterator[logging.Logger]:
    log = logging.getLogger(LOGGER_NAME)
    old_level, old_propagate = log.level, log.propagate
    log.setLevel(logging.DEBUG)
    log.propagate = True  # so caplog sees the records
    yield log
    log.setLevel(old_level)
    log.propagate = old_propagate


def _server_kwargs(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    return {
        'host': parts.hostname or '127.0.0.1',
        'port': parts.port or 3306,
        'user': unquote(parts.username or 'root'),
        'password': unquote(parts.password or ''),
    }


@pytest.fixture(scope='session')
def db_settings() -> Iterator[DbSettings]:
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL not set')
    from yoyo import get_backend, read_migrations

    server = _server_kwargs(url)
    name = f'prg_test_{uuid.uuid4().hex[:12]}'
    admin = pymysql.connect(**server, autocommit=True)
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4')
        backend = get_backend(f'{url.rstrip("/")}/{name}')
        migrations = read_migrations(str(MIGRATIONS))
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
        backend.connection.close()
        yield DbSettings(
            host=server['host'],
            port=server['port'],
            user=server['user'],
            password=server['password'],
            database=name,
            pool_maxconnections=10,
        )
    finally:
        with admin.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS `{name}`')
        admin.close()


@pytest.fixture
def db(db_settings: DbSettings) -> Iterator[Database]:
    database = Database(db_settings)
    yield database
    database.close()


@pytest.fixture
def raw_db(db_settings: DbSettings) -> Iterator['pymysql.connections.Connection[Any]']:
    """A plain connection for setup and assertions, outside the pool (like another DB user, e.g. Airpane)."""
    conn = pymysql.connect(
        host=db_settings.host,
        port=db_settings.port,
        user=db_settings.user,
        password=db_settings.password,
        database=db_settings.database,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
    yield conn
    conn.close()


@pytest.fixture
def sender() -> str:
    """A sender address unique to the test."""
    return f'test-{uuid.uuid4().hex[:10]}@example.com'
