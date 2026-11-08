import asyncio
import logging
import socket
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from policyd_rate_guard import server as server_module
from policyd_rate_guard.config import DbSettings, Settings, TcpAddress, WebhookSettings
from policyd_rate_guard.log import ContextFilter
from policyd_rate_guard.protocol import PolicyRequest
from policyd_rate_guard.server import PolicyServer, bind_listen_socket
from policyd_rate_guard.service import INVALID_ACTION, Handover, Outcome
from policyd_rate_guard.webhook import Webhook, WebhookPayload

from .helpers import postfix_request

PAYLOAD = WebhookPayload('Q', 'u@example.com', None, None, 1, None, None, '2026-11-08 00:00:00', 1, 1, 2)


@dataclass
class FakeService:
    """Answers DUNNO without sasl_username (pre-check), else OK (or ``outcome``) after ``delay`` (counting), and
    ``store_delay`` (storing and logging, after the decision has been handed over)."""

    outcome: Outcome = field(default_factory=lambda: Outcome('OK'))
    delay: float = 0.0
    store_delay: float = 0.0
    decided: list[PolicyRequest] = field(default_factory=list)

    def precheck(self, request: PolicyRequest) -> Outcome | None:
        return None if request.sasl_username else Outcome('DUNNO')

    def decide(self, request: PolicyRequest, handover: Handover | None = None) -> Outcome:
        if self.delay:
            threading.Event().wait(self.delay)
        self.decided.append(request)
        if handover is not None:
            handover.hand_over(self.outcome)
        if self.store_delay:
            threading.Event().wait(self.store_delay)
        return self.outcome


class FakeWebhook:
    def __init__(self) -> None:
        self.calls: list[WebhookPayload] = []
        self.release = threading.Event()

    def call(self, payload: WebhookPayload) -> bool:
        self.release.wait(5)
        self.calls.append(payload)
        return True


@dataclass
class Running:
    server: PolicyServer
    service: FakeService
    port: int

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection('127.0.0.1', self.port)


@pytest.fixture
def server_factory(make_settings: Callable[..., Settings], logger: logging.Logger) -> Iterator[Callable[..., Any]]:
    servers: list[PolicyServer] = []

    async def start(service: FakeService | None = None, webhook: Any = None, **overrides: Any) -> Running:
        settings = make_settings(listen=TcpAddress('127.0.0.1', 0), **overrides)
        service = service or FakeService()
        server = PolicyServer(settings, service, webhook, logger)
        sock = bind_listen_socket(settings)
        await server.start([sock])
        servers.append(server)
        return Running(server, service, sock.getsockname()[1])

    yield start
    for server in servers:
        server.db_executor.shutdown(wait=False)


@pytest.fixture
async def running(server_factory: Callable[..., Any]) -> AsyncIterator[Running]:
    run = await server_factory()
    yield run
    await run.server.shutdown()


async def ask(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, data: bytes) -> bytes:
    writer.write(data)
    await writer.drain()
    return await asyncio.wait_for(reader.readuntil(b'\n\n'), 5)


async def test_persistent_connection_serves_many_requests(running: Running) -> None:
    reader, writer = await running.connect()
    for i in range(5):
        assert await ask(reader, writer, postfix_request('u@example.com', queue_id=f'Q{i}')) == b'action=OK\n\n'
    assert await ask(reader, writer, postfix_request(None)) == b'action=DUNNO\n\n'
    writer.close()
    assert [r.queue_id for r in running.service.decided] == ['Q0', 'Q1', 'Q2', 'Q3', 'Q4']


async def test_fragmented_and_pipelined_requests(running: Running) -> None:
    reader, writer = await running.connect()
    data = postfix_request('u@example.com', queue_id='FRAG')
    for i in range(len(data)):
        writer.write(data[i : i + 1])
        await writer.drain()
    assert await asyncio.wait_for(reader.readuntil(b'\n\n'), 5) == b'action=OK\n\n'

    writer.write(postfix_request('u@example.com', queue_id='P1') + postfix_request('u@example.com', queue_id='P2'))
    assert await asyncio.wait_for(reader.readuntil(b'\n\n'), 5) == b'action=OK\n\n'
    assert await asyncio.wait_for(reader.readuntil(b'\n\n'), 5) == b'action=OK\n\n'
    writer.close()


