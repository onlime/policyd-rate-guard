import asyncio
import logging
import socket
import stat
import tempfile
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from policyd_rate_guard.config import Settings, TcpAddress, UnixAddress
from policyd_rate_guard.protocol import PolicyRequest
from policyd_rate_guard.server import PolicyServer, bind_listen_socket
from policyd_rate_guard.service import INVALID_ACTION, Outcome
from policyd_rate_guard.webhook import WebhookPayload

from .helpers import postfix_request

PAYLOAD = WebhookPayload('Q', 'u@example.com', None, None, 1, None, None, '2026-11-08 00:00:00', 1, 1, 2)


@dataclass
class FakeService:
    """Answers DUNNO without sasl_username (pre-check), else OK (or ``outcome``) after ``delay``."""

    outcome: Outcome = field(default_factory=lambda: Outcome('OK'))
    delay: float = 0.0
    decided: list[PolicyRequest] = field(default_factory=list)

    def precheck(self, request: PolicyRequest) -> Outcome | None:
        return None if request.sasl_username else Outcome('DUNNO')

    def decide(self, request: PolicyRequest) -> Outcome:
        if self.delay:
            threading.Event().wait(self.delay)
        self.decided.append(request)
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
        server = PolicyServer(settings, service, webhook, logger)  # type: ignore[arg-type]
        sock = bind_listen_socket(settings)
        await server.start([sock])
        servers.append(server)
        return Running(server, service, sock.getsockname()[1])

    yield start
    for server in servers:
        server.db_executor.shutdown(wait=False)
        server.webhook_executor.shutdown(wait=False)


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
    """F1: padded client-controlled values before sasl_username."""
    reader, writer = await running.connect()
    data = postfix_request('victim@example.com', sender='x' * 1900 + '@example.com', helo_name='h' * 255)
    assert await ask(reader, writer, data) == b'action=OK\n\n'
    assert running.service.decided[-1].sasl_username == 'victim@example.com'
    writer.close()


async def test_oversized_request_is_deferred_and_closed(server_factory: Callable[..., Any]) -> None:
    run = await server_factory(max_request_size=4096)
    reader, writer = await run.connect()
    writer.write(b'request=smtpd_access_policy\nsender=' + b'x' * 10000 + b'\n\n')
    await writer.drain()
    assert await asyncio.wait_for(reader.read(), 5) == f'action={INVALID_ACTION}\n\n'.encode()
    writer.close()
    await run.server.shutdown()


async def test_idle_connection_is_closed(server_factory: Callable[..., Any]) -> None:
    run = await server_factory(idle_timeout=0.2)
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


async def test_connection_limit(server_factory: Callable[..., Any], caplog: pytest.LogCaptureFixture) -> None:
    run = await server_factory(max_connections=2)
    first = await run.connect()
    second = await run.connect()
    assert await ask(first[0], first[1], postfix_request('u@example.com')) == b'action=OK\n\n'
    assert await ask(second[0], second[1], postfix_request('u@example.com')) == b'action=OK\n\n'
    reader, writer = await run.connect()
    assert await asyncio.wait_for(reader.read(), 5) == b''
    assert 'Too many connections (2), rejected 1 so far' in caplog.text
    for _, w in (first, second, (reader, writer)):
        w.close()
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
    await shutdown
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
    monkeypatch.setenv('WATCHDOG_USEC', '200000')
    settings = make_settings(listen=TcpAddress('127.0.0.1', 0))
    server = PolicyServer(settings, FakeService(), None, logger)  # type: ignore[arg-type]
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
    assert messages[0].startswith(b'READY=1')
    assert b'WATCHDOG=1' in messages
    assert messages[-1] == b'STOPPING=1'


def test_bind_unix_socket(make_settings: Callable[..., Settings]) -> None:
    directory = Path(tempfile.mkdtemp(prefix='prg-', dir='/tmp'))
    path = directory / 'policyd.sock'
    settings = make_settings(listen=UnixAddress(path))
    first = bind_listen_socket(settings)
    assert stat.S_IMODE(path.stat().st_mode) == 0o660
    first.close()  # leaves a stale socket file behind
    second = bind_listen_socket(settings)  # replaces the stale socket
    assert stat.S_ISSOCK(path.stat().st_mode)
    second.close()
    path.unlink()
    path.write_text('not a socket')
    with pytest.raises(FileExistsError):
        bind_listen_socket(settings)
    path.unlink()
    directory.rmdir()


async def test_unix_socket_server(make_settings: Callable[..., Settings], logger: logging.Logger) -> None:
    directory = Path(tempfile.mkdtemp(prefix='prg-', dir='/tmp'))
    path = directory / 'policyd.sock'
    settings = make_settings(listen=UnixAddress(path))
    server = PolicyServer(settings, FakeService(), None, logger)  # type: ignore[arg-type]
    await server.start([bind_listen_socket(settings)])
    reader, writer = await asyncio.open_unix_connection(str(path))
    assert await ask(reader, writer, postfix_request('u@example.com')) == b'action=OK\n\n'
    writer.close()
    await server.shutdown()
    cleanup_dir(directory)


def cleanup_dir(directory: Path) -> None:
    for entry in directory.iterdir():
        entry.unlink()
    directory.rmdir()


def test_bind_ipv6(make_settings: Callable[..., Settings]) -> None:
    if not socket.has_ipv6:  # pragma: no cover
        pytest.skip('no IPv6')
    sock = bind_listen_socket(make_settings(listen=TcpAddress('::1', 0)))
    assert sock.family == socket.AF_INET6
    sock.close()
