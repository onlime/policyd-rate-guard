"""Webhook notification when a sender reaches the quota (once per period).

It runs after the reply has been sent to Postfix, in its own thread, with timeouts: a slow or failing webhook can
neither delay the policy decision nor turn a block into DUNNO.
"""

import logging
from base64 import b64decode
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

import jwt
import requests

from . import __version__
from .protocol import sanitize

if TYPE_CHECKING:
    from .config import WebhookSettings

JWT_ISSUER = 'policyd-rate-guard'
JWT_LIFETIME = timedelta(seconds=60)
TIMEOUT = (3.0, 10.0)  # connect, read (seconds)
MAX_LOGGED_BODY = 200


@dataclass(frozen=True, slots=True)
class WebhookPayload:
    msgid: str | None
    sender: str
    client_address: str | None
    client_name: str | None
    rcpt_count: int
    from_addr: str | None
    to_addr: str | None
    timestamp: str
    quota: int
    quota_reset: int
    used: int


class Webhook:
    def __init__(self, settings: 'WebhookSettings', logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.session = requests.Session()
        self.session.trust_env = False  # no proxies or .netrc credentials from the environment
        self.user_agent = f'policyd-rate-guard/{__version__}'

    def jwt_token(self, sender: str, now: datetime | None = None) -> str:
        issued = now or datetime.now(tz=UTC)
        claims = {'sub': sender, 'iss': JWT_ISSUER, 'iat': issued, 'nbf': issued, 'exp': issued + JWT_LIFETIME}
        return jwt.encode(claims, b64decode(self.settings.secret), algorithm='HS256')

    def build_request(self, payload: WebhookPayload) -> tuple[str, dict[str, str]]:
        placeholders = {
            key: quote('' if value is None else str(value), safe='@') for key, value in asdict(payload).items()
        }
        headers = {
            'User-Agent': self.user_agent,
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.jwt_token(payload.sender)}',
        }
        return self.settings.url.format(**placeholders), headers

    def call(self, payload: WebhookPayload) -> bool:
        """POST the payload. Never raises; returns whether the webhook accepted it."""
        try:
            url, headers = self.build_request(payload)
            response = self.session.post(
                url,
                headers=headers,
                json=asdict(payload),
                timeout=TIMEOUT,
                allow_redirects=False,
            )
        except Exception as e:  # a webhook failure must never affect mail flow
            # Only the exception type and the URL template: the message may contain the token
            self.logger.warning('Webhook call failed: POST %s (%s)', self.settings.url, type(e).__name__)
            return False
        if 200 <= response.status_code < 300:  # redirects aren't followed, so a 3xx is a failure too
            self.logger.info('Webhook call successful: POST %s (User-Agent: %s)', self.settings.url, self.user_agent)
            return True
        self.logger.warning(
            'Webhook call failed with status code: %s %s',
            response.status_code,
            sanitize(response.text, MAX_LOGGED_BODY),
        )
        return False
