import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from policyd_rate_guard.config import Settings, WebhookSettings
from policyd_rate_guard.log import ContextFilter
from policyd_rate_guard.protocol import parse_request
from policyd_rate_guard.service import INVALID_ACTION, Handover, Outcome, PolicyService

from .helpers import SECRET, postfix_request


def service(settings: Settings, db: Any = None) -> PolicyService:
    return PolicyService(settings, db, logging.getLogger('policyd-rate-guard'))


@pytest.mark.parametrize(
    ('data', 'expected'),
    [
        (postfix_request(None), Outcome('DUNNO')),  # incoming mail on port 25
        (postfix_request('u@example.com', request='other'), Outcome('DUNNO')),
        (postfix_request('u@example.com', protocol_state='RCPT'), Outcome('DUNNO')),
        (postfix_request('u@example.com', recipient_count=-1000), Outcome(INVALID_ACTION)),
        (postfix_request('u@example.com', recipient_count='abc'), Outcome(INVALID_ACTION)),
        (postfix_request('u@example.com', recipient_count=10**9), Outcome(INVALID_ACTION)),
        (postfix_request('x' * 256 + '@example.com'), Outcome(INVALID_ACTION)),
        (postfix_request('u@example.com'), None),  # needs the DB
        (postfix_request('u@example.com', protocol_state='END-OF-MESSAGE'), None),
        (postfix_request('u@example.com', protocol_state='BDAT'), None),
        # not a state Postfix sends: never DUNNO
        (postfix_request('u@example.com', protocol_state='nonsense'), Outcome(INVALID_ACTION)),
        (postfix_request('u@example.com', protocol_state=''), Outcome(INVALID_ACTION)),
        # more digits than int() accepts: invalid, not an internal error
        (postfix_request('u@example.com', recipient_count='9' * 5000), Outcome(INVALID_ACTION)),
    ],
)
def test_precheck(data: bytes, expected: Outcome | None, make_settings: Callable[..., Settings]) -> None:
    assert service(make_settings()).precheck(parse_request(data)) == expected


def test_wrong_protocol_state_is_warned_once(
    make_settings: Callable[..., Settings], logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    svc = service(make_settings())
    for _ in range(3):
        svc.precheck(parse_request(postfix_request('u@example.com', protocol_state='RCPT')))
    assert [r.levelname for r in caplog.records if 'Not counting' in r.getMessage()] == ['ERROR']


@pytest.mark.parametrize('fail_action', ['DUNNO', 'DEFER_IF_PERMIT'])
def test_db_failure_answers_fail_action(
    fail_action: str, make_settings: Callable[..., Settings], logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.handler.addFilter(ContextFilter())
    caplog.handler.setFormatter(logging.Formatter('%(queue_id_prefix)s%(message)s'))
    db = MagicMock()
    db.connection.side_effect = ConnectionError('MySQL server has gone away')
    svc = service(make_settings(fail_action=fail_action), db)
    assert svc.decide(parse_request(postfix_request('u@example.com', queue_id='QFAIL'))) == Outcome(fail_action)
    assert 'QFAIL: Unhandled exception, answering ' + fail_action in caplog.text


def test_precheck_failure_answers_fail_action(make_settings: Callable[..., Settings], logger: logging.Logger) -> None:
    svc = service(make_settings())
    request = MagicMock()
    request.queue_id = None
    type(request).request_type = property(lambda self: (_ for _ in ()).throw(RuntimeError('boom')))
    assert svc.precheck(request) == Outcome('DUNNO')


def test_store_failure_keeps_the_decision(
    make_settings: Callable[..., Settings],
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In 0.x an error after the decision (e.g. storing the message) turned a block into DUNNO."""
    from policyd_rate_guard import service as service_module
    from policyd_rate_guard.ratelimit import Decision

    @contextmanager
    def connection() -> Any:
        yield MagicMock()

    db = MagicMock()
    db.connection = connection
    blocked = Decision(1, 5, 5, 6, 6, blocked=True, was_blocked=False)
    monkeypatch.setattr(service_module, 'count_message', lambda *a: blocked)
    monkeypatch.setattr(service_module, 'store_message', MagicMock(side_effect=RuntimeError('Data too long')))
    settings = make_settings(
        webhook=WebhookSettings(enabled=True, url='https://x/{sender}', secret=SECRET),
        action_text_blocked='Slow down',
    )
    outcome = service(settings, db).decide(parse_request(postfix_request('u@example.com', recipient_count=6)))
    assert outcome.action == 'DEFER_IF_PERMIT Slow down'
    assert outcome.notify is not None
    assert outcome.notify.sender == 'u@example.com'
    assert outcome.notify.used == 6
    assert 'Failed to store message' in caplog.text


def test_unknown_protocol_states_are_neither_remembered_nor_errors(
    make_settings: Callable[..., Settings], logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    """Any local client could send unique states: no memory growth, no ERROR (a Zabbix alarm) per request."""
    svc = PolicyService(make_settings(), None, logger)  # type: ignore[arg-type]
    for i in range(100):
        assert svc.precheck(parse_request(postfix_request('u@example.com', protocol_state=f'X{i}'))) == Outcome(
            INVALID_ACTION
        )
    assert not svc._warned_states
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_answered_before_a_worker_was_free_is_not_counted(
    make_settings: Callable[..., Settings], logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    handover = Handover()
    assert handover.give_up() is None
    db = MagicMock()
    outcome = service(make_settings(), db).decide(parse_request(postfix_request('u@example.com')), handover)
    assert outcome == Outcome('DUNNO')
    db.connection.assert_not_called()
    assert 'Already answered DUNNO, not counting' in caplog.text


@pytest.mark.parametrize(
    ('fail_action', 'stored_blocked', 'status'), [('DUNNO', False, 'ACCEPTED'), ('DEFER_IF_PERMIT', True, 'BLOCKED')]
)
def test_counted_after_the_answer_records_what_postfix_got(
    fail_action: str,
    stored_blocked: bool,
    status: str,
    make_settings: Callable[..., Settings],
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The event loop answered FAIL_ACTION while the worker was counting: the log line and the messages row show
    that answer, and the webhook payload is still returned for the crossing request."""
    from policyd_rate_guard import service as service_module
    from policyd_rate_guard.ratelimit import Decision

    @contextmanager
    def connection() -> Any:
        yield MagicMock()

    db = MagicMock()
    db.connection = connection
    handover = Handover()

    def count(*args: Any) -> Decision:
        assert handover.give_up() is None  # DECIDE_TIMEOUT passes while counting
        return Decision(1, 5, 5, 6, 6, blocked=True, was_blocked=False)

    monkeypatch.setattr(service_module, 'count_message', count)
    store = MagicMock()
    monkeypatch.setattr(service_module, 'store_message', store)
    settings = make_settings(
        webhook=WebhookSettings(enabled=True, url='https://x/{sender}', secret=SECRET), fail_action=fail_action
    )
    outcome = service(settings, db).decide(parse_request(postfix_request('u@example.com', recipient_count=6)), handover)
    assert outcome.notify is not None
    assert handover.abandoned
    assert store.call_args.args[1].blocked is stored_blocked
    assert f'status={status} (DECIDE_TIMEOUT)' in caplog.text
