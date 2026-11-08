"""Webhook notification when a sender reaches the quota (once per period).

It runs after the reply has been sent to Postfix, in a separate executor, with timeouts: a slow or failing
webhook can neither delay the policy decision nor turn a block into DUNNO.
"""

import hashlib
import logging
from base64 import b64decode
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import jwt
import requests

from . import __version__
from .config import WebhookSettings
from .protocol import sanitize

JWT_ISSUER = 'policyd-rate-guard'
JWT_LIFETIME = timedelta(seconds=60)
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
    def __init__(self, settings: WebhookSettings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.session = requests.Session()
        self.session.trust_env = False  # no proxies or .netrc credentials from the environment
        self.user_agent = f'policyd-rate-guard/{__version__}'

    def simple_token(self, sender: str) -> str:
        """Legacy token: sha256(secret + sender). Static and replayable, use JWT instead."""
        return hashlib.sha256(f'{self.settings.secret}{sender}'.encode()).hexdigest()

    def jwt_token(self, sender: str, now: datetime | None = None) -> str:
        issued = now or datetime.now(tz=UTC)
        claims = {'sub': sender, 'iss': JWT_ISSUER, 'iat': issued, 'nbf': issued, 'exp': issued + JWT_LIFETIME}
        return jwt.encode(claims, b64decode(self.settings.secret), algorithm='HS256')

    def build_request(self, payload: WebhookPayload) -> tuple[str, dict[str, str]]:
        data = asdict(payload)
        token = self.jwt_token(payload.sender) if self.settings.use_jwt else self.simple_token(payload.sender)
        headers = {'User-Agent': self.user_agent, 'Accept': 'application/json'}
        placeholders = {key: quote('' if value is None else str(value), safe='@') for key, value in data.items()}
        if '{token}' in self.settings.url:
            # Variant 1: token as query parameter (usually the simple token)
            url = self.settings.url.format(**placeholders, token=quote(token, safe=''))
        else:
            # Variant 2: token as bearer token (usually JWT)
            headers['Authorization'] = f'Bearer {token}'
            url = self.settings.url.format(**placeholders)
        return url, headers

    def call(self, payload: WebhookPayload) -> bool:
        """POST the payload. Never raises; returns whether the webhook accepted it."""
        try:
            url, headers = self.build_request(payload)
            response = self.session.post(
                url,
                headers=headers,
                json=asdict(payload),
                timeout=(self.settings.connect_timeout, self.settings.read_timeout),
                allow_redirects=False,
            )
        except Exception as e:  # noqa: BLE001 (a webhook failure must never affect mail flow)
            # Only the exception type and the URL template: the message may contain the token
            self.logger.warning('Webhook call failed: POST %s (%s)', self.settings.url, type(e).__name__)
            return False
        if response.ok:
            self.logger.info('Webhook call successful: POST %s (User-Agent: %s)', self.settings.url, self.user_agent)
            return True
        self.logger.warning(
            'Webhook call failed with status code: %s %s',
            response.status_code,
            sanitize(response.text, MAX_LOGGED_BODY),
        )
        return False
