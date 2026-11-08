"""Rate limit logic. Tests marked ``db`` run against a real MySQL/MariaDB server."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pymysql
import pytest

from policyd_rate_guard.config import DbSettings, Settings, TcpAddress, WebhookSettings
from policyd_rate_guard.db import Database, mysql_errno
from policyd_rate_guard.protocol import parse_request
from policyd_rate_guard.ratelimit import (
    Decision,
    count_message,
    is_over_quota,
    purge_messages,
    reset_counters,
)
from policyd_rate_guard.server import PolicyServer, bind_listen_socket
from policyd_rate_guard.service import PolicyService

from .helpers import postfix_request

WEBHOOK = WebhookSettings(enabled=True, url='https://example.com/{sender}', secret='c2VjcmV0')


def test_is_over_quota() -> None:
    assert not is_over_quota(10, 10, 10)
    assert is_over_quota(11, 10, 10)
    assert is_over_quota(1, 11, 10)


def test_crossed() -> None:
    assert Decision(1, 5, 5, 6, 6, blocked=True, was_blocked=False).crossed
    assert not Decision(1, 5, 5, 7, 7, blocked=True, was_blocked=True).crossed
    assert not Decision(1, 5, 5, 5, 5, blocked=False, was_blocked=False).crossed


def test_deadlock_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    deadlock = pymysql.err.OperationalError(1213, 'Deadlock found when trying to get lock')
    cursor = MagicMock()
    cursor.execute.side_effect = [deadlock, deadlock, 1, 1]
    cursor.fetchone.return_value = {'id': 7, 'quota': 10, 'quota_reset': 10, 'msg_counter': 1, 'rcpt_counter': 2}
    conn = MagicMock()
    conn.cursor.return_value = cursor
    decision = count_message(conn, 'u@example.com', 2, 10)
    assert decision == Decision(7, 10, 10, 1, 2, blocked=False, was_blocked=False)
    assert conn.rollback.call_count == 2


def test_other_errors_are_not_retried() -> None:
    cursor = MagicMock()
    cursor.execute.side_effect = pymysql.err.OperationalError(1205, 'Lock wait timeout exceeded')
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with pytest.raises(pymysql.err.OperationalError) as info:
        count_message(conn, 'u@example.com', 1, 10)
    assert mysql_errno(info.value) == 1205
    assert cursor.execute.call_count == 1
    assert mysql_errno(ValueError('x')) is None


# --- against a real database -------------------------------------------------------------------------------------


def counters(raw_db: Any, sender: str) -> dict[str, Any]:
    with raw_db.cursor() as cursor:
        cursor.execute('SELECT * FROM `ratelimits` WHERE `sender` = %s', (sender,))
        row: dict[str, Any] = cursor.fetchone()
        return row


def decide(svc: PolicyService, sasl_username: str, rcpt: int = 1, **kwargs: Any) -> Any:
    return svc.handle(parse_request(postfix_request(sasl_username, recipient_count=rcpt, **kwargs)))


@pytest.mark.db
def test_new_sender_gets_default_quota(db: Database, raw_db: Any, sender: str) -> None:
    with db.connection() as conn:
        decision = count_message(conn, sender, 3, 1000)
    assert decision.quota == 1000
    assert (decision.msg_counter, decision.rcpt_counter, decision.blocked) == (1, 3, False)
    row = counters(raw_db, sender)
    assert (row['quota'], row['quota_reset'], row['msg_total'], row['rcpt_total']) == (1000, 1000, 1, 3)


@pytest.mark.db
def test_blocking_semantics(
    db: Database, raw_db: Any, sender: str, make_settings: Callable[..., Settings], logger: logging.Logger
) -> None:
    svc = PolicyService(make_settings(quota=3, webhook=WEBHOOK), db, logger)
    outcomes = [decide(svc, sender) for _ in range(5)]
    assert [o.action.split()[0] for o in outcomes] == ['OK', 'OK', 'OK', 'DEFER_IF_PERMIT', 'DEFER_IF_PERMIT']
    assert [o.notify is not None for o in outcomes] == [False, False, False, True, False]  # webhook once
    row = counters(raw_db, sender)
    # Blocked messages are still counted (as in 0.x), so retries keep raising the counters
    assert (row['msg_counter'], row['rcpt_counter'], row['msg_total']) == (5, 5, 5)
    with raw_db.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS n, SUM(`blocked`) AS blocked FROM `messages` WHERE `sender` = %s', (sender,))
        assert cursor.fetchone() == {'n': 5, 'blocked': 2}


@pytest.mark.db
def test_message_counter_blocks_too(
    db: Database, sender: str, make_settings: Callable[..., Settings], logger: logging.Logger
) -> None:
    svc = PolicyService(make_settings(quota=2), db, logger)
    assert [decide(svc, sender, rcpt=0).action.split()[0] for _ in range(3)] == ['OK', 'OK', 'DEFER_IF_PERMIT']


@pytest.mark.db
def test_quota_changes_by_others_are_never_overwritten(
    db: Database, raw_db: Any, sender: str, make_settings: Callable[..., Settings], logger: logging.Logger
) -> None:
    """F2: 0.x wrote the stale quota back, undoing a concurrent change by Airpane/support."""
    svc = PolicyService(make_settings(quota=2), db, logger)
    decide(svc, sender)
    decide(svc, sender)
    with raw_db.cursor() as cursor:
        cursor.execute('UPDATE `ratelimits` SET `quota` = 100 WHERE `sender` = %s', (sender,))
    assert decide(svc, sender).action == 'OK'
    assert counters(raw_db, sender)['quota'] == 100


@pytest.mark.db
def test_long_values_are_clamped(db: Database, raw_db: Any, sender: str, make_settings: Callable[..., Settings],
                                 logger: logging.Logger) -> None:  # fmt: skip
    """F4: a From over 255 characters failed with 'Data too long' under strict sql_mode, after counting."""
    svc = PolicyService(make_settings(quota=0), db, logger)
    outcome = decide(svc, sender, sender='z' * 300 + '@example.com', client_name='c' * 300)
    assert outcome.action.startswith('DEFER_IF_PERMIT')
    with raw_db.cursor() as cursor:
        cursor.execute('SELECT `from_addr`, `client_name` FROM `messages` WHERE `sender` = %s', (sender,))
        row = cursor.fetchone()
    assert row == {'from_addr': 'z' * 255, 'client_name': 'c' * 255}


@pytest.mark.db
def test_concurrent_first_mails_are_all_counted(
    db: Database, raw_db: Any, sender: str, make_settings: Callable[..., Settings], logger: logging.Logger
) -> None:
    """F2: in 0.x, 30 parallel first mails of a new sender were counted as 4, and 2 got DUNNO."""
    svc = PolicyService(make_settings(quota=10, webhook=WEBHOOK), db, logger)
    barrier = threading.Barrier(50)

    def one(_: int) -> Any:
        barrier.wait()
        return decide(svc, sender)

    with ThreadPoolExecutor(50) as pool:
        outcomes = list(pool.map(one, range(50)))
    actions = [o.action.split()[0] for o in outcomes]
    assert actions.count('OK') == 10
    assert actions.count('DEFER_IF_PERMIT') == 40
    assert 'DUNNO' not in actions
    assert sum(o.notify is not None for o in outcomes) == 1
    row = counters(raw_db, sender)
    assert (row['msg_counter'], row['rcpt_counter'], row['msg_total'], row['rcpt_total']) == (50, 50, 50, 50)


@pytest.mark.db
def test_lock_wait_timeout_answers_fail_action_quickly(
    db_settings: DbSettings, raw_db: Any, sender: str, make_settings: Callable[..., Settings], logger: logging.Logger
) -> None:
    """F6: without timeouts, a locked row (e.g. a migration) made requests pile up indefinitely."""
    database = Database(replace(db_settings, lock_wait_timeout=1))
    svc = PolicyService(make_settings(), database, logger)
    decide(svc, sender)
    other = pymysql.connect(host=db_settings.host, port=db_settings.port, user=db_settings.user,
                            password=db_settings.password, database=db_settings.database)  # fmt: skip
    try:
        with other.cursor() as cursor:
            cursor.execute('SELECT * FROM `ratelimits` WHERE `sender` = %s FOR UPDATE', (sender,))
        started = time.monotonic()
        assert decide(svc, sender).action == 'DUNNO'
        assert time.monotonic() - started < 5
    finally:
        other.rollback()
        other.close()
        database.close()


@pytest.mark.db
def test_reset_counters(db: Database, raw_db: Any, sender: str) -> None:
    locked, unlocked = f'locked-{sender}', f'unlocked-{sender}'
    with raw_db.cursor() as cursor:
        cursor.executemany(
            'INSERT INTO `ratelimits` (`sender`, `quota`, `quota_reset`, `quota_locked`, `msg_counter`, '
            '`rcpt_counter`, `msg_total`, `rcpt_total`, `updated_at`) VALUES (%s, 3000, 1000, %s, 60, 70, 460, 470, '
            "'2026-01-01 00:00:00')",
            [(locked, 1), (unlocked, 0)],
        )
    assert reset_counters(db) >= 2
    rows = {s: counters(raw_db, s) for s in (locked, unlocked)}
    assert (rows[locked]['quota'], rows[locked]['msg_counter'], rows[locked]['rcpt_counter']) == (3000, 0, 0)
    assert (rows[unlocked]['quota'], rows[unlocked]['msg_counter'], rows[unlocked]['rcpt_counter']) == (1000, 0, 0)
    assert rows[unlocked]['msg_total'] == 460
    assert str(rows[unlocked]['updated_at']) == '2026-01-01 00:00:00'


@pytest.mark.db
def test_purge_in_batches(db: Database, raw_db: Any, sender: str) -> None:
    with raw_db.cursor() as cursor:
        cursor.execute('DELETE FROM `messages`')
        rows = [(sender, 400) for _ in range(25)] + [(sender, 10) for _ in range(5)]
        cursor.executemany(
            'INSERT INTO `messages` (`sender`, `rcpt_count`, `blocked`, `created_at`) '
            'VALUES (%s, 1, 0, DATE_SUB(NOW(), INTERVAL %s DAY))',
            rows,
        )
    assert purge_messages(db, days=365, batch_size=10) == 25
    with raw_db.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS n FROM `messages`')
        assert cursor.fetchone() == {'n': 5}


@pytest.mark.db
async def test_server_with_real_database(
    db: Database, raw_db: Any, sender: str, make_settings: Callable[..., Settings], logger: logging.Logger
) -> None:
    settings = make_settings(quota=20, listen=TcpAddress('127.0.0.1', 0))
    server = PolicyServer(settings, PolicyService(settings, db, logger), None, logger)
    sock = bind_listen_socket(settings)
    await server.start([sock])
    port = sock.getsockname()[1]

    async def client(i: int) -> list[bytes]:
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        answers = []
        for j in range(2):
            writer.write(postfix_request(sender, queue_id=f'S{i:02d}{j}'))
            await writer.drain()
            answers.append(await asyncio.wait_for(reader.readuntil(b'\n\n'), 10))
        writer.close()
        return answers

    results = [a for answers in await asyncio.gather(*(client(i) for i in range(30))) for a in answers]
    await server.shutdown()
    assert results.count(b'action=OK\n\n') == 20
    assert len(results) == 60
    row = counters(raw_db, sender)
    assert (row['msg_counter'], row['rcpt_counter']) == (60, 60)
