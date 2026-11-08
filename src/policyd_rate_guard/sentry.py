"""Sentry error reporting without personal data or secrets.

sentry-sdk sends local variables of every stack frame by default, and its scrubber only matches exact key
names: the webhook secret and the DB password (inside DBUtils' connection kwargs) were sent in 0.x. Local
variables are disabled here, HTTP breadcrumbs (with the webhook URL) are dropped, and every string in an event or
breadcrumb is scrubbed of email addresses, configured secrets and token query parameters.
"""

import logging
import re
import socket
import threading
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from . import __version__
from .config import Settings

EMAIL_RE = re.compile(r'[^\s<>"\'=,;:()\[\]{}/?&#]+@[^\s<>"\'=,;:()\[\]{}/?&#]+')
TOKEN_RE = re.compile(r'(?i)(token=|bearer\s+)[^\s&"\']+')
FILTERED = '[Filtered]'
# Event metadata set by us or the SDK; the release "policyd-rate-guard@1.0.0" would look like an address
METADATA_KEYS = frozenset({'release', 'environment', 'platform', 'sdk', 'server_name', 'event_id', 'timestamp',
                           'level', 'logger', 'dist'})  # fmt: skip


class Scrubber:
    def __init__(self, secrets: list[str]) -> None:
        # longest first, so a secret containing another one is replaced as a whole
        self.secrets = sorted({s for s in secrets if len(s) >= 4}, key=len, reverse=True)

    def scrub_text(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, FILTERED)
        text = TOKEN_RE.sub(lambda m: m.group(1) + FILTERED, text)
        return EMAIL_RE.sub('[email]', text)

    def scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, dict):
            return {key: self.scrub(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return type(value)(self.scrub(item) for item in value)
        return value

    def before_send(self, event: Any, hint: Any) -> Any:
        if not isinstance(event, dict):  # pragma: no cover
            return self.scrub(event)
        return {key: value if key in METADATA_KEYS else self.scrub(value) for key, value in event.items()}

    def before_breadcrumb(self, crumb: Any, hint: Any) -> Any:
        # sentry-sdk's HTTP integration records every request with its URL: the webhook's contains the mailbox,
        # and a legacy username without @ isn't scrubbed as an address
        if isinstance(crumb, dict) and crumb.get('category') == 'httplib':
            return None
        return self.scrub(crumb)


def init_sentry(settings: Settings) -> bool:
    if not settings.sentry_dsn:
        return False
    scrubber = Scrubber(settings.secrets())
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=f'policyd-rate-guard@{__version__}',
        # Everything off; an explicit data_collection would otherwise default user_info to True
        data_collection={
            'user_info': False,
            'cookies': {'mode': 'off'},
            'http_headers': {'request': {'mode': 'off'}},
            'http_bodies': [],
            'url_query_params': {'mode': 'off'},
            'database_query_data': False,
            'queues': False,
            'stack_frame_variables': False,
            'frame_context_lines': 0,
        },
        include_local_variables=False,  # still read directly by some sentry-sdk code paths
        max_breadcrumbs=20,
        # no sentry-trace/baggage headers on the webhook calls: the baggage carries the DSN's public key
        trace_propagation_targets=[],
        before_send=scrubber.before_send,
        before_breadcrumb=scrubber.before_breadcrumb,
        integrations=[LoggingIntegration(level=None, event_level=logging.ERROR)],
    )
    # In addition to the (auto-detected) server_name, provide the FQDN as tag. getfqdn() asks DNS, which may hang:
    # in the background, so the daemon serves right away (Postfix's requests would wait in the socket meanwhile).
    threading.Thread(target=_set_fqdn_tag, name='sentry-fqdn', daemon=True).start()
    return True


def _set_fqdn_tag() -> None:
    sentry_sdk.get_global_scope().set_tag('fqdn', socket.getfqdn())
