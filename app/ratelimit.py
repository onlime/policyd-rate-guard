

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
        self.id = id
        self.quota = quota
        self.quota_reset = quota_reset
        self.quota_locked = quota_locked
        self.msg_counter = msg_counter
        self.rcpt_counter = rcpt_counter

        self.db = db
        self.cursor = db.cursor()
        self.conf = conf
        self.logger = logger

    def store(self):
        """Store ratelimit in database"""
        if self.id is not None:
            self.update()
        else:
            self.store_new()

    def store_new(self):
        """Store new ratelimit in database"""
        self.logger.debug('Storing ratelimit')
        self.cursor.execute(
            'INSERT INTO ratelimits (sender, quota, quota_reset, quota_locked, msg_counter, rcpt_counter) VALUES (%s, %s, %s, %s, %s, %s)',
            (
                self.sender,
                self.quota,
                self.quota_reset,
                self.quota_locked,
                self.msg_counter,
                self.rcpt_counter
            )
        )
        self.id = self.cursor.lastrowid
        self.db.commit()

    def update(self):
        """Update ratelimit in database"""
        self.logger.debug('Updating ratelimit')
        self.cursor.execute(
            'UPDATE ratelimits SET quota = %s, msg_counter = %s, rcpt_counter = %s WHERE id = %s',
            (
                self.quota,
                self.msg_counter,
                self.rcpt_counter,
                self.id
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
        self.logger.debug('Adding recipients to ratelimit: %i', count)
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
        cursor = db.cursor()
        logger.debug('Getting ratelimit for sender %s', sender)
        cursor.execute(
            'SELECT * FROM ratelimits WHERE sender = %s',
            (sender,)
        )
        ratelimit = cursor.fetchone()
        if ratelimit is None:
            logger.debug('No ratelimit found for sender %s', sender)
            return Ratelimit(sender, conf=conf, db=db, logger=logger)
        logger.debug('Ratelimit found: %s', ratelimit)
        return Ratelimit(
            ratelimit[1],
            ratelimit[0],
            ratelimit[2],
            ratelimit[3],
            ratelimit[4],
            ratelimit[5],
            ratelimit[6],
            db=db,
            conf=conf,
            logger=logger
        )
