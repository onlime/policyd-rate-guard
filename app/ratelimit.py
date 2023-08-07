

class Ratelimit:
    def __init__(
        self,
        sender: str,
        id: int = None,
        quota: int = None,
        quota_reset: int = None,
        quota_locked: bool = False,
        msg_counter: int = 0,
        rcpt_counter: int = 0,
        db: object = None,
        conf: object = None,
        logger: object = None,
    ):
        self.sender = sender
        self.id = id
        self.quota = quota if quota is not None else int(conf.get('QUOTA', 1000))
        self.quota_reset = quota_reset if quota_reset is not None else int(conf.get('QUOTA', 1000))
        self.quota_locked = quota_locked
        self.msg_counter = msg_counter
        self.rcpt_counter = rcpt_counter

        self.db = db
        self.cursor = db.cursor()
        self.conf = conf
        self.logger = logger

        self.changed = self.id is None


    def store(self):
        """Store ratelimit in database"""
        if not self.changed:
            self.logger.debug('ratelimit.py - Ratelimit not changed')
            return
        if self.id is not None:
            self.update()
        else:
            self.store_new()

    def store_new(self):
        """Store new ratelimit in database"""
        self.logger.debug('ratelimit.py - Storing ratelimit')
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
        self.logger.debug('ratelimit.py - Updating ratelimit')
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
        self.logger.debug('ratelimit.py - Getting id of ratelimit for %s', self.sender)
        return self.id

    def add_msg(self):
        """Add message to ratelimit"""
        self.logger.debug('ratelimit.py - Adding message to ratelimit for %s', self.sender)
        self.msg_counter += 1
        self.changed = True

    def add_rcpt(self, count: int):
        """Add recipient to ratelimit"""
        self.logger.debug('ratelimit.py - Adding recipients to ratelimit for %s: %i', self.sender, count)
        self.rcpt_counter += count
        self.changed = True

    def check_over_quota(self) -> bool:
        """Check if ratelimit is over quota"""
        self.logger.debug('ratelimit.py - Checking if ratelimit is over quota for %s', self.sender)
        if self.rcpt_counter >= self.quota: # TODO: Block if rcpt_counter gets over quota with current mail?
            self.logger.debug('ratelimit.py - Ratelimit is over quota for %s', self.sender)
            return True
        return False
    
    def reset_quota(self):
        """Reset quota"""
        self.logger.debug('ratelimit.py - Resetting quota for %s', self.sender)
        if self.quota != self.quota_reset:
            self.quota = self.quota_reset
            self.changed = True

    def reset_counters(self):
        """Reset counters"""
        self.logger.debug('ratelimit.py - Resetting counters for %s', self.sender)
        self.msg_counter = 0
        self.rcpt_counter = 0
        self.changed = True

    @staticmethod
    def find(sender: str, db: object, logger: object, conf: object):
        """Get ratelimit for sender"""
        cursor = db.cursor()
        logger.debug('ratelimit.py - Getting ratelimit for sender %s', sender)
        cursor.execute(
            'SELECT * FROM ratelimits WHERE sender = %s',
            (sender,)
        )
        ratelimit = cursor.fetchone()
        if ratelimit is None:
            logger.debug('ratelimit.py - No ratelimit found for sender %s', sender)
            return Ratelimit(sender, conf=conf, db=db, logger=logger)
        logger.debug('ratelimit.py - Ratelimit found: %s', ratelimit)
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
    
    @staticmethod
    def get_all(db: object, logger: object, conf: object) -> list:
        cursor = db.cursor()
        cursor.execute('SELECT * from ratelimits')
        results = cursor.fetchall()
        ratelimits = []
        for result in results:
            ratelimit = Ratelimit(
                result[1],
                result[0],
                result[2],
                result[3],
                result[4],
                result[5],
                result[6],
                db=db,
                conf=conf,
                logger=logger
            )
            ratelimits.append(ratelimit)
        logger.debug('ratelimit.py - Found %i ratelimits', len(ratelimits))
        return ratelimits
