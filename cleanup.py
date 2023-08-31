from app.conf import Config
from app.logging import get_logger
from app.db import DbConnectionPool
from app.ratelimit import Ratelimit

class Cleaner:

    def __init__(self, conf: object = None) -> None:
        self.conf = conf or Config()
        self.logger = get_logger(self.conf)
        self.db = DbConnectionPool(self.conf).connection()
        self.cleanup()

    def cleanup(self) -> None:
        """Cleanup database"""
        self.logger.debug('Cleaning up database')
        Ratelimit.reset_all_counters(self.db, self.logger)


if __name__ == '__main__': # pragma: no cover
    Cleaner()
