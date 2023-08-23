from app.conf import Config
from app.logging import get_logger
from database.db import connect_database
from app.ratelimit import Ratelimit

class Cleaner:

    def __init__(self) -> None:
        self.conf = Config()
        self.logger = get_logger(self.conf)
        self.db = connect_database(self.conf)
        self.cleanup()

    def cleanup(self) -> None:
        """Cleanup database"""
        self.logger.debug('cleanup.py - Cleaning up database')
        ratelimits = Ratelimit.get_all(self.db, self.logger, self.conf)

        # TODO: This does not perform well, use a single query instead
        for ratelimit in ratelimits:
            ratelimit.reset_quota()
            ratelimit.reset_counters()
            ratelimit.store()


if __name__ == '__main__': # pragma: no cover
    Cleaner()
