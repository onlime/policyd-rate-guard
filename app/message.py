from app.ratelimit import Ratelimit

class Message:

    def __init__(
        self,
        sender: str,
        sender_ip: str,
        recipient_count: int,
        msgid: str,
        from_addr: str = None,
        to_addr: str = None,
        cc_addr: str = None,
        bcc_addr: str = None,
        db: object = None,
        conf: object = None,
        logger: object = None,
    ) -> None:
        self.sender = sender
        self.sender_ip = sender_ip
        self.rcpt_count = recipient_count
        self.msgid = msgid
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
            'INSERT INTO `messages` (`ratelimit_id`, `sender`, `sender_ip`, `rcpt_count`, `blocked`, `msgid`, `from_addr`, `to_addr`, `cc_addr`, `bcc_addr`) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (
                self.ratelimit.get_id(),
                self.sender,
                self.sender_ip,
                self.rcpt_count,
                self.blocked,
                self.msgid,
                self.from_addr,
                self.to_addr,
                self.cc_addr,
                self.bcc_addr,
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
        self.ratelimit.add_msg() # TODO: Also update counter if the message was blocked?
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