async def test_long_request_is_counted_not_truncated(running: Running) -> None:
    """Padded client-controlled values before sasl_username (0.x read only 2048 bytes and lost it)."""
    reader, writer = await running.connect()
    data = postfix_request('victim@example.com', sender='x' * 1900 + '@example.com', helo_name='h' * 255)
    assert await ask(reader, writer, data) == b'action=OK\n\n'
    assert running.service.decided[-1].sasl_username == 'victim@example.com'
    writer.close()


async def test_oversized_request_is_deferred_and_closed(
    server_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module, 'MAX_REQUEST_SIZE', 4096)
    run = await server_factory()
    reader, writer = await run.connect()
    writer.write(b'request=smtpd_access_policy\nsender=' + b'x' * 10000 + b'\n\n')
    await writer.drain()
    assert await asyncio.wait_for(reader.read(), 5) == f'action={INVALID_ACTION}\n\n'.encode()
    writer.close()
    await run.server.shutdown()


async def test_idle_connection_is_closed(server_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, 'IDLE_TIMEOUT', 0.2)
    run = await server_factory()
    reader, writer = await run.connect()
    assert await asyncio.wait_for(reader.read(), 5) == b''
    writer.close()
    await run.server.shutdown()


async def test_incomplete_request_is_logged(running: Running, caplog: pytest.LogCaptureFixture) -> None:
    _, writer = await running.connect()
    writer.write(b'request=smtpd_access_policy\nsasl_username=u@example.com\n')
    await writer.drain()
    writer.close()
    await writer.wait_closed()
    for _ in range(50):
        if 'Connection closed in the middle of a request' in caplog.text:
            break
        await asyncio.sleep(0.02)
    assert 'Connection closed in the middle of a request' in caplog.text
    assert running.service.decided == []


async def test_unexpected_error_closes_the_connection(
    server_factory: Callable[..., Any], caplog: pytest.LogCaptureFixture
) -> None:
    """A bug in the server itself: no answer, the connection is closed (Postfix then uses its default_action)."""

    class Broken(FakeService):
        def decide(self, request: PolicyRequest, handover: Handover | None = None) -> Outcome:
            raise RuntimeError('bug')

    run = await server_factory(Broken())
    reader, writer = await run.connect()
    writer.write(postfix_request('u@example.com'))
    await writer.drain()
    assert await asyncio.wait_for(reader.read(), 5) == b''
    assert 'Unhandled exception in connection handler' in caplog.text
    writer.close()
    await run.server.shutdown()


async def test_webhook_runs_after_the_reply(server_factory: Callable[..., Any]) -> None:
    """A slow webhook must not delay the answer to Postfix (0.x called it before replying, without timeout)."""
    webhook = FakeWebhook()
    run = await server_factory(FakeService(Outcome('DEFER_IF_PERMIT Rate limit reached', PAYLOAD)), webhook)
    reader, writer = await run.connect()
    assert (
        await ask(reader, writer, postfix_request('u@example.com')) == b'action=DEFER_IF_PERMIT Rate limit reached\n\n'
    )
    assert webhook.calls == []  # still blocked in the webhook
    webhook.release.set()
    for _ in range(100):
        if webhook.calls:
            break
        await asyncio.sleep(0.01)
    assert webhook.calls == [PAYLOAD]
    writer.close()
    await run.server.shutdown()


async def test_shutdown_lets_busy_requests_finish(server_factory: Callable[..., Any]) -> None:
    run = await server_factory(FakeService(delay=0.3))
    idle_reader, idle_writer = await run.connect()
    reader, writer = await run.connect()
    writer.write(postfix_request('u@example.com'))
    await writer.drain()
    await asyncio.sleep(0.1)  # request is now being decided
    shutdown = asyncio.create_task(run.server.shutdown())
    assert await asyncio.wait_for(reader.readuntil(b'\n\n'), 5) == b'action=OK\n\n'
    assert await asyncio.wait_for(reader.read(), 5) == b''  # closed after the reply, no further requests
    await asyncio.wait_for(shutdown, 2)  # not the full grace period
    assert await asyncio.wait_for(idle_reader.read(), 5) == b''
    for w in (writer, idle_writer):
        w.close()


