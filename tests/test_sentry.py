import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from policyd_rate_guard import sentry
from policyd_rate_guard.config import DbSettings, Settings, WebhookSettings
from policyd_rate_guard.sentry import Scrubber, init_sentry

from .helpers import SECRET


class CaptureTransport(Transport):
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Iterator[CaptureTransport]:
    capture = CaptureTransport()
    original = sentry_sdk.init

    def init(**kwargs: Any) -> Any:
        return original(transport=capture, **kwargs)

    monkeypatch.setattr(
        sentry, 'sentry_sdk', type('M', (), {'init': staticmethod(init), 'set_tag': sentry_sdk.set_tag})
    )
    yield capture
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # disable again


def test_scrubber() -> None:
    scrubber = Scrubber(['hunter22', SECRET, 'x'])  # too short secrets are ignored
    event = {
        'message': f'login user@example.com with hunter22 and {SECRET}',
        'extra': {'url': 'https://h/api/a@b.ch?token=abcdef&x=1', 'auth': 'Bearer eyJhbGciOi.xyz'},
        'list': ['to=<rcpt@example.org>', 42, None],
        'tuple': ('sasl_username=u@example.net,',),
    }
    assert scrubber.before_send(event, {}) == {
        'message': 'login [email] with [Filtered] and [Filtered]',
        'extra': {'url': 'https://h/api/[email]?token=[Filtered]&x=1', 'auth': 'Bearer [Filtered]'},
        'list': ['to=<[email]>', 42, None],
        'tuple': ('sasl_username=[email],',),
    }
    assert scrubber.before_breadcrumb({'message': 'a@b.ch'}, {}) == {'message': '[email]'}
    assert scrubber.before_send({'release': 'policyd-rate-guard@1.0.0', 'message': 'policyd-rate-guard@1.0.0'}, {}) == {
        'release': 'policyd-rate-guard@1.0.0',
        'message': '[email]',
    }


def test_init_without_dsn(make_settings: Callable[..., Settings]) -> None:
    assert init_sentry(make_settings()) is False


def test_events_contain_no_secrets_locals_or_addresses(
    transport: CaptureTransport, make_settings: Callable[..., Settings]
) -> None:
    settings = make_settings(
        sentry_dsn='https://public@example.invalid/1',
        db=DbSettings(password='db-password-123'),
        webhook=WebhookSettings(secret=SECRET),
    )
    assert init_sentry(settings)
    data_collection = sentry_sdk.get_client().options['data_collection']
    assert data_collection['user_info'] is False
    assert data_collection['stack_frame_variables'] is False
    assert data_collection['frame_context_lines'] == 0

    def failing(webhook_secret: str, sender: str) -> None:
        password = 'db-password-123'  # noqa: F841 (a local that 0.x would have sent)
        raise ConnectionError(f'cannot notify {sender} with {webhook_secret}')

    try:
        failing(SECRET, 'victim@example.com')
    except ConnectionError:
        sentry_sdk.capture_exception()
    logging.getLogger('policyd-rate-guard').error('Failed for sender other@example.com')
    sentry_sdk.flush()

    payload = b''.join(item.get_bytes() for envelope in transport.envelopes for item in envelope.items)
    assert payload, 'no event captured'
    for needle in (SECRET.encode(), b'db-password-123', b'victim@example.com', b'other@example.com', b'"vars"'):
        assert needle not in payload
    assert b'[email]' in payload
    assert b'policyd-rate-guard@' in payload  # release
