"""asyncio policy server.

Connection I/O runs in the event loop, so idle persistent connections (Postfix keeps one per smtpd process for up
to ``smtpd_policy_service_max_idle``) cost nothing. DB work runs in a bounded thread pool sized to the DB
connection pool, webhooks in a separate small pool after the reply has been sent.
"""

import asyncio
import contextlib
import logging
import os
import signal
import socket
import stat
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import Settings, TcpAddress, UnixAddress
from .log import queue_id_context
from .protocol import format_response, parse_request
from .service import INVALID_ACTION, Outcome, PolicyService
from .systemd import notify, watchdog_interval
from .webhook import Webhook, WebhookPayload

SHUTDOWN_GRACE = 10.0


def bind_listen_socket(settings: Settings) -> socket.socket:
    """Bind ``SOCKET`` ourselves (when not socket-activated)."""
    address = settings.listen
    if isinstance(address, TcpAddress):
        family = socket.AF_INET6 if ':' in address.host else socket.AF_INET
        return socket.create_server((address.host, address.port), family=family, backlog=settings.socket_backlog)
    path = address.path
    with contextlib.suppress(FileNotFoundError):
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise FileExistsError(f'{path} exists and is not a socket')
        path.unlink()  # stale socket of a previous run
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o117)  # 0660: owner and group (e.g. postfix) only
    try:
        sock.bind(str(path))
    finally:
        os.umask(old_umask)
    sock.listen(settings.socket_backlog)
    return sock


class PolicyServer:
    def __init__(
        self, settings: Settings, service: PolicyService, webhook: Webhook | None, logger: logging.Logger
    ) -> None:
        self.settings = settings
        self.service = service
        self.webhook = webhook
        self.logger = logger
        self.db_executor = ThreadPoolExecutor(settings.db.pool_maxconnections, thread_name_prefix='policy-db')
        self.webhook_executor = ThreadPoolExecutor(2, thread_name_prefix='policy-webhook')
        self._connections: dict[asyncio.Task[None], bool] = {}  # task -> busy
        self._background: set[asyncio.Future[Any]] = set()
        self._servers: list[asyncio.Server] = []
        self._rejected_connections = 0

    async def start(self, sockets: list[socket.socket]) -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(self._loop_exception)
        for sock in sockets:
            if sock.family == socket.AF_UNIX:
                # cleanup_socket=False: a systemd-provided socket may live in a directory we can't even stat
                server = await asyncio.start_unix_server(
                    self._on_connection,
                    sock=sock,
                    limit=self.settings.max_request_size,
                    backlog=self.settings.socket_backlog,
                    cleanup_socket=False,
                )
            else:
                server = await asyncio.start_server(
                    self._on_connection,
                    sock=sock,
                    limit=self.settings.max_request_size,
                    backlog=self.settings.socket_backlog,
                )
            self._servers.append(server)
            self.logger.info('Listening on %s', _describe(sock))

    async def run(self, sockets: list[socket.socket], stop: asyncio.Event | None = None) -> None:
        """Serve until ``stop`` is set (or SIGTERM/SIGINT), then shut down gracefully."""
        stop = stop or asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop.set)
        await self.start(sockets)
        notify('READY=1\nSTATUS=Serving policy requests')
        watchdog = asyncio.create_task(self._watchdog()) if watchdog_interval() else None
        try:
            await stop.wait()
        finally:
            notify('STOPPING=1')
            if watchdog:
                watchdog.cancel()
            await self.shutdown()

    async def shutdown(self) -> None:
        for server in self._servers:
            server.close()
        # Idle connections can go right away, busy ones may finish their request
        for task, busy in list(self._connections.items()):
            if not busy:
                task.cancel()
        if self._connections:
            _, pending = await asyncio.wait(list(self._connections), timeout=SHUTDOWN_GRACE)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=1)
        for server in self._servers:
            with contextlib.suppress(Exception):
                await server.wait_closed()
        if self._background:
            await asyncio.wait(list(self._background), timeout=SHUTDOWN_GRACE)
        self.db_executor.shutdown(wait=False, cancel_futures=True)
        self.webhook_executor.shutdown(wait=False, cancel_futures=True)
        self.logger.info('Stopped')

    async def _watchdog(self) -> None:
        interval = watchdog_interval() or 10.0
        while True:
            notify('WATCHDOG=1')
            await asyncio.sleep(interval)

    def _loop_exception(self, loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        # e.g. accept() failing with EMFILE: asyncio pauses accepting and carries on
        exc = context.get('exception')
        self.logger.error('Event loop error: %s', context.get('message'), exc_info=exc)

    async def _on_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is None:  # pragma: no cover
            return
        if len(self._connections) >= self.settings.max_connections:
            self._rejected_connections += 1
            if self._rejected_connections % 100 == 1:
                self.logger.warning(
                    'Too many connections (%d), rejected %d so far',
                    len(self._connections),
                    self._rejected_connections,
                )
            await _close(writer)
            return
        self._connections[task] = False
        try:
            await self._serve_connection(task, reader, writer)
        except asyncio.CancelledError:
            pass
        except (ConnectionError, TimeoutError) as e:
            self.logger.debug('Connection closed: %s', type(e).__name__)
        except Exception:
            self.logger.exception('Unhandled exception in connection handler')
        finally:
            self._connections.pop(task, None)
            await _close(writer)

    async def _serve_connection(
        self, task: asyncio.Task[None], reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # Postfix keeps the connection and sends further requests on it ("the server must not close the
        # connection unless there was an error"), so loop until the client closes or goes idle.
        while True:
            try:
                async with asyncio.timeout(self.settings.idle_timeout):
                    data = await reader.readuntil(b'\n\n')
            except asyncio.IncompleteReadError as e:
                if e.partial.strip():
                    self.logger.warning('Connection closed in the middle of a request (%d bytes)', len(e.partial))
                return
            except asyncio.LimitOverrunError:
                # Far larger than anything Postfix sends: never let it pass as DUNNO
                self.logger.warning('Request exceeds %d bytes, answering and closing', self.settings.max_request_size)
                writer.write(format_response(INVALID_ACTION))
                await writer.drain()
                return
            except TimeoutError:
                self.logger.debug('Closing idle connection')
                return

            self._connections[task] = True
            try:
                outcome = await self._process(data)
                writer.write(format_response(outcome.action))
                await writer.drain()
            finally:
                self._connections[task] = False
            if outcome.notify is not None:
                self._notify(outcome.notify)

    async def _process(self, data: bytes) -> Outcome:
        request = parse_request(data)
        with queue_id_context(request.queue_id):
            self.logger.debug('Received request: %r', data[:4096])
        outcome = self.service.precheck(request)
        if outcome is None:
            loop = asyncio.get_running_loop()
            outcome = await loop.run_in_executor(self.db_executor, self.service.decide, request)
        return outcome

    def _notify(self, payload: WebhookPayload) -> None:
        if self.webhook is None:
            return
        call: Callable[[WebhookPayload], bool] = self.webhook.call
        future = asyncio.get_running_loop().run_in_executor(self.webhook_executor, call, payload)
        self._background.add(future)
        future.add_done_callback(self._background.discard)


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()


def _describe(sock: socket.socket) -> str:
    name = sock.getsockname()
    if sock.family == socket.AF_UNIX:
        return f'unix:{name}'
    host, port = name[0], name[1]
    return f'inet:[{host}]:{port}' if ':' in host else f'inet:{host}:{port}'


__all__ = ['PolicyServer', 'TcpAddress', 'UnixAddress', 'bind_listen_socket']
