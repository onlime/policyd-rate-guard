from app.conf import Config
from app.logging import get_logger
from app.db import DbConnectionPool
from app.ratelimit import Ratelimit
from app.message import Message

class Cleaner:

    def __init__(self, conf: object = None) -> None:
        self.conf = conf or Config()
        self.logger = get_logger(self.conf)
        self.db_pool = DbConnectionPool(self.conf)
        self.logger.debug('Cleaning up database')
        self.reset_counters()
        self.cleanup()

    def reset_counters(self) -> None:
        """Reset counters"""
        Ratelimit.reset_all_counters(self.db_pool, self.logger)

    def cleanup(self) -> None:
        """Cleanup database"""
        message_retention = int(self.conf.get('MESSAGE_RETENTION', 0))
        if message_retention > 0:
            Message.purge_old_messages(self.db_pool, self.logger, message_retention)

if __name__ == '__main__': # pragma: no cover
    Cleaner()
