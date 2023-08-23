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
        self.handle() # TODO: Log exceptions & close connection & raise exception

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
            except ValueError: # Needed to ignore lines w/o "=" (e.g. empty lines)
                pass

        # Handle message
        message = Message(
            self.request['sasl_username'],
            self.request['client_address'],
            self.request['recipient_count'],
            self.request['queue_id'],
            self.request['sender'],
            self.request['recipient'] if 'recipient' in self.request else None, # TODO: Check if self.request.get is better
            self.request['cc_address'] if 'cc_address' in self.request else None,
            self.request['bcc_address'] if 'bcc_address' in self.request else None,
            self.db,
            self.conf,
            self.logger
        )
        message.get_ratelimit()
        message.update_ratelimit()
        blocked = message.is_blocked()
        message.store()

        # Create response
        # actions return to postfix, see http://www.postfix.org/access.5.html for a list of actions.
        if blocked:
            self.logger.warning('handler.py - Message from %s blocked', message.sender) # TODO: More information (msgid, recipient_count, sender, from_addr, sender_ip, etc.)
            action_text_blocked = self.conf.get('ACTION_TEXT_BLOCKED', 'Rate limit reached, retry later')
            data = 'action=DEFER_IF_PERMIT {}\n\n'.format(action_text_blocked)
        else:
            self.logger.info('handler.py - Message from %s accepted', message.sender) # TODO: More information (msgid, recipient_count, sender, from_addr, sender_ip, etc.)
            data = 'action=OK\n\n'

        # Send response
        self.logger.debug('handler.py - Sending data: %s', data)
        self.conn.send(data.encode('utf-8'))

        # Close connection
        self.conn.close()
