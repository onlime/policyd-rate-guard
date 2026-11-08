import hashlib
import logging
from base64 import b64decode
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import jwt
import pytest
import requests

from policyd_rate_guard import __version__
from policyd_rate_guard.config import WebhookSettings
from policyd_rate_guard.webhook import Webhook, WebhookPayload

SECRET = 'Wk9YZXliVlVtY2pQcFlFUm9KY1U1ZkFFaUpWTk1FU20='


def payload(sender: str = 'test@example.com') -> WebhookPayload:
    return WebhookPayload(
        msgid='TEST1234567', sender=sender, client_address='172.19.0.2', client_name='unknown', rcpt_count=3,
        from_addr='test@example.com', to_addr='to_test@example.com', timestamp='2026-11-08 12:00:00',
        quota=1000, quota_reset=1000, used=1003,
    )  # fmt: skip


def webhook(logger: logging.Logger, **overrides: Any) -> Webhook:
    values: dict[str, Any] = {
        'enabled': True,
        'url': 'https://example.com/api/policyd/{sender}?token={token}',
        'secret': SECRET,
    }
    settings = WebhookSettings(**(values | overrides))
    return Webhook(settings, logger)


def mock_post(hook: Webhook, status: int = 200, text: str = '{"success": true}') -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.ok = 200 <= status < 300
    response.status_code = status
    response.text = text
    post = MagicMock(return_value=response)
    hook.session.post = post  # type: ignore[method-assign]
    return post


def test_simple_token_is_unchanged_from_0x(logger: logging.Logger) -> None:
    hook = webhook(logger)
    expected = '34caa5c52fce98bc56fa3bfd8274a92328f09a6e0b27da2b5d89c1b5c5ed05c5'
    assert hook.simple_token('test@example.com') == expected
    assert expected == hashlib.sha256(f'{SECRET}test@example.com'.encode()).hexdigest()


def test_call_with_simple_token_in_query(logger: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
    hook = webhook(logger)
    post = mock_post(hook)
    with caplog.at_level(logging.INFO):
        assert hook.call(payload())
    token = hook.simple_token('test@example.com')
    url = post.call_args.args[0]
    assert url == f'https://example.com/api/policyd/test@example.com?token={token}'
    kwargs = post.call_args.kwargs
    assert kwargs['headers'] == {'User-Agent': f'policyd-rate-guard/{__version__}', 'Accept': 'application/json'}
    assert kwargs['json']['sender'] == 'test@example.com'
    assert kwargs['json']['rcpt_count'] == 3
    assert kwargs['timeout'] == (3.0, 10.0)
    assert kwargs['allow_redirects'] is False
    assert 'Webhook call successful: POST https://example.com/api/policyd/{sender}?token={token}' in caplog.text
    assert token not in caplog.text


def test_call_with_jwt_bearer(logger: logging.Logger) -> None:
    hook = webhook(logger, url='https://example.com/api/policyd/{sender}', use_jwt=True)
    post = mock_post(hook)
    assert hook.call(payload())
    headers = post.call_args.kwargs['headers']
    token = headers['Authorization'].removeprefix('Bearer ')
    claims = jwt.decode(token, b64decode(SECRET), algorithms=['HS256'], issuer='policyd-rate-guard')
    assert claims['sub'] == 'test@example.com'
    assert claims['exp'] - claims['iat'] == 60
    assert claims['nbf'] == claims['iat']


def test_jwt_claims_are_unchanged(logger: logging.Logger) -> None:
    now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    token = webhook(logger, use_jwt=True).jwt_token('a@example.com', now=now)
    claims = jwt.decode(
        token,
        b64decode(SECRET),
        algorithms=['HS256'],
        options={'verify_exp': False, 'verify_iat': False, 'verify_nbf': False},
    )
    assert claims == {'sub': 'a@example.com', 'iss': 'policyd-rate-guard', 'iat': 1794139200,
                      'nbf': 1794139200, 'exp': 1794139260}  # fmt: skip


def test_placeholders_are_url_encoded(logger: logging.Logger) -> None:
    hook = webhook(logger, url='https://example.com/api/{sender}/{client_name}?q={token}')
    url, _ = hook.build_request(payload(sender='a/../b?c#d@example.com'))
    assert url.startswith('https://example.com/api/a%2F..%2Fb%3Fc%23d@example.com/unknown?q=')


def test_failed_call_logs_no_token(logger: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
    hook = webhook(logger)
    token = hook.simple_token('test@example.com')
    hook.session.post = MagicMock(  # type: ignore[method-assign]
        side_effect=requests.ConnectionError(f'Max retries exceeded with url: /?token={token}')
    )
    assert not hook.call(payload())
    assert 'Webhook call failed: POST https://example.com/api/policyd/{sender}?token={token} (ConnectionError)' in (
        caplog.text
    )
    assert token not in caplog.text


def test_non_2xx_is_logged_truncated(logger: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
    hook = webhook(logger)
    mock_post(hook, status=500, text='E' * 1000 + '\nmore')
    assert not hook.call(payload())
    assert 'Webhook call failed with status code: 500 ' + 'E' * 200 + '…' in caplog.text


def test_session_ignores_environment(logger: logging.Logger) -> None:
    assert webhook(logger).session.trust_env is False
