"""End-to-end tests through a real Postfix (docker compose stack, see docker-compose.yml).

Needs E2E_SMTP_PORT (submission), E2E_DATABASE_URL and E2E_WEBHOOK_URL; skipped otherwise.
"""

import json
import os
import re
import smtplib
import subprocess
import time
import urllib.request
from base64 import b64decode
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTPUTF8
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jwt
import pymysql
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.environ.get('E2E_SMTP_PORT'), reason='E2E_SMTP_PORT not set (docker compose stack)'),
]

ROOT = Path(__file__).resolve().parents[2]
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
    """The webhook runs after the reply, in its own thread: wait for it, and a bit longer for one too many."""
    for _ in range(50):
        calls: list[Any] = webhook('GET')
        if len(calls) >= expected:
            time.sleep(0.5)
            return list(webhook('GET'))
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
    """One mail to three recipients counts once as message, three times as recipient (more cases further below)."""
    user = fresh('test02@example.com')
    send(user, rcpts=['to@example.org', 'cc@example.org', 'bcc@example.org'])
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


# --- A dataset of real mails: SMTP submission with SASL login through Postfix, then the reply, the counters, the
# `messages` row and the daemon's log line are checked. Postfix counts envelope recipients (RCPT TO), so To, Cc and
# Bcc all count, and so does a duplicate; a recipient Postfix rejects doesn't.


@dataclass(frozen=True)
class Mail:
    to: tuple[str, ...] = ()
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    envelope_from: str | None = None  # None: the SASL user
    header_from: str | None = None
    utf8: bool = False

    def rcpts(self) -> list[str]:
        return [*self.to, *self.cc, *self.bcc]

    def message(self, user: str) -> bytes:
        msg = EmailMessage()
        msg['From'] = self.header_from or user
        if self.to:
            msg['To'] = ', '.join(self.to)
        if self.cc:
            msg['Cc'] = ', '.join(self.cc)  # Bcc is only in the envelope
        msg['Subject'] = 'e2e dataset'
        msg.set_content('Test')
        return msg.as_bytes(policy=SMTPUTF8)


@dataclass(frozen=True)
class Delivery:
    code: int
    reply: str
    accepted: list[str]

    @property
    def queue_id(self) -> str | None:
        match = re.search(r'queued as ([0-9A-Za-z]+)', self.reply)
        return match.group(1) if match else None


def deliver(user: str, mail: Mail) -> Delivery:
    with smtplib.SMTP('127.0.0.1', int(os.environ['E2E_SMTP_PORT']), timeout=30) as smtp:
        smtp.login(user, PASSWORD)
        if mail.utf8:
            smtp.command_encoding = 'utf-8'
        smtp.mail(user if mail.envelope_from is None else mail.envelope_from, ['SMTPUTF8'] if mail.utf8 else [])
        accepted = [rcpt for rcpt in mail.rcpts() if smtp.rcpt(rcpt)[0] == 250]
        try:
            code, reply = smtp.data(mail.message(user))
        except smtplib.SMTPDataError as e:
            code, reply = e.smtp_code, e.smtp_error
        return Delivery(code, reply.decode(), accepted)


def stored_messages(db: Any, user: str, expected: int = 1) -> list[dict[str, Any]]:
    """The sender's `messages` rows: Postfix gets its answer as soon as the message is counted, the row follows."""
    for _ in range(50):
        with db.cursor() as cursor:
            cursor.execute('SELECT * FROM `messages` WHERE `sender` = %s ORDER BY `id`', (user,))
            rows: list[dict[str, Any]] = cursor.fetchall()
        if len(rows) >= expected:
            return rows
        time.sleep(0.1)
    return rows


