import logging
import logging.handlers
import re
import socket
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from policyd_rate_guard.config import Settings
from policyd_rate_guard.log import LOGGER_NAME, configure_logging, queue_id_context
from policyd_rate_guard.protocol import parse_request
from policyd_rate_guard.ratelimit import Decision, MessageRecord
from policyd_rate_guard.service import PolicyService

from .helpers import postfix_request


@pytest.fixture
def restore_logger() -> Iterator[None]:
    log = logging.getLogger(LOGGER_NAME)
    handlers, level, propagate = list(log.handlers), log.level, log.propagate
    yield
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()
    for handler in handlers:
        log.addHandler(handler)
    log.setLevel(level)
    log.propagate = propagate


@pytest.mark.usefixtures('restore_logger')
def test_log_line_format_is_unchanged(tmp_path: Path, make_settings: Callable[..., Settings]) -> None:
    """Golden test: infra's list-recipients-by-sender.sh greps ' sasl_username=X,' and takes awk $4 as queue ID."""
    log_file = tmp_path / 'policyd.log'
    settings = make_settings(log_file=log_file, log_level='INFO')
    logger = configure_logging(settings)
    service = PolicyService(settings, db=None, logger=logger)
    request = parse_request(postfix_request('user@example.com', recipient_count=2, queue_id='4XyZ1abc2'))
    record = MessageRecord('4XyZ1abc2', 'user@example.com', 2, 'from@example.com', 'rcpt@example.org',
                           '192.0.2.10', 'client.example.net', None)  # fmt: skip
    decision = Decision(1, 1000, 1000, 3, 7, blocked=False, was_blocked=False)
    with queue_id_context('4XyZ1abc2'):
        service._log_decision(request, record, decision)

    line = log_file.read_text().splitlines()[-1]
    fields = line.split()
    assert fields[2] == 'INFO'
    assert fields[3] == '4XyZ1abc2:'
    assert line.split(' ', 4)[4] == (
        'client=client.example.net[192.0.2.10], helo=client.example.net, sasl_method=PLAIN, '
        'sasl_username=user@example.com, from=from@example.com, to=rcpt@example.org, recipient_count=2, '
        'curr_count=7/1000, status=ACCEPTED'
    )
    assert ' sasl_username=user@example.com,' in line


@pytest.mark.usefixtures('restore_logger')
def test_blocked_and_crossing_lines(tmp_path: Path, make_settings: Callable[..., Settings]) -> None:
    log_file = tmp_path / 'policyd.log'
    settings = make_settings(log_file=log_file)
    service = PolicyService(settings, db=None, logger=configure_logging(settings))
    request = parse_request(postfix_request('user@example.com'))
    record = MessageRecord('Q1', 'user@example.com', 1, None, None, None, None, None)
    service._log_decision(request, record, Decision(1, 5, 5, 6, 6, blocked=True, was_blocked=False))
    service._log_decision(request, record, Decision(1, 5, 5, 7, 7, blocked=True, was_blocked=True))
    lines = log_file.read_text().splitlines()
    assert 'WARNING Message BLOCKED: sender=user@example.com' in lines[0]
    assert lines[1].endswith('status=BLOCKED (QUOTA_LIMIT_REACHED)')
    assert lines[3].endswith('status=BLOCKED')


@pytest.mark.usefixtures('restore_logger')
def test_queue_ids_are_correct_under_concurrency(tmp_path: Path, make_settings: Callable[..., Settings]) -> None:
    """F8: 0.x stored the queue ID on the shared logger, so concurrent requests logged each other's IDs."""
    log_file = tmp_path / 'policyd.log'
    logger = configure_logging(make_settings(log_file=log_file))
    barrier = threading.Barrier(20)

    def worker(i: int) -> None:
        with queue_id_context(f'QID{i:02d}'):
            barrier.wait()
            for _ in range(20):
                logger.info('request %02d', i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = log_file.read_text().splitlines()
    assert len(lines) == 400
    for line in lines:
        fields = line.split()
        assert fields[3] == f'QID{fields[5]}:'


@pytest.mark.usefixtures('restore_logger')
def test_third_party_logs_stay_out_and_no_root_handlers(tmp_path: Path, make_settings: Callable[..., Settings]) -> None:
    log_file = tmp_path / 'policyd.log'
    root_handlers = list(logging.getLogger().handlers)
    configure_logging(make_settings(log_file=log_file))
    logging.getLogger('urllib3.connectionpool').warning('third party')
    assert logging.getLogger().handlers == root_handlers
    assert 'third party' not in log_file.read_text()


@pytest.mark.usefixtures('restore_logger')
def test_reopens_log_file_after_rotation(tmp_path: Path, make_settings: Callable[..., Settings]) -> None:
    log_file = tmp_path / 'policyd.log'
    logger = configure_logging(make_settings(log_file=log_file))
    logger.info('before')
    log_file.rename(tmp_path / 'policyd.log.1')  # what logrotate does
    logger.info('after')
    assert 'after' in log_file.read_text()
    assert 'before' in (tmp_path / 'policyd.log.1').read_text()


@pytest.mark.usefixtures('restore_logger')
def test_console_and_default_handlers(make_settings: Callable[..., Settings]) -> None:
    assert [type(h) for h in configure_logging(make_settings(log_console=True)).handlers] == [logging.StreamHandler]
    # without any configured handler, log to stderr (journal under systemd)
    assert [type(h) for h in configure_logging(make_settings()).handlers] == [logging.StreamHandler]


@pytest.mark.usefixtures('restore_logger')
def test_syslog_line_matches_the_zabbix_item(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """infra's Zabbix item counts lines matching this pattern in mail.log: they mean mail was let through uncounted."""
    directory = Path(tempfile.mkdtemp(prefix='prg-', dir='/tmp'))  # short path for AF_UNIX
    path = directory / 'log.sock'
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(str(path))

    class TestSysLogHandler(logging.handlers.SysLogHandler):
        def __init__(self, address: str, facility: int) -> None:
            super().__init__(str(path), facility)  # instead of /dev/log

    monkeypatch.setattr(logging.handlers, 'SysLogHandler', TestSysLogHandler)
    try:
        logger = configure_logging(make_settings(syslog=True))
        with queue_id_context('QERR'):
            logger.error('Unhandled exception, answering DUNNO')
        message = receiver.recv(4096).decode()
    finally:
        receiver.close()
        path.unlink()
        directory.rmdir()
    assert re.search(r'policyd-rate-guard\[[0-9]+\]: (ERROR|CRITICAL)', message)
    # facility LOG_MAIL (2 * 8) + severity err (3), so the line ends up in mail.log
    assert re.fullmatch(r'<19>policyd-rate-guard\[\d+\]: ERROR QERR: Unhandled exception, answering DUNNO\x00', message)
