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
        msg_total: int = 0,
        rcpt_total: int = 0,
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
        self.msg_total = msg_total
        self.rcpt_total = rcpt_total
        self.db = db
        self.cursor = db.cursor()
        self.conf = conf
        self.logger = logger

        self.changed = self.id is None

    def store(self):
        """Store ratelimit in database"""
        if not self.changed:
            self.logger.debug('Ratelimit not changed')
            return
        if self.id is not None:
            self.update()
        else:
            self.store_new()

    def store_new(self):
        """Store new ratelimit in database"""
        self.logger.debug('Storing ratelimit')
        self.cursor.execute(
            '''INSERT INTO `ratelimits` (`sender`, `quota`, `quota_reset`, `quota_locked`, `msg_counter`,
              `rcpt_counter`, `msg_total`, `rcpt_total`)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', (
                self.sender,
                self.quota,
                self.quota_reset,
                self.quota_locked,
                self.msg_counter,
                self.rcpt_counter,
                self.msg_total,
                self.rcpt_total,
            )
        )
        self.id = self.cursor.lastrowid
        self.db.commit()
        self.changed = False

    def update(self):
        """Update ratelimit in database"""
        self.logger.debug('Updating ratelimit')
        self.cursor.execute(
            '''UPDATE `ratelimits` SET `quota` = %s, `msg_counter` = %s, `rcpt_counter` = %s, `msg_total` = %s,
            `rcpt_total` = %s WHERE `id` = %s''', (
                self.quota,
                self.msg_counter,
                self.rcpt_counter,
                self.msg_total,
                self.rcpt_total,
                self.id,
            )
        )
        self.db.commit()
        self.changed = False

    def get_id(self) -> int:
        """Get id of ratelimit"""
        self.logger.debug('Getting id of ratelimit for %s', self.sender)
        return self.id

    def add_msg(self):
        """Add message to ratelimit"""
        self.logger.debug('Adding message to ratelimit for %s', self.sender)
        self.msg_counter += 1
        self.msg_total += 1
        self.changed = True

    def add_rcpt(self, count: int):
        """Add recipient to ratelimit"""
        self.logger.debug('Adding recipients to ratelimit for %s: %i', self.sender, count)
        self.rcpt_counter += count
        self.rcpt_total += count
        self.changed = True

    def check_over_quota(self) -> bool:
        """Check if ratelimit is over quota"""
        self.logger.debug('Checking if ratelimit is over quota for %s', self.sender)
        # rcpt_counter should always be greater than msg_counter, but just in case...
        if self.rcpt_counter > self.quota or self.msg_counter > self.quota:
            self.logger.debug('Ratelimit is over quota for %s', self.sender)
            return True
        return False

    @staticmethod
    def find(sender: str, db: object, logger: object, conf: object) -> object:
        """Get ratelimit for sender"""
        cursor = db.cursor()
        logger.debug('Getting ratelimit for sender %s', sender)
        cursor.execute('SELECT * FROM `ratelimits` WHERE `sender` = %s', (sender, ))
        result = cursor.fetchone()
        if result is None:
            logger.debug('No ratelimit found for sender %s', sender)
            return Ratelimit(sender, conf=conf, db=db, logger=logger)
        logger.debug('Ratelimit found: %s', result)
        return Ratelimit(
            result['sender'],
            result['id'],
            result['quota'],
            result['quota_reset'],
            result['quota_locked'],
            result['msg_counter'],
            result['rcpt_counter'],
            result['msg_total'],
            result['rcpt_total'],
            db,
            conf,
            logger,
        )

    @staticmethod
    def reset_all_counters(db_pool: object, logger: object):
        """Reset all ratelimit counters"""
        logger.debug('Reset all counters')
        db = db_pool.connection()
        try:
            # With DBUtils PooledDB, we need to explicitly start a transaction
            db.begin()
            cursor = db.cursor()
            # reset all counters, but don't change updated_at timestamp
            cursor.execute('UPDATE `ratelimits` SET `msg_counter` = 0, `rcpt_counter` = 0, `updated_at` = `updated_at`')
            # only reset quota if it is not locked
            cursor.execute(
                'UPDATE `ratelimits` SET `quota` = `quota_reset`, `updated_at` = `updated_at` WHERE `quota_locked` = 0'
            )
            db.commit()
        finally:
            db.close()
