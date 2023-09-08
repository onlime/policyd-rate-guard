import unittest
from app.conf import Config
from app.logging import Logging
from app.db import DbConnectionPool
from app.ratelimit import Ratelimit


class TestRatelimit(unittest.TestCase):

    def setUp(self) -> None:
        self.conf = Config('.env.test')
        self.logger = Logging.get_logger(self.conf)
        self.db = DbConnectionPool(self.conf).connection()

    def test_find(self) -> None:
        ratelimit = Ratelimit.find('test_nonexistent@example.com', self.db, self.logger, self.conf)
        self.assertEqual(type(ratelimit).__name__, 'Ratelimit')
        self.assertEqual(ratelimit.quota, 1000)
        self.assertEqual(ratelimit.rcpt_counter, 0)

    def test_add_msg(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        msg_counter_old = ratelimit.msg_counter
        msg_total_old = ratelimit.msg_total
        ratelimit.add_msg()
        self.assertEqual(ratelimit.msg_counter, msg_counter_old + 1)
        self.assertEqual(ratelimit.msg_total, msg_total_old + 1)
        self.assertTrue(ratelimit.changed)

    def test_add_rcpt(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        rcpt_counter_old = ratelimit.rcpt_counter
        rcpt_total_old = ratelimit.rcpt_total
        ratelimit.add_rcpt(3)
        self.assertEqual(ratelimit.rcpt_counter, rcpt_counter_old + 3)
        self.assertEqual(ratelimit.rcpt_total, rcpt_total_old + 3)
        self.assertTrue(ratelimit.changed)

    def test_check_over_quota(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        ratelimit.rcpt_counter = 0
        ratelimit.quota = 1000
        over_quota = ratelimit.check_over_quota()
        self.assertFalse(over_quota)

        ratelimit.rcpt_counter = 1000
        over_quota = ratelimit.check_over_quota()
        self.assertFalse(over_quota)

        ratelimit.rcpt_counter = 1001
        over_quota = ratelimit.check_over_quota()
        self.assertTrue(over_quota)

    def test_store(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        ratelimit.msg_counter = 123
        ratelimit.rcpt_counter = 456
        ratelimit.msg_total = 223
        ratelimit.rcpt_total = 556
        ratelimit.add_msg()
        ratelimit.add_rcpt(3)
        ratelimit.store()
        self.assertFalse(ratelimit.changed)
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        self.assertEqual(ratelimit.msg_counter, 124)
        self.assertEqual(ratelimit.rcpt_counter, 459)
        self.assertEqual(ratelimit.msg_total, 224)
        self.assertEqual(ratelimit.rcpt_total, 559)
        self.assertFalse(ratelimit.changed)

    def test_get_id(self) -> None:
        ratelimit = Ratelimit.find('test@example.com', self.db, self.logger, self.conf)
        id = ratelimit.get_id()
        self.assertEqual(type(id).__name__, 'int')
