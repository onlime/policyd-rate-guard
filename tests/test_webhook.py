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
        'url': 'https://example.com/api/policyd/{sender}',
        'secret': SECRET,
    }
    settings = WebhookSettings(**(values | overrides))
    return Webhook(settings, logger)


def mock_post(hook: Webhook, status: int = 200, text: str = '{"success": true}') -> MagicMock:
    response = requests.Response()
    response.status_code = status
    response._content = text.encode()
    response.encoding = 'utf-8'
    post = MagicMock(return_value=response)
    hook.session.post = post
    return post


def test_call_with_jwt_bearer(logger: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
    hook = webhook(logger)
    post = mock_post(hook)
    with caplog.at_level(logging.INFO):
        assert hook.call(payload())
    assert post.call_args.args[0] == 'https://example.com/api/policyd/test@example.com'
    kwargs = post.call_args.kwargs
    headers = kwargs['headers']
    token = headers.pop('Authorization').removeprefix('Bearer ')
    assert headers == {'User-Agent': f'policyd-rate-guard/{__version__}', 'Accept': 'application/json'}
    claims = jwt.decode(token, b64decode(SECRET), algorithms=['HS256'], issuer='policyd-rate-guard')
    assert claims['sub'] == 'test@example.com'
    assert claims['exp'] - claims['iat'] == 60
    assert claims['nbf'] == claims['iat']
    assert kwargs['json']['sender'] == 'test@example.com'
    assert kwargs['json']['rcpt_count'] == 3
    assert kwargs['timeout'] == (3.0, 10.0)
    assert kwargs['allow_redirects'] is False
    assert 'Webhook call successful: POST https://example.com/api/policyd/{sender}' in caplog.text
    assert token not in caplog.text


def test_jwt_claims_are_unchanged(logger: logging.Logger) -> None:
    now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    token = webhook(logger).jwt_token('a@example.com', now=now)
    claims = jwt.decode(
        token,
        b64decode(SECRET),
        algorithms=['HS256'],
        options={'verify_exp': False, 'verify_iat': False, 'verify_nbf': False},
    )
    assert claims == {'sub': 'a@example.com', 'iss': 'policyd-rate-guard', 'iat': 1794139200,
                      'nbf': 1794139200, 'exp': 1794139260}  # fmt: skip


def test_placeholders_are_url_encoded(logger: logging.Logger) -> None:
    hook = webhook(logger, url='https://example.com/api/{sender}/{client_name}?msgid={msgid}')
    url, _ = hook.build_request(payload(sender='a/../b?c#d@example.com'))
    assert url == 'https://example.com/api/a%2F..%2Fb%3Fc%23d@example.com/unknown?msgid=TEST1234567'


def test_failed_call_logs_only_the_url_template(logger: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
    hook = webhook(logger)
    hook.session.post = MagicMock(
        side_effect=requests.ConnectionError('Max retries exceeded with url: /api/policyd/test@example.com')
    )
    assert not hook.call(payload())
    assert 'Webhook call failed: POST https://example.com/api/policyd/{sender} (ConnectionError)' in caplog.text
    assert 'test@example.com' not in caplog.text
    assert caplog.records[-1].levelname == 'ERROR'  # no notification: Zabbix alerts on ERROR lines


def test_non_2xx_is_logged_truncated(logger: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
    hook = webhook(logger)
    mock_post(hook, status=500, text='E' * 1000 + '\nmore')
    assert not hook.call(payload())
    assert 'Webhook call failed with status code: 500 ' + 'E' * 200 + '…' in caplog.text


def test_session_ignores_environment(logger: logging.Logger) -> None:
    assert webhook(logger).session.trust_env is False


def test_redirect_is_a_failure(logger: logging.Logger, caplog: pytest.LogCaptureFixture) -> None:
    """Redirects aren't followed (the JWT would go elsewhere), so a 302 means the notification wasn't delivered."""
    hook = webhook(logger)
    mock_post(hook, status=302, text='')
    assert not hook.call(payload())
    assert 'Webhook call failed with status code: 302' in caplog.text
