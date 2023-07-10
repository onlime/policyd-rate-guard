
class Handler:
    """Handle request"""

    request = {}

    def __init__(self, conn, addr, conf, logger):
        self.conn = conn
        self.addr = addr
        self.conf = conf
        self.logger = logger
        self.handle()

    def handle(self):
        """Handle request"""
        # Read data
        data = self.conn.recv(1024).decode('utf-8')
        if not data:
            raise Exception('No data received')
        self.logger.debug('Received data: %s', data)
        # Parse data
        for line in data.split("\n"):
            line = line.strip()
            try:
                key, value = line.split(u'=', 1)
                if value:
                    self.logger.debug('Received header: %s=%s', key, value)
                    self.request[key] = value
            except ValueError:
                pass

        self.conn.close()
