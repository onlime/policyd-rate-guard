import unittest

from app.conf import Config
from app.logging import get_logger
from database.db import connect_database

from app.ratelimit import Ratelimit

class TestRatelimit(unittest.TestCase):

    def setUp(self) -> None:
        self.conf = Config('.env.test')
        self.logger = get_logger(self.conf)
        self.db = connect_database(self.conf)

    def test_find(self) -> None:
        ratelimit = Ratelimit.find('test_nonexistent@example.com', self.db, self.logger, self.conf)
        self.assertEqual(type(ratelimit).__name__, 'Ratelimit')
        self.assertEqual(ratelimit.quota, 1000)
        self.assertEqual(ratelimit.rcpt_counter, 0)

    def test_get_all(self) -> None:
        ratelimits = Ratelimit.get_all(self.db, self.logger, self.conf)
        self.assertEqual(type(ratelimits).__name__, 'list')
        self.assertEqual(type(ratelimits[0]).__name__, 'Ratelimit')

    def test_add_msg(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        msg_counter_old = ratelimit.msg_counter
        ratelimit.add_msg()
        self.assertEqual(ratelimit.msg_counter, msg_counter_old + 1)
        self.assertTrue(ratelimit.changed)

    def test_add_rcpt(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        rcpt_counter_old = ratelimit.rcpt_counter
        ratelimit.add_rcpt(3)
        self.assertEqual(ratelimit.rcpt_counter, rcpt_counter_old + 3)
        self.assertTrue(ratelimit.changed)

    def test_check_over_quota(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        ratelimit.rcpt_counter = 0
        ratelimit.quota = 1000
        over_quota = ratelimit.check_over_quota()
        self.assertFalse(over_quota)

        ratelimit.rcpt_counter = 1000
        over_quota = ratelimit.check_over_quota()
        self.assertTrue(over_quota)

    def test_reset_quota(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        ratelimit.quota_reset = 1234
        ratelimit.quota = 5000
        ratelimit.reset_quota()
        self.assertEqual(ratelimit.quota, ratelimit.quota_reset)
        self.assertTrue(ratelimit.changed)

    def test_reset_counters(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        ratelimit.rcpt_counter = 1000
        ratelimit.msg_counter = 1000
        ratelimit.reset_counters()
        self.assertEqual(ratelimit.rcpt_counter, 0)
        self.assertEqual(ratelimit.msg_counter, 0)
        self.assertTrue(ratelimit.changed)

    def test_store(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        ratelimit.rcpt_counter = 123
        ratelimit.msg_counter = 456
        ratelimit.add_rcpt(3)
        ratelimit.store()
        self.assertFalse(ratelimit.changed)
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        self.assertEqual(ratelimit.rcpt_counter, 126)
        self.assertEqual(ratelimit.msg_counter, 456)
        self.assertFalse(ratelimit.changed)

    def test_get_id(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        id = ratelimit.get_id()
        self.assertEqual(type(id).__name__, 'int')
