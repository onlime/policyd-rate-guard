from app.message import Message

class Handler:
    """Handle request"""

    request = {}
    data = ''

    def __init__(self, conn: object, addr: str, conf: object, logger: object, db: object):
        self.conn = conn
        self.addr = addr
        self.conf = conf
        self.logger = logger # TODO: Add msgid to logger
        self.db = db
        try:
            self.handle()
        except Exception as e: # pragma: no cover
            self.logger.exception('handler.py - Unhandled Exception: %s', e)
            self.logger.warning('handler.py - Received DATA: %s', self.data)
            self.send_response('DUNNO') # use DUNNO as accept action, just to distinguish between OK and unhandled exception
            self.conn.close()

    def handle(self):
        """Handle request"""

        # PyMySQL: Ensure the db connection is alive
        # if self.conf.get('DB_DRIVER', 'pymysql').lower() == 'pymysql':
        #     self.db.ping(reconnect=True)

        # Read data
        self.data = self.conn.recv(2048).decode('utf-8') # Attention: We only read first 2048 bytes, which is sufficient for our needs
        if not self.data:
            raise Exception('No data received')
        self.logger.debug('handler.py - Received data: %s', self.data)
        # Parse data
        for line in self.data.split("\n"): # TODO: How to get subject, cc, bcc?
            line = line.strip()
            try:
                key, value = line.split(u'=', 1)
                if value:
                    self.logger.debug('handler.py - Received header: %s=%s', key, value)
                    self.request[key] = value
            except ValueError: # Needed to ignore lines without "=" (e.g. the final two empty lines)
                pass

        # Break no sasl_username was found (e.g. on incoming mail on port 25)
        if 'sasl_username' not in self.request:
            self.logger.debug('handler.py - sasl_username is empty, accepting message and reply with DUNNO')
            self.send_response('DUNNO')
            self.conn.close()
            return

        # Handle message
        message = Message(
            msgid=self.request['queue_id'],
            sender=self.request['sasl_username'] or '_NO_SASL_' + self.request['sender'],
            client_address=self.request['client_address'],
            client_name=self.request['client_name'],
            rcpt_count=self.request['recipient_count'],
            from_addr=self.request['sender'],
            to_addr=self.request.get('recipient'),
            cc_addr=self.request.get('cc_address'),
            bcc_addr=self.request.get('bcc_address'),
            db=self.db,
            conf=self.conf,
            logger=self.logger
        )
        message.get_ratelimit()
        was_blocked = message.is_blocked()
        message.update_ratelimit() # Always update counter, even if quota limit was already reached before (was_blocked)!
        blocked = message.is_blocked() # ... and make sure we check for blocked after having raised the counter.
        message.store()

        # Detailed log message in the following format:
        # TEST1234567: client=unknown[8.8.8.8], sasl_method=PLAIN, sasl_username=test@example.com, recipient_count=1, curr_count=2/1000, status=ACCEPTED
        log_message = '{}: client={}[{}], sasl_method={}, sasl_username={}, from={}, recipient_count={}, curr_count={}/{}, status={}{}'.format(
            message.msgid,
            message.client_name,
            message.client_address,
            self.request['sasl_method'], # currently not stored in Message object or `messages` table
            message.sender,
            message.from_addr,
            message.rcpt_count,
            message.ratelimit.rcpt_counter,
            message.ratelimit.quota,
            'BLOCKED' if blocked else 'ACCEPTED',
            ' (QUOTA_LIMIT_REACHED)' if blocked and not was_blocked else ''
        )

        # Create response
        if blocked:
            self.logger.warning('handler.py - Message BLOCKED: %s', message.get_props_description())
            self.send_response('DEFER_IF_PERMIT ' + self.conf.get('ACTION_TEXT_BLOCKED', 'Rate limit reached, retry later'))
            if not was_blocked: # TODO: Implement webhook API call for notification to sender on quota limit reached (only on first block)
                self.logger.debug('handler.py - Quota limit reached for %s, notifying sender via webhook!', message.sender)
            self.logger.warning(log_message)
        else:
            self.logger.debug('handler.py - Message ACCEPTED: %s', message.get_props_description())
            self.send_response('OK')
            self.logger.info(log_message)

        self.conn.close()

    def send_response(self, message: str = 'OK'):
        """Send response"""
        # actions return to postfix, see http://www.postfix.org/access.5.html for a list of actions.
        data = 'action={}\n\n'.format(message)
        self.logger.debug('handler.py - Sending data: %s', data)
        self.conn.send(data.encode('utf-8'))
