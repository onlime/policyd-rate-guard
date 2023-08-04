from app.message import Message

class Handler:
    """Handle request"""

    request = {}

    def __init__(self, conn, addr, conf, logger, db):
        self.conn = conn
        self.addr = addr
        self.conf = conf
        self.logger = logger
        self.db = db
        self.handle()

    def handle(self):
        """Handle request"""
        # Read data
        data = self.conn.recv(1024).decode('utf-8')
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
            except ValueError:
                pass

        # Handle message
        message = Message(
            self.request['sasl_username'],
            self.request['client_address'],
            self.request['recipient_count'],
            self.request['queue_id'],
            self.request['sender'],
            self.request['recipient'] if 'recipient' in self.request else None,
            self.request['cc_address'] if 'cc_address' in self.request else None,
            self.request['bcc_address'] if 'bcc_address' in self.request else None,
            self.db,
            self.conf,
            self.logger
        )
        message.get_ratelimit()
        blocked = message.check_if_blocked()
        message.update_ratelimit()
        message.store()

        # Create response
        if blocked:
            self.logger.info('handler.py - Message from %s blocked', message.sender)
            action_text_blocked = self.conf.get('ACTION_TEXT_BLOCKED', 'Rate limit reach, retry later')
            data = 'action=defer_if_permit {}\n\n'.format(action_text_blocked)
        else:
            self.logger.debug('handler.py - Message from %s accepted', message.sender)
            data = 'action=OK\n\n'

        # Send response
        self.logger.debug('handler.py - Sending data: %s', data)
        self.conn.send(data.encode('utf-8'))

        # Close connection
        self.conn.close()