async def test_run_notifies_systemd(
    server_factory: Callable[..., Any],
    make_settings: Callable[..., Settings],
    logger: logging.Logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = Path(tempfile.mkdtemp(prefix='prg-', dir='/tmp'))  # short path for AF_UNIX
    path = directory / 'notify.sock'
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(str(path))
    receiver.setblocking(False)
    monkeypatch.setenv('NOTIFY_SOCKET', str(path))
    settings = make_settings(listen=TcpAddress('127.0.0.1', 0))
    server = PolicyServer(settings, FakeService(), None, logger)
    stop = asyncio.Event()
    task = asyncio.create_task(server.run([bind_listen_socket(settings)], stop))
    await asyncio.sleep(0.25)
    stop.set()
    await asyncio.wait_for(task, 5)
    messages = []
    while True:
        try:
            messages.append(receiver.recv(256))
        except BlockingIOError:
            break
    receiver.close()
    path.unlink()
    directory.rmdir()
    assert messages == [b'READY=1\nSTATUS=Serving policy requests', b'STOPPING=1']


async def test_unix_socket_from_systemd(make_settings: Callable[..., Settings], logger: logging.Logger) -> None:
    """A unix socket set up by a socket unit (ListenStream=/path) is served like a TCP one, and left in place."""
    directory = Path(tempfile.mkdtemp(prefix='prg-', dir='/tmp'))  # short path for AF_UNIX
    path = directory / 'policyd.sock'
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.listen()
    server = PolicyServer(make_settings(), FakeService(), None, logger)
    await server.start([sock])
    reader, writer = await asyncio.open_unix_connection(str(path))
    assert await ask(reader, writer, postfix_request('u@example.com')) == b'action=OK\n\n'
    writer.close()
    await server.shutdown()
    assert path.is_socket()
    path.unlink()
    directory.rmdir()


def test_bind_ipv6(make_settings: Callable[..., Settings]) -> None:
    if not socket.has_ipv6:  # pragma: no cover
        pytest.skip('no IPv6')
    sock = bind_listen_socket(make_settings(listen=TcpAddress('::1', 0)))
    assert sock.family == socket.AF_INET6
    sock.close()


async def test_undecided_requests_get_fail_action_before_postfix_gives_up(
    server_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A slow database: FAIL_ACTION before Postfix's timeout (no retry, so no double count), and a request still
    waiting for a worker is dropped instead of being counted later."""
    monkeypatch.setattr(server_module, 'DECIDE_TIMEOUT', 0.2)
    run = await server_factory(FakeService(delay=0.6), db=DbSettings(pool_maxconnections=1))
    first, second = await run.connect(), await run.connect()
    first[1].write(postfix_request('u@example.com', queue_id='SLOW1'))
    second[1].write(postfix_request('u@example.com', queue_id='SLOW2'))
    assert await asyncio.wait_for(first[0].readuntil(b'\n\n'), 5) == b'action=DUNNO\n\n'
    assert await asyncio.wait_for(second[0].readuntil(b'\n\n'), 5) == b'action=DUNNO\n\n'
    await asyncio.sleep(0.8)  # the first one finishes in its worker, the second never starts
    assert [r.queue_id for r in run.service.decided] == ['SLOW1']
    assert 'No decision within 0 s (database slow or workers busy), answering DUNNO' in caplog.text
    for _, writer in (first, second):
        writer.close()
    await run.server.shutdown()


async def test_the_decision_is_answered_while_still_storing(
    server_factory: Callable[..., Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Counted: Postfix gets the decision right away, not after the messages row (e.g. waiting for a lock) or the
    timeout, and the webhook fires."""
    webhook = FakeWebhook()
    webhook.release.set()
    blocked = Outcome('DEFER_IF_PERMIT Rate limit reached', PAYLOAD)
    run = await server_factory(FakeService(blocked, store_delay=1.0), webhook)
    reader, writer = await run.connect()
    started = time.monotonic()
    assert (
        await ask(reader, writer, postfix_request('u@example.com')) == b'action=DEFER_IF_PERMIT Rate limit reached\n\n'
    )
    assert time.monotonic() - started < 0.5
    assert 'No decision within' not in caplog.text
    for _ in range(100):
        if webhook.calls:
            break
        await asyncio.sleep(0.01)
    assert webhook.calls == [PAYLOAD]
    writer.close()
    await run.server.shutdown()


async def test_a_decision_made_too_late_still_notifies(
    server_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Postfix got FAIL_ACTION, but the worker counted it as the crossing request: the webhook fires from the worker,
    once (else the sender's period would pass without a notification)."""
    monkeypatch.setattr(server_module, 'DECIDE_TIMEOUT', 0.2)
    webhook = FakeWebhook()
    webhook.release.set()
    run = await server_factory(FakeService(Outcome('DEFER_IF_PERMIT Rate limit reached', PAYLOAD), delay=0.5), webhook)
    reader, writer = await run.connect()
    assert await ask(reader, writer, postfix_request('u@example.com')) == b'action=DUNNO\n\n'
    for _ in range(100):
        if webhook.calls:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)
    assert webhook.calls == [PAYLOAD]
    writer.close()
    await run.server.shutdown()


async def test_shutdown_waits_for_a_webhook_only_briefly(
    server_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A hanging webhook (e.g. DNS) must not hold a restart: requests queue in the socket meanwhile, and Postfix
    gives up on them after 10 s and retries (counted twice)."""
    monkeypatch.setattr(server_module, 'WEBHOOK_SHUTDOWN_GRACE', 0.3)
    webhook = FakeWebhook()  # never released
    run = await server_factory(FakeService(Outcome('DEFER_IF_PERMIT Rate limit reached', PAYLOAD)), webhook)
    reader, writer = await run.connect()
    await ask(reader, writer, postfix_request('u@example.com'))
    writer.close()
    started = time.monotonic()
    await run.server.shutdown()
    assert time.monotonic() - started < 2
    assert 'Webhook call abandoned at shutdown (webhook for Q)' in caplog.text
    webhook.release.set()


def test_webhook_thread_name_is_escaped(make_settings: Callable[..., Settings], logger: logging.Logger) -> None:
    """The name ends up in a log line (abandoned at shutdown); the queue ID comes from the request."""
    webhook = FakeWebhook()
    server = PolicyServer(make_settings(), FakeService(), webhook, logger)  # type: ignore[arg-type]
    server._notify(replace(PAYLOAD, msgid='Q\x1b[31m\r' + 'x' * 100))
    (thread,) = server._webhook_threads
    assert thread.name.startswith('webhook for Q\\x1b[31m\\x0d') and len(thread.name) < 90
    webhook.release.set()
    thread.join(5)


async def test_webhook_failure_is_logged_with_the_queue_id(
    server_factory: Callable[..., Any], logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.handler.addFilter(ContextFilter())
    secret = 'Wk9YZXliVlVtY2pQcFlFUm9KY1U1ZkFFaUpWTk1FU20='  # 32 bytes
    webhook = Webhook(WebhookSettings(enabled=True, url='https://x.invalid/{sender}', secret=secret), logger)
    webhook.session.post = MagicMock(side_effect=requests.ConnectionError('down'))  # type: ignore[method-assign]
    run = await server_factory(FakeService(Outcome('DEFER_IF_PERMIT Rate limit reached', PAYLOAD)), webhook)
    reader, writer = await run.connect()
    await ask(reader, writer, postfix_request('u@example.com'))
    for _ in range(100):
        records = [r for r in caplog.records if r.getMessage().startswith('Webhook call failed')]
        if records:
            break
        await asyncio.sleep(0.01)
    assert records[0].levelname == 'ERROR'
    assert records[0].queue_id_prefix == 'Q: '
    writer.close()
    await run.server.shutdown()
