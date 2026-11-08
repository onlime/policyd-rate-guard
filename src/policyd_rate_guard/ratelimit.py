"""Atomic rate limit counting and message storage.

0.x read the counters, added in Python and wrote absolute values back, so parallel requests lost updates, the
first two mails of a new sender ran into a duplicate-key error (answered with DUNNO), and a stale ``quota`` was
written back over changes made meanwhile (e.g. by Airpane). Here a single upsert increments the counters in
place and holds the row lock until commit; the daemon never writes ``quota``.

Only portable SQL is used (no ``VALUES()``/row alias), so it runs on MySQL 8.4/9.x and MariaDB. The schema is
unchanged from 0.x, other tools read and write the ``ratelimits`` table directly.
"""

import random
import time
from dataclasses import dataclass
from datetime import datetime

from .db import ER_LOCK_DEADLOCK, Connection, Database, mysql_errno
from .protocol import clamp

COUNT_SQL = """
INSERT INTO `ratelimits` (`sender`, `quota`, `quota_reset`, `msg_counter`, `rcpt_counter`, `msg_total`, `rcpt_total`)
VALUES (%(sender)s, %(quota)s, %(quota)s, 1, %(rcpt)s, 1, %(rcpt)s)
ON DUPLICATE KEY UPDATE
    `msg_counter` = LEAST(`msg_counter` + 1, 4294967295),
    `rcpt_counter` = LEAST(`rcpt_counter` + %(rcpt)s, 4294967295),
    `msg_total` = LEAST(`msg_total` + 1, 4294967295),
    `rcpt_total` = LEAST(`rcpt_total` + %(rcpt)s, 4294967295)
"""

SELECT_SQL = """
SELECT `id`, `quota`, `quota_reset`, `msg_counter`, `rcpt_counter`
FROM `ratelimits` WHERE `sender` = %(sender)s FOR UPDATE
"""

INSERT_MESSAGE_SQL = """
INSERT INTO `messages` (`ratelimit_id`, `msgid`, `sender`, `rcpt_count`, `blocked`, `from_addr`, `to_addr`,
    `client_address`, `client_name`)
VALUES (%(ratelimit_id)s, %(msgid)s, %(sender)s, %(rcpt_count)s, %(blocked)s, %(from_addr)s, %(to_addr)s,
    %(client_address)s, %(client_name)s)
"""

# Counters and (unless locked) quotas are reset in one statement; `updated_at` is kept.
RESET_SQL = """
UPDATE `ratelimits` SET `msg_counter` = 0, `rcpt_counter` = 0,
    `quota` = IF(`quota_locked`, `quota`, `quota_reset`), `updated_at` = `updated_at`
"""

# A batch of old messages in the order of the created_at index (which carries the id), then deleted by id. A DELETE
# with ORDER BY and LIMIT leaves the plan to the optimizer, which may sort all matching rows for every batch: with
# years of rows (0.x kept them forever) a single batch then takes longer than the read timeout, and never finishes.
PURGE_SELECT_SQL = """
SELECT `id` FROM `messages` FORCE INDEX (`messages_created_at_index`)
WHERE `created_at` < DATE_SUB(CURDATE(), INTERVAL %(days)s DAY) ORDER BY `created_at`, `id` LIMIT %(batch)s
"""
PURGE_DELETE_SQL = 'DELETE FROM `messages` WHERE `id` IN %(ids)s'

# Touches no row: only checks the DELETE privilege for `check`
CHECK_DELETE_SQL = 'DELETE FROM `messages` WHERE `id` = 0'
CHECK_SENDER = 'policyd-rate-guard-check@invalid'

MAX_DEADLOCK_RETRIES = 3

# Column sizes of the `messages` and `ratelimits` tables
SENDER_MAX = 255
MSGID_MAX = 255
ADDR_MAX = 255
TEXT_ADDR_MAX = 1024
CLIENT_ADDRESS_MAX = 45
CLIENT_NAME_MAX = 255


@dataclass(frozen=True, slots=True)
class Decision:
    ratelimit_id: int
    quota: int
    quota_reset: int
    msg_counter: int
    rcpt_counter: int
    blocked: bool
    was_blocked: bool

    @property
    def crossed(self) -> bool:
        """True for exactly one request per period: the one that took the sender over the quota."""
        return self.blocked and not self.was_blocked


@dataclass(frozen=True, slots=True)
class MessageRecord:
    queue_id: str | None
    sender: str
    rcpt_count: int
    from_addr: str | None
    to_addr: str | None
    client_address: str | None
    client_name: str | None
    created_at: datetime


def is_over_quota(msg_counter: int, rcpt_counter: int, quota: int) -> bool:
    return msg_counter > quota or rcpt_counter > quota


