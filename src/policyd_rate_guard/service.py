"""Policy decision for one request. Runs in a worker thread (blocking DB access)."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from .config import Settings
from .db import Database
from .log import queue_id_context
from .protocol import COUNTING_STATES, POSTFIX_STATES, PolicyRequest, sanitize
from .ratelimit import SENDER_MAX, Decision, MessageRecord, count_message, store_message
from .webhook import WebhookPayload

DUNNO = 'DUNNO'
OK = 'OK'
# Answer for requests that are applicable but carry invalid data. Postfix never sends such values, so they come
# from something else talking to the socket: never let them pass as DUNNO.
INVALID_ACTION = 'DEFER_IF_PERMIT Invalid policy request'
MAX_RECIPIENT_COUNT = 1_000_000


@dataclass(frozen=True, slots=True)
class Outcome:
    action: str
    notify: WebhookPayload | None = None


class Handover:
    """Hands the decision from the worker to the event loop, which answers FAIL_ACTION after DECIDE_TIMEOUT.

    Once the event loop has given up, the worker must not count a message it hasn't counted yet, and must log, store
    and notify what Postfix actually got for one it has. ``on_decision`` lets the event loop answer as soon as the
    message is counted, without waiting for the worker to store and log it.
    """

    def __init__(self, on_decision: Callable[[Outcome], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._on_decision = on_decision
        self.abandoned = False
        self.outcome: Outcome | None = None

    def give_up(self) -> Outcome | None:
        """Event loop, on timeout: the decision if the message is counted already, else None (FAIL_ACTION)."""
        with self._lock:
            if self.outcome is None:
                self.abandoned = True
            return self.outcome

    def hand_over(self, outcome: Outcome) -> bool:
        """Worker, right after counting: False if the event loop has answered FAIL_ACTION already."""
        with self._lock:
            if self.abandoned:
                return False
            self.outcome = outcome
        if self._on_decision is not None:
            self._on_decision(outcome)
        return True


class PolicyService:
    def __init__(self, settings: Settings, db: Database, logger: logging.Logger) -> None:
        self.settings = settings
        self.db = db
        self.logger = logger
        self.blocked_action = f'DEFER_IF_PERMIT {settings.action_text_blocked}'
        self._warned_states: set[str] = set()

    def precheck(self, request: PolicyRequest) -> Outcome | None:
        """Decide without the DB where possible (cheap, runs in the event loop). None means: needs ``decide()``."""
        with queue_id_context(request.queue_id):
            try:
                return self._precheck(request)
            except Exception:
                self.logger.exception('Unhandled exception, answering %s', self.settings.fail_action)
                return Outcome(self.settings.fail_action)

    def decide(self, request: PolicyRequest, handover: Handover | None = None) -> Outcome:
        """Count the message and decide (blocking DB access, runs in a worker thread)."""
        with queue_id_context(request.queue_id):
            if handover is not None and handover.abandoned:
                self.logger.warning('Already answered %s, not counting', self.settings.fail_action)
                return Outcome(self.settings.fail_action)
            try:
                return self._decide(request, handover)
            except Exception:
                if handover is not None and handover.abandoned:
                    # the event loop answered FAIL_ACTION already, and logged that at ERROR
                    self.logger.warning('Failed after the answer was given', exc_info=True)
                else:
                    self.logger.exception('Unhandled exception, answering %s', self.settings.fail_action)
                return Outcome(self.settings.fail_action)

    def _precheck(self, request: PolicyRequest) -> Outcome | None:
        if request.request_type != 'smtpd_access_policy':
            self.logger.warning('Ignoring request of type %s', sanitize(request.request_type, 64))
            return Outcome(DUNNO)

        sender = request.sasl_username
        if not sender:
            # e.g. incoming mail on port 25
            self.logger.debug('sasl_username is empty, accepting message and reply with DUNNO')
            return Outcome(DUNNO)

        state = request.protocol_state or ''
        if state not in COUNTING_STATES:
            if state not in POSTFIX_STATES:
                # not from Postfix: never let it pass as DUNNO (and don't remember arbitrary values)
                self.logger.warning('Invalid request: protocol_state=%s', sanitize(state, 32))
                return Outcome(INVALID_ACTION)
            if state not in self._warned_states:
                self._warned_states.add(state)
                # every authenticated mail passes uncounted: an ERROR, which Zabbix alerts on
                self.logger.error(
                    'Not counting in protocol state %s: use check_policy_service in smtpd_data_restrictions '
                    '(or smtpd_end_of_data_restrictions)',
                    state,
                )
            return Outcome(DUNNO)

        rcpt_count = request.recipient_count(MAX_RECIPIENT_COUNT)
        if rcpt_count is None or len(sender) > SENDER_MAX:
            self.logger.warning(
                'Invalid request: sasl_username=%s recipient_count=%s',
                sanitize(sender, 300),
                sanitize(request.get('recipient_count'), 32),
            )
            return Outcome(INVALID_ACTION)
        return None

    def _decide(self, request: PolicyRequest, handover: Handover | None) -> Outcome:
        sender = request.sasl_username
        rcpt_count = request.recipient_count(MAX_RECIPIENT_COUNT)
        if sender is None or rcpt_count is None:  # pragma: no cover (rejected by _precheck)
            raise ValueError('decide() called for a request that failed the pre-check')

        record = MessageRecord(
            queue_id=request.queue_id,
            sender=sender,
            rcpt_count=rcpt_count,
            from_addr=request.get('sender'),
            to_addr=request.get('recipient'),
            client_address=request.get('client_address'),
            client_name=request.get('client_name'),
            created_at=datetime.now().astimezone(),
        )

        with self.db.connection() as conn:
            decision = count_message(conn, sender, rcpt_count, self.settings.quota)
            # The decision stands, whatever happens from here on
            if decision.blocked:
                notify = self._payload(record, decision) if decision.crossed and self.settings.webhook.enabled else None
                outcome = Outcome(self.blocked_action, notify)
            else:
                outcome = Outcome(OK)
            answered = handover is None or handover.hand_over(outcome)
            # Too late: Postfix got FAIL_ACTION (the server logged it). Record that answer; the webhook still fires.
            given = decision if answered else replace(decision, blocked=self.settings.fail_action != DUNNO)
            try:
                store_message(conn, given, record)
            except Exception:
                if answered:
                    self.logger.exception('Failed to store message')
                else:  # the event loop logged this request's timeout at ERROR already
                    self.logger.warning('Failed to store message', exc_info=True)

        self._log_decision(request, record, given, None if answered else 'DECIDE_TIMEOUT')
        return outcome

    def _log_decision(
        self, request: PolicyRequest, record: MessageRecord, decision: Decision, reason: str | None = None
    ) -> None:
        # Detailed log line, format kept from 0.x (parsed by operations scripts):
        # client=unknown[8.8.8.8], helo=myCLIENTPC, sasl_method=PLAIN, sasl_username=test@example.com, from=…,
        # to=…, recipient_count=1, curr_count=2/1000, status=ACCEPTED
        line = (
            f'client={sanitize(record.client_name)}[{sanitize(record.client_address)}], '
            f'helo={sanitize(request.get("helo_name"))}, sasl_method={sanitize(request.get("sasl_method"))}, '
            f'sasl_username={sanitize(record.sender)}, from={sanitize(record.from_addr)}, '
            f'to={sanitize(record.to_addr)}, recipient_count={record.rcpt_count}, '
            f'curr_count={decision.rcpt_counter}/{decision.quota}, '
            f'status={"BLOCKED" if decision.blocked else "ACCEPTED"}'
            f'{f" ({reason})" if reason else " (QUOTA_LIMIT_REACHED)" if decision.crossed else ""}'
        )
        if decision.blocked:
            self.logger.warning(
                'Message BLOCKED: sender=%s rcpt_count=%s from_addr=%s client_address=%s client_name=%s',
                sanitize(record.sender),
                record.rcpt_count,
                sanitize(record.from_addr),
                sanitize(record.client_address),
                sanitize(record.client_name),
            )
            self.logger.warning('%s', line)
        else:
            self.logger.info('%s', line)

    @staticmethod
    def _payload(record: MessageRecord, decision: Decision) -> WebhookPayload:
        return WebhookPayload(
            msgid=record.queue_id,
            sender=record.sender,
            client_address=record.client_address,
            client_name=record.client_name,
            rcpt_count=record.rcpt_count,
            from_addr=record.from_addr,
            to_addr=record.to_addr,
            timestamp=record.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            quota=decision.quota,
            quota_reset=decision.quota_reset,
            used=decision.rcpt_counter,
        )
