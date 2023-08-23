from app.message import Message

class Handler:
    """Handle request"""

    request = {}

    def __init__(self, conn, addr, conf, logger, db):
        self.conn = conn
        self.addr = addr
        self.conf = conf
        self.logger = logger # TODO: Add msgid to logger
        self.db = db
        try:
            self.handle()
        except Exception as e: # pragma: no cover
            self.logger.exception('handler.py - Unhandled Exception: %s', e)
            self.send_response('OK')
            self.conn.close()
            # raise e # TODO: Integrate sentry-sdk, see #1

    def handle(self):
        """Handle request"""
        # Read data
        data = self.conn.recv(2048).decode('utf-8') # Attention: We only read first 2048 bytes, which is sufficient for our needs
        if not data:
            raise Exception('No data received')
        self.logger.debug('handler.py - Received data: %s', data)
        # Parse data
        for line in data.split("\n"): # TODO: How to get subject, cc, bcc?
            line = line.strip()
            try:
                key, value = line.split(u'=', 1)
                if value:
                    self.logger.debug('handler.py - Received header: %s=%s', key, value)
                    self.request[key] = value
            except ValueError: # Needed to ignore lines without "=" (e.g. the final two empty lines)
                pass

        # Handle message
        message = Message(
            self.request['sasl_username'],
            self.request['client_address'],
            self.request['recipient_count'],
            self.request['queue_id'],
            self.request['sender'],
            self.request.get('recipient'),
            self.request.get('cc_address'),
            self.request.get('bcc_address'),
            self.db,
            self.conf,
            self.logger
        )
        message.get_ratelimit()
        message.update_ratelimit() # Always update counter, even if the message was blocked!
        blocked = message.is_blocked() # ... and make sure we check for blocked after having raised the counter.
        message.store()

        # Create response
        if blocked:
            self.logger.warning('handler.py - Message from %s blocked', message.sender) # TODO: More information (msgid, recipient_count, sender, from_addr, sender_ip, etc.)
            self.send_response('DEFER_IF_PERMIT ' + self.conf.get('ACTION_TEXT_BLOCKED', 'Rate limit reached, retry later'))
        else:
            self.logger.info('handler.py - Message from %s accepted', message.sender) # TODO: More information (msgid, recipient_count, sender, from_addr, sender_ip, etc.)
            self.send_response('OK')

        self.conn.close()

    def send_response(self, message: str = 'OK'):
        """Send response"""
        # actions return to postfix, see http://www.postfix.org/access.5.html for a list of actions.
        data = 'action={}\n\n'.format(message)
        self.logger.debug('handler.py - Sending data: %s', data)
        self.conn.send(data.encode('utf-8'))
