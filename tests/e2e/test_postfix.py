"""End-to-end tests through a real Postfix (docker compose stack, see docker-compose.yml).

Needs E2E_SMTP_PORT (submission), E2E_DATABASE_URL and E2E_WEBHOOK_URL; skipped otherwise.
"""

import json
import os
import smtplib
import time
import urllib.request
from base64 import b64decode
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import jwt
import pymysql
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.environ.get('E2E_SMTP_PORT'), reason='E2E_SMTP_PORT not set (docker compose stack)'),
]

PASSWORD = 'Example1234'
SECRET = 'Wk9YZXliVlVtY2pQcFlFUm9KY1U1ZkFFaUpWTk1FU20='  # .env.docker
QUOTA = 5  # .env.docker


@pytest.fixture
def db() -> Iterator[Any]:
    url = urlsplit(os.environ['E2E_DATABASE_URL'])
    conn = pymysql.connect(
        host=url.hostname, port=url.port or 3306, user=url.username, password=url.password or '',
        database=url.path.lstrip('/'), autocommit=True, cursorclass=pymysql.cursors.DictCursor,
    )  # fmt: skip
    yield conn
    conn.close()


def webhook(method: str, path: str = '/calls') -> Any:
    request = urllib.request.Request(os.environ['E2E_WEBHOOK_URL'] + path, method=method)  # noqa: S310
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return json.load(response)


@pytest.fixture
def fresh(db: Any) -> Any:
    """Reset a test user's counters and the recorded webhook calls."""

    def reset(user: str) -> str:
        with db.cursor() as cursor:
            cursor.execute('DELETE FROM `messages` WHERE `sender` = %s', (user,))
            cursor.execute('DELETE FROM `ratelimits` WHERE `sender` = %s', (user,))
        webhook('DELETE')
        return user

    return reset


def send(user: str, from_addr: str = 'sender@example.com', rcpts: list[str] | None = None,
         helo: str | None = None) -> None:  # fmt: skip
    with smtplib.SMTP('127.0.0.1', int(os.environ['E2E_SMTP_PORT']), local_hostname=helo, timeout=30) as smtp:
        smtp.login(user, PASSWORD)
        smtp.sendmail(from_addr, rcpts or ['rcpt@example.org'], b'Subject: e2e\r\n\r\nTest\r\n')


def send_bdat(user: str) -> tuple[int, bytes]:
    """CHUNKING (BDAT) instead of DATA, as many clients use it when Postfix offers it."""
    body = b'Subject: e2e bdat\r\n\r\nTest\r\n'
    with smtplib.SMTP('127.0.0.1', int(os.environ['E2E_SMTP_PORT']), timeout=30) as smtp:
        smtp.login(user, PASSWORD)
        smtp.mail(user)
        smtp.rcpt('rcpt@example.org')
        smtp.putcmd('BDAT', f'{len(body)} LAST')
        smtp.send(body)
        return smtp.getreply()


def webhook_calls(expected: int) -> list[Any]:
    """The webhook runs after the reply, in its own thread: wait for it."""
    for _ in range(50):
        calls: list[Any] = webhook('GET')
        if len(calls) >= expected:
            return calls
        time.sleep(0.1)
    return calls


def counters(db: Any, user: str) -> tuple[int, int]:
    with db.cursor() as cursor:
        cursor.execute('SELECT `msg_counter`, `rcpt_counter` FROM `ratelimits` WHERE `sender` = %s', (user,))
        row = cursor.fetchone()
    return (row['msg_counter'], row['rcpt_counter']) if row else (0, 0)


def test_quota_blocks_at_data_and_webhook_fires_once(fresh: Any, db: Any) -> None:
    user = fresh('test01@example.com')
    for _ in range(QUOTA):
        send(user)
    for _ in range(2):
        with pytest.raises(smtplib.SMTPDataError) as info:
            send(user)
        assert info.value.smtp_code == 450
        assert b'Rate limit reached' in info.value.smtp_error
    assert counters(db, user) == (QUOTA + 2, QUOTA + 2)

    calls = webhook_calls(1)
    assert len(calls) == 1
    call = calls[0]
    assert call['path'] == '/api/policyd/test01@example.com'
    assert call['json']['sender'] == user
    assert call['json']['used'] == QUOTA + 1
    claims = jwt.decode(call['authorization'].removeprefix('Bearer '), b64decode(SECRET), algorithms=['HS256'])
    assert claims['sub'] == user


def test_all_recipients_are_counted(fresh: Any, db: Any) -> None:
    user = fresh('test02@example.com')
    send(user, rcpts=['a@example.org', 'b@example.org', 'c@example.org'])
    assert counters(db, user) == (1, 3)


def test_padded_client_values_are_counted(fresh: Any, db: Any) -> None:
    """With 0.x, padding MAIL FROM/HELO pushed sasl_username beyond the 2048 bytes it read: not counted."""
    user = fresh('test03@example.com')
    send(user, from_addr='x' * 1900 + '@example.com')
    send(user, helo='h' * 60 + '.' + 'e' * 60 + '.' + 'l' * 60 + '.example')
    assert counters(db, user) == (2, 2)


def test_bdat_is_counted_and_blocked(fresh: Any, db: Any) -> None:
    """Postfix applies smtpd_data_restrictions to BDAT too: no way around the limit with CHUNKING."""
    user = fresh('test02@example.com')
    for _ in range(QUOTA):
        assert send_bdat(user)[0] == 250
    code, message = send_bdat(user)
    assert code == 450
    assert b'Rate limit reached' in message
    assert counters(db, user) == (QUOTA + 1, QUOTA + 1)