def log_line(queue_id: str) -> list[str]:
    """The daemon's log line for a queue ID (4th field, as list-recipients-by-sender.sh reads it), split in fields."""
    for _ in range(50):
        logs = subprocess.run(  # noqa: S603
            ['docker', 'compose', 'logs', '--no-color', '--no-log-prefix', 'policyd'],  # noqa: S607
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        for line in logs.splitlines():
            fields = line.split()
            if len(fields) > 4 and fields[3] == f'{queue_id}:' and fields[4].startswith('client='):
                return fields
        time.sleep(0.1)
    raise AssertionError(f'no log line for {queue_id}')


A, B, C, D, E, F = (f'{name}@example.org' for name in 'abcdef')


@pytest.mark.parametrize(
    ('mail', 'counted', 'to_addr'),
    [
        pytest.param(Mail(to=(A,)), 1, A, id='to'),
        pytest.param(Mail(to=(A, B, C)), 3, None, id='to-3'),
        pytest.param(Mail(to=(A,), cc=(B, C)), 3, None, id='to-cc'),
        pytest.param(Mail(to=(A,), cc=(B,), bcc=(C, D)), 4, None, id='to-cc-bcc'),
        pytest.param(Mail(bcc=(A, B)), 2, None, id='bcc-only'),
        pytest.param(Mail(to=(A,), cc=(A,)), 2, None, id='duplicate-recipient'),
        pytest.param(Mail(to=(A, 'rejected@localhost')), 1, A, id='recipient-rejected-by-postfix'),
        pytest.param(Mail(to=(A,), envelope_from=''), 1, A, id='null-sender'),
        pytest.param(Mail(to=(A,), header_from='Someone Else <other@example.org>'), 1, A, id='header-from-differs'),
        pytest.param(Mail(to=('jörg@exämple.org',), utf8=True), 1, 'jörg@exämple.org', id='smtputf8'),
        pytest.param(Mail(to=(A, B, C), cc=(D,), bcc=(E,)), QUOTA, None, id='exactly-the-quota'),
    ],
)
def test_accepted_mail_is_counted_stored_and_logged(
    mail: Mail, counted: int, to_addr: str | None, fresh: Callable[[str], str], db: Any
) -> None:
    user = fresh('test01@example.com')
    delivery = deliver(user, mail)
    assert delivery.code == 250, delivery.reply
    assert len(delivery.accepted) == counted
    assert counters(db, user) == (1, counted)

    (row,) = stored_messages(db, user)
    assert row['msgid'] == delivery.queue_id
    assert row['rcpt_count'] == counted
    assert row['blocked'] == 0
    assert row['to_addr'] == to_addr  # Postfix only sends the recipient for a single one
    assert row['from_addr'] == ((user if mail.envelope_from is None else mail.envelope_from) or None)  # envelope

    fields = log_line(delivery.queue_id or '')
    assert f'sasl_username={user},' in fields
    assert 'sasl_method=PLAIN,' in fields  # as smtplib picks it from PLAIN LOGIN
    assert f'recipient_count={counted},' in fields
    assert f'curr_count={counted}/{QUOTA},' in fields
    assert fields[-1] == 'status=ACCEPTED'


def test_one_mail_over_the_quota_is_blocked_counted_and_notified(fresh: Callable[[str], str], db: Any) -> None:
    """More recipients than the quota in a single mail: deferred, still counted, the webhook fires."""
    user = fresh('test02@example.com')
    delivery = deliver(user, Mail(to=(A, B, C), cc=(D, E), bcc=(F,)))
    assert delivery.code == 450
    assert 'Rate limit reached' in delivery.reply
    assert counters(db, user) == (1, 6)
    (row,) = stored_messages(db, user)
    assert (row['rcpt_count'], row['blocked']) == (6, 1)
    fields = log_line(row['msgid'])
    assert f'curr_count=6/{QUOTA},' in fields
    assert fields[-2:] == ['status=BLOCKED', '(QUOTA_LIMIT_REACHED)']
    calls = webhook_calls(1)
    assert [(c['json']['sender'], c['json']['rcpt_count'], c['json']['used']) for c in calls] == [(user, 6, 6)]


def test_several_mails_in_one_session_are_each_counted(fresh: Callable[[str], str], db: Any) -> None:
    """One SMTP connection, three transactions (a client reusing its session): three counted messages."""
    user = fresh('test03@example.com')
    with smtplib.SMTP('127.0.0.1', int(os.environ['E2E_SMTP_PORT']), timeout=30) as smtp:
        smtp.login(user, PASSWORD)
        for rcpts in ([A], [A, B], [C]):
            smtp.sendmail(user, rcpts, b'Subject: e2e session\r\n\r\nTest\r\n')
    assert counters(db, user) == (3, 4)
    assert len({row['msgid'] for row in stored_messages(db, user, 3)}) == 3


def compose(*args: str) -> None:
    subprocess.run(['docker', 'compose', *args], cwd=ROOT, capture_output=True, check=True)  # noqa: S603, S607


def test_database_down_fails_open_and_counting_resumes(fresh: Callable[[str], str]) -> None:
    """Last in this file: it stops the database. Without it Postfix accepts the mail (FAIL_ACTION DUNNO) and the
    daemon logs an ERROR with the queue ID; once the database is back, counting resumes."""
    user = fresh('test03@example.com')
    compose('stop', 'db')
    try:
        delivery = deliver(user, Mail(to=(A,)))
    finally:
        compose('up', '--detach', '--wait', 'db')
    assert delivery.code == 250, delivery.reply
    logs = subprocess.run(  # noqa: S603
        ['docker', 'compose', 'logs', '--no-color', '--no-log-prefix', 'policyd'],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert any(f' ERROR {delivery.queue_id}: ' in line and 'answering DUNNO' in line for line in logs.splitlines())

    delivery = deliver(user, Mail(to=(A, B)))
    assert delivery.code == 250
    url = urlsplit(os.environ['E2E_DATABASE_URL'])
    conn = pymysql.connect(
        host=url.hostname, port=url.port or 3306, user=url.username, password=url.password or '',
        database=url.path.lstrip('/'), autocommit=True, cursorclass=pymysql.cursors.DictCursor,
    )  # fmt: skip
    try:
        assert counters(conn, user) == (1, 2)  # only the mail after the outage
    finally:
        conn.close()
