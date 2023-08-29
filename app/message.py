from app.ratelimit import Ratelimit

class Message:

    def __init__(
        self,
        msgid: str,
        sender: str,
        client_address: str,
        client_name: str,
        rcpt_count: int,
        from_addr: str = None,
        to_addr: str = None,
        cc_addr: str = None,
        bcc_addr: str = None,
        db: object = None,
        conf: object = None,
        logger: object = None,
    ) -> None:
        self.msgid = msgid
        self.sender = sender
        self.client_address = client_address
        self.client_name = client_name
        self.rcpt_count = rcpt_count
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.cc_addr = cc_addr
        self.bcc_addr = bcc_addr
        self.db = db
        self.cursor = db.cursor()
        self.conf = conf
        self.logger = logger

    def store(self):
        """Store message in database"""
        self.logger.debug('message.py - Storing message')
        self.cursor.execute(
            'INSERT INTO `messages` (`ratelimit_id`, `msgid`, `sender`, `rcpt_count`, `blocked`, `from_addr`, `to_addr`, `cc_addr`, `bcc_addr`, `client_address`, `client_name`) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (
                self.ratelimit.get_id(),
                self.msgid,
                self.sender,
                self.rcpt_count,
                self.blocked,
                self.from_addr,
                self.to_addr,
                self.cc_addr,
                self.bcc_addr,
                self.client_address,
                self.client_name,
            )
        )
        self.db.commit()

    def get_ratelimit(self) -> None:
        """Get ratelimit for sender"""
        self.logger.debug('message.py - Getting ratelimit for sender {}'.format(self.sender))
        self.ratelimit = Ratelimit.find(self.sender, self.db, self.logger, self.conf)
    
    def update_ratelimit(self) -> None:
        """Update ratelimit for sender"""
        self.logger.debug('message.py - Updating ratelimit counters for sender {}'.format(self.sender))
        self.ratelimit.add_msg()
        self.ratelimit.add_rcpt(int(self.rcpt_count))
        self.ratelimit.store()

    def is_blocked(self) -> bool:
        """Check if sender is blocked"""
        self.logger.debug('message.py - Checking if sender {} is blocked'.format(self.sender))
        if self.ratelimit.check_over_quota():
            self.logger.debug('message.py - Sender {} is blocked'.format(self.sender))
            self.blocked = True
            return True
        self.blocked = False
        return False

    def get_props_description(self, props: list = ['msgid', 'sender', 'rcpt_count', 'from_addr', 'client_address', 'client_name'], separator: str = ' '):
        return separator.join(f"{name}={getattr(self, name)}" for name in props)
