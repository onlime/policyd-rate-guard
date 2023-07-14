

class Ratelimit:
    def __init__(
        self,
        sender: str,
        id: int = None,
        quota: int = 1000,
        quota_reset: int = 1000,
        quota_locked: bool = False,
        msg_counter: int = 0,
        rcpt_counter: int = 0,
        db: object = None,
        conf: object = None,
        logger: object = None,
    ):
        self.sender = sender
        self.quota = quota
        self.quota_reset = quota_reset
        self.quota_locked = quota_locked
        self.msg_counter = msg_counter
        self.rcpt_counter = rcpt_counter

        self.db = db
        self.conf = conf
        self.logger = logger

    def store(self):
        """Store ratelimit in database"""
        if self.id:
            self.update()
        else:
            self.store_new()

    def store_new(self):
        """Store new ratelimit in database"""
        self.logger.debug('Storing ratelimit')
        self.db.execute(
            'INSERT INTO ratelimits (sender, quota, quota_reset, quota_locked, msg_counter, rcpt_counter) VALUES (?, ?, ?, ?, ?, ?)',
            (
                self.sender,
                self.quota,
                self.quota_reset,
                self.quota_locked,
                self.msg_counter,
                self.rcpt_counter,
            )
        )
        self.id = self.db.lastrowid
        self.db.commit()

    def update(self):
        """Update ratelimit in database"""
        self.logger.debug('Updating ratelimit')
        self.db.execute(
            'UPDATE ratelimits SET quota = ?, msg_counter = ?, rcpt_counter = ? WHERE id = ?',
            (
                self.quota,
                self.quota_reset,
                self.quota_locked,
                self.msg_counter,
                self.rcpt_counter,
                self.id,
            )
        )
        self.db.commit()

    def get_id(self) -> int:
        """Get id of ratelimit"""
        self.logger.debug('Getting id of ratelimit')
        return self.id

    def add_msg(self):
        """Add message to ratelimit"""
        self.logger.debug('Adding message to ratelimit')
        self.msg_counter += 1

    def add_rcpt(self, count: int):
        """Add recipient to ratelimit"""
        self.logger.debug('Adding recipients to ratelimit')
        self.rcpt_counter += count

    def check_over_quota(self) -> bool:
        """Check if ratelimit is over quota"""
        self.logger.debug('Checking if ratelimit is over quota')
        if self.rcpt_counter > self.quota:
            self.logger.debug('Ratelimit is over quota')
            return True
        return False

    @staticmethod
    def find(sender: str, db: object, logger: object, conf: object):
        """Get ratelimit for sender"""
        logger.debug('Getting ratelimit for sender %s', sender)
        ratelimit = db.execute(
            'SELECT * FROM ratelimits WHERE sender = ?',
            (sender,)
        ).fetchone()
        if ratelimit is None:
            logger.debug('No ratelimit found for sender %s', sender)
            return Ratelimit(sender, conf=conf, db=db, logger=logger)
        return Ratelimit(*ratelimit, db=db, conf=conf, logger=logger)
