from app.message import Message

class Handler:
    """Handle request"""

    data = ''

    def __init__(self, conn: object, addr: str, conf: object, logger: object, db_pool: object):
        self.conn = conn
        self.addr = addr
        self.conf = conf
        self.logger = logger
        self.db_pool = db_pool
        try:
            self.handle()
        except Exception as e: # pragma: no cover
            self.logger.exception('Unhandled Exception: %s', e)
            self.logger.warning('Received DATA: %s', self.data)
            self.send_response('DUNNO') # use DUNNO as accept action, just to distinguish between OK and unhandled exception

    def handle(self):
        """Handle request"""
        # Read data
        self.data = self.conn.recv(2048).decode('utf-8') # Attention: We only read first 2048 bytes, which is sufficient for our needs
        if not self.data:
            raise Exception('No data received')
        self.logger.debug('Received data: %s', self.data)

        # Parse data
        request = {}
        for line in self.data.split("\n"): # TODO: How to get subject, cc, bcc?
            line = line.strip()
            try:
                key, value = line.split(u'=', 1)
                if value:
                    self.logger.debug('Received header: %s=%s', key, value)
                    request[key] = value
            except ValueError: # Needed to ignore lines without "=" (e.g. the final two empty lines)
                pass

        # Add msgid to logger
        self.logger.msgid = request.get('queue_id')

        # Break no sasl_username was found (e.g. on incoming mail on port 25)
        if not request.get('sasl_username'):
            self.logger.debug('sasl_username is empty, accepting message and reply with DUNNO')
            self.send_response('DUNNO')
            return
        
        # Temp debugging of message data without recipient (e.g. on multiple To: addresses)
        # if not request.get('recipient'):
        #     self.logger.warning('Received DATA with no recipient: %s', self.data)

        # Get database connection from DB pool
        self.db = self.db_pool.connection()

        # Handle message
        message = Message(
            msgid=request['queue_id'],
            sender=request['sasl_username'],
            client_address=request['client_address'],
            client_name=request['client_name'],
            rcpt_count=request['recipient_count'],
            from_addr=request.get('sender'),
            to_addr=request.get('recipient'),
            cc_addr=request.get('cc_address'),
            bcc_addr=request.get('bcc_address'),
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
        # TEST1234567: client=unknown[8.8.8.8], helo=myCLIENTPC, sasl_method=PLAIN, sasl_username=test@example.com, recipient_count=1, curr_count=2/1000, status=ACCEPTED
        log_message = 'client={}[{}], helo={}, sasl_method={}, sasl_username={}, from={}, to={}, recipient_count={}, curr_count={}/{}, status={}{}'.format(
            message.client_name,
            message.client_address,
            request.get('helo_name'), # currently not stored in Message object or `messages` table
            request['sasl_method'], # currently not stored in Message object or `messages` table
            message.sender,
            message.from_addr,
            message.to_addr,
            message.rcpt_count,
            message.ratelimit.rcpt_counter,
            message.ratelimit.quota,
            'BLOCKED' if blocked else 'ACCEPTED',
            ' (QUOTA_LIMIT_REACHED)' if blocked and not was_blocked else ''
        )

        # Create response
        if blocked:
            self.logger.warning('Message BLOCKED: %s', message.get_props_description())
            if not was_blocked: # TODO: Implement webhook API call for notification to sender on quota limit reached (only on first block)
                self.logger.debug('Quota limit reached for %s, notifying sender via webhook!', message.sender)
            self.logger.warning(log_message)
            self.send_response('DEFER_IF_PERMIT ' + self.conf.get('ACTION_TEXT_BLOCKED', 'Rate limit reached, retry later'))
        else:
            self.logger.debug('Message ACCEPTED: %s', message.get_props_description())
            self.logger.info(log_message)
            self.send_response('OK')

    def send_response(self, message: str = 'OK'):
        """Send response"""
        # actions return to Postfix, see http://www.postfix.org/access.5.html for a list of actions.
        data = 'action={}\n\n'.format(message)
        self.logger.debug('Sending data: %s', data)
        self.conn.send(data.encode('utf-8'))
        self.conn.close()
        self.logger.msgid = None # Reset msgid in logger
        # TODO: Do we need to close the cursor as well? (prior to closing the connection)
        if self.db:
            self.db.close() # Close database connection
