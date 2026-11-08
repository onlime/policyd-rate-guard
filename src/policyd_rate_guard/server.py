"""asyncio policy server.

Connection I/O runs in the event loop, so idle persistent connections (Postfix keeps one per smtpd process for up
to ``smtpd_policy_service_max_idle``) cost nothing. DB work runs in a bounded thread pool sized to the DB
connection pool, a webhook in its own thread after the reply has been sent.
"""

import asyncio
import contextlib
import logging
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import Settings
from .log import queue_id_context
from .protocol import PolicyRequest, format_response, parse_request, sanitize
from .service import INVALID_ACTION, Handover, Outcome, PolicyService
from .systemd import notify
from .webhook import Webhook, WebhookPayload

BACKLOG = 256
IDLE_TIMEOUT = 330.0  # seconds, longer than Postfix's smtpd_policy_service_max_idle (300s)
MAX_REQUEST_SIZE = 65536  # bytes, far more than Postfix ever sends
SHUTDOWN_GRACE = 10.0
# Seconds, below Postfix's policy timeout (timeout=10s): an undecided request gets FAIL_ACTION before Postfix gives
# up and retries, and one still waiting for a worker is dropped, so a message is never counted twice
DECIDE_TIMEOUT = 8.0
# Seconds a shutdown waits for webhook calls in flight: a restart must not keep Postfix waiting (requests queue in
# the socket meanwhile, and one that Postfix gives up on would be counted again on its retry)
WEBHOOK_SHUTDOWN_GRACE = 2.0


def bind_listen_socket(settings: Settings) -> socket.socket:
    """Bind ``SOCKET`` (host,port) ourselves, when not socket-activated."""
    host, port = settings.listen.host, settings.listen.port
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    return socket.create_server((host, port), family=family, backlog=BACKLOG)


class PolicyServer:
    def __init__(
        self, settings: Settings, service: PolicyService, webhook: Webhook | None, logger: logging.Logger
    ) -> None:
        self.settings = settings
        self.service = service
        self.webhook = webhook
        self.logger = logger
        self.db_executor = ThreadPoolExecutor(settings.db.pool_maxconnections, thread_name_prefix='policy-db')
        self._connections: dict[asyncio.Task[None], bool] = {}  # task -> busy
        self._servers: list[asyncio.Server] = []
        self._webhook_threads: set[threading.Thread] = set()
        self._stopping = False

    async def start(self, sockets: list[socket.socket]) -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(self._loop_exception)
        for sock in sockets:
            # Also for a unix socket from systemd (ListenStream=/path); systemd removes the file, not us
            server = await asyncio.start_server(self._on_connection, sock=sock, limit=MAX_REQUEST_SIZE, backlog=BACKLOG)
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
        try:
            await stop.wait()
        finally:
            notify('STOPPING=1')
            await self.shutdown()

    async def shutdown(self) -> None:
        self._stopping = True
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
        self.db_executor.shutdown(wait=False, cancel_futures=True)
        deadline = time.monotonic() + WEBHOOK_SHUTDOWN_GRACE
        while self._webhook_threads and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        for thread in list(self._webhook_threads):
            self.logger.error('Webhook call abandoned at shutdown (%s)', thread.name)
        self.logger.info('Stopped')

    def _loop_exception(self, loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        # e.g. accept() failing with EMFILE: asyncio pauses accepting and carries on
        exc = context.get('exception')
        self.logger.error('Event loop error: %s', context.get('message'), exc_info=exc)

    async def _on_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is None:  # pragma: no cover
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
        # connection unless there was an error"), so loop until the client closes or goes idle. On shutdown, close
        # after the reply: a request cut off later would be counted without an answer, and counted again on retry.
        while not self._stopping:
            try:
                async with asyncio.timeout(IDLE_TIMEOUT):
                    data = await reader.readuntil(b'\n\n')
            except asyncio.IncompleteReadError as e:
                if e.partial.strip():
                    self.logger.warning('Connection closed in the middle of a request (%d bytes)', len(e.partial))
                return
            except asyncio.LimitOverrunError:
                # Far larger than anything Postfix sends: never let it pass as DUNNO
                self.logger.warning('Request exceeds %d bytes, answering and closing', MAX_REQUEST_SIZE)
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
            outcome = await self._decide_in_worker(request)
        return outcome

    async def _decide_in_worker(self, request: PolicyRequest) -> Outcome:
        """The decision, as soon as the message is counted (storing and logging it go on in the worker)."""
        loop = asyncio.get_running_loop()
        decided: asyncio.Future[Outcome] = loop.create_future()

        def on_decision(outcome: Outcome) -> None:  # in the worker
            with contextlib.suppress(RuntimeError):  # the loop is closed: nobody waits any more
                loop.call_soon_threadsafe(_set_result, decided, outcome)

        handover = Handover(on_decision)
        work = loop.run_in_executor(self.db_executor, self._decide, request, handover)
        work.add_done_callback(_retrieve)
        done, _ = await asyncio.wait({decided, work}, timeout=DECIDE_TIMEOUT, return_when=asyncio.FIRST_COMPLETED)
        if decided in done:
            return decided.result()
        if work in done:
            return work.result()  # e.g. FAIL_ACTION after a database error
        work.cancel()  # drops the request if it's still waiting for a worker
        outcome = handover.give_up()  # counted just now: still the decision
        if outcome is None:
            with queue_id_context(request.queue_id):
                self.logger.error(
                    'No decision within %.0f s (database slow or workers busy), answering %s',
                    DECIDE_TIMEOUT,
                    self.settings.fail_action,
                )
            outcome = Outcome(self.settings.fail_action)
        return outcome

    def _decide(self, request: PolicyRequest, handover: Handover) -> Outcome:
        """Worker thread."""
        outcome = self.service.decide(request, handover)
        if handover.abandoned and outcome.notify is not None:
            self._notify(outcome.notify)  # answered without this decision: nobody else will
        return outcome

    def _notify(self, payload: WebhookPayload) -> None:
        # At most once per sender and period. A daemon thread: a shutdown waits WEBHOOK_SHUTDOWN_GRACE at most.
        if self.webhook is not None:
            name = f'webhook for {sanitize(payload.msgid, 64)}'
            thread = threading.Thread(target=self._call_webhook, args=(payload,), name=name, daemon=True)
            self._webhook_threads.add(thread)
            thread.start()

    def _call_webhook(self, payload: WebhookPayload) -> None:
        try:
            if self.webhook is not None:
                with queue_id_context(payload.msgid):
                    self.webhook.call(payload)
        finally:
            self._webhook_threads.discard(threading.current_thread())


def _set_result(future: asyncio.Future[Outcome], outcome: Outcome) -> None:
    if not future.done():
        future.set_result(outcome)


def _retrieve(future: asyncio.Future[Outcome]) -> None:
    """A worker's result nobody waits for any more: no "exception was never retrieved" warning."""
    if not future.cancelled():
        future.exception()


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