def count_message(conn: Connection, sender: str, rcpt_count: int, default_quota: int) -> Decision:
    """Count one message with ``rcpt_count`` recipients for ``sender`` and decide whether it's blocked.

    Retried on deadlocks, which concurrent upserts of a new sender can cause. Lock wait timeouts are not retried
    (the session timeout is already the time budget) and propagate to the caller.
    """
    params = {'sender': sender, 'rcpt': rcpt_count, 'quota': default_quota}
    for attempt in range(MAX_DEADLOCK_RETRIES + 1):
        # An explicit transaction: otherwise DBUtils transparently retries a failed statement on a new connection,
        # where the uncommitted upsert is gone (old counters, nothing counted, no error)
        conn.begin()
        cursor = conn.cursor()
        try:
            cursor.execute(COUNT_SQL, params)
            cursor.execute(SELECT_SQL, params)
            row = cursor.fetchone()
            conn.commit()
        except Exception as e:
            conn.rollback()
            if mysql_errno(e) == ER_LOCK_DEADLOCK and attempt < MAX_DEADLOCK_RETRIES:
                time.sleep(random.uniform(0.005, 0.05) * (attempt + 1))  # noqa: S311 (jitter, not crypto)
                continue
            raise
        finally:
            cursor.close()
        break
    if row is None:  # pragma: no cover (the upsert guarantees the row)
        raise RuntimeError(f'ratelimit row for {sender!r} vanished')

    quota, msg, rcpt = int(row['quota']), int(row['msg_counter']), int(row['rcpt_counter'])
    return Decision(
        ratelimit_id=int(row['id']),
        quota=quota,
        quota_reset=int(row['quota_reset']),
        msg_counter=msg,
        rcpt_counter=rcpt,
        blocked=is_over_quota(msg, rcpt, quota),
        was_blocked=is_over_quota(msg - 1, rcpt - rcpt_count, quota),
    )


def store_message(conn: Connection, decision: Decision, record: MessageRecord) -> None:
    conn.begin()
    cursor = conn.cursor()
    try:
        cursor.execute(
            INSERT_MESSAGE_SQL,
            {
                'ratelimit_id': decision.ratelimit_id,
                'msgid': clamp(record.queue_id, MSGID_MAX),
                'sender': clamp(record.sender, SENDER_MAX),
                'rcpt_count': record.rcpt_count,
                'blocked': decision.blocked,
                'from_addr': clamp(record.from_addr, ADDR_MAX),
                'to_addr': clamp(record.to_addr, TEXT_ADDR_MAX),
                'client_address': clamp(record.client_address, CLIENT_ADDRESS_MAX),
                'client_name': clamp(record.client_name, CLIENT_NAME_MAX),
            },
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def reset_counters(db: Database) -> int:
    """Reset all counters, and quotas that aren't locked. Returns the number of changed rows."""
    with db.connection() as conn:
        conn.begin()
        cursor = conn.cursor()
        try:
            changed = cursor.execute(RESET_SQL)
            conn.commit()
        finally:
            cursor.close()
    return changed


def purge_messages(db: Database, days: int, batch_size: int = 10000) -> int:
    """Delete messages older than ``days`` in batches (short locks, even for a first purge of years of rows)."""
    deleted = 0
    with db.connection() as conn:
        while True:
            conn.begin()
            cursor = conn.cursor()
            try:
                cursor.execute(PURGE_SELECT_SQL, {'days': days, 'batch': batch_size})
                ids = [row['id'] for row in cursor.fetchall()]
                if ids:
                    deleted += cursor.execute(PURGE_DELETE_SQL, {'ids': ids})
                conn.commit()
            finally:
                cursor.close()
            if len(ids) < batch_size:
                return deleted


def check_writes(db: Database, default_quota: int) -> None:
    """Run the statements of a policy request and of the cleanup in a transaction that is rolled back.

    Raises if the database user lacks a privilege or the server can't run them (e.g. READ COMMITTED with
    statement-based binary logging), which a SELECT alone wouldn't show.
    """
    params = {'sender': CHECK_SENDER, 'rcpt': 1, 'quota': default_quota}
    with db.connection() as conn:
        conn.begin()
        cursor = conn.cursor()
        try:
            cursor.execute(COUNT_SQL, params)
            cursor.execute(SELECT_SQL, params)
            row = cursor.fetchone()
            cursor.execute(INSERT_MESSAGE_SQL, {
                'ratelimit_id': row['id'] if row else 0, 'msgid': None, 'sender': CHECK_SENDER, 'rcpt_count': 1,
                'blocked': False, 'from_addr': None, 'to_addr': None, 'client_address': None, 'client_name': None,
            })  # fmt: skip
            cursor.execute(CHECK_DELETE_SQL)
            # the cleanup's statements (e.g. the purge needs the index on created_at)
            cursor.execute(RESET_SQL + 'WHERE `sender` = %(sender)s', params)
            cursor.execute(PURGE_SELECT_SQL, {'days': 0, 'batch': 1})
            cursor.fetchall()
        finally:
            conn.rollback()
            cursor.close()
