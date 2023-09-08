import unittest
from app.message import Message
from app.conf import Config
from app.db import DbConnectionPool
from app.logging import get_logger

class TestMessage(unittest.TestCase):

    def setUp(self) -> None:
        self.conf = Config('.env.test')
        self.logger = get_logger(self.conf)
        self.db = DbConnectionPool(self.conf).connection()
        self.message = Message(
            'TEST1234567',
            'test@example.com',
            '172.19.0.2',
            'unknown',
            3,
            'test@example.com',
            'to_test@example.com',
            db=self.db,
            conf=self.conf,
            logger=self.logger,
        )

    def test_init(self) -> None:
        self.assertEqual(type(self.message).__name__, 'Message')
        self.assertEqual(self.message.sender, 'test@example.com')

    def test_get_ratelimit(self) -> None:
        self.message.get_ratelimit()
        self.assertEqual(type(self.message.ratelimit).__name__, 'Ratelimit')

    def test_update_ratelimit(self) -> None:
        self.message.get_ratelimit()
        rcpt_counter_old = self.message.ratelimit.rcpt_counter
        msg_counter_old = self.message.ratelimit.msg_counter
        self.message.update_ratelimit()
        self.assertEqual(self.message.ratelimit.rcpt_counter, rcpt_counter_old + 3)
        self.assertEqual(self.message.ratelimit.msg_counter, msg_counter_old + 1)

    def test_is_blocked(self) -> None:
        self.message.get_ratelimit()
        self.message.ratelimit.rcpt_counter = 0
        self.message.ratelimit.quota = 1000
        self.message.is_blocked()
        self.assertEqual(self.message.blocked, False)
        
        self.message.ratelimit.rcpt_counter = 1000
        self.message.is_blocked()
        self.assertEqual(self.message.blocked, False)

        self.message.ratelimit.rcpt_counter = 1001
        self.message.is_blocked()
        self.assertEqual(self.message.blocked, True)

    def test_store(self) -> None:
        old_count = self.message.cursor.execute('SELECT * FROM `messages` WHERE `msgid` = %s', ('TEST1234567',))
        self.message.get_ratelimit()
        self.message.is_blocked()
        self.message.store()
        new_count = self.message.cursor.execute('SELECT * FROM `messages` WHERE `msgid` = %s', ('TEST1234567',))
        self.assertEqual(new_count, old_count + 1)

    def test_get_props_description(self) -> None:
        desc = self.message.get_props_description()
        self.assertEqual(desc, 'sender=test@example.com rcpt_count=3 from_addr=test@example.com client_address=172.19.0.2 client_name=unknown')
        desc = self.message.get_props_description(['msgid'])
        self.assertEqual(desc, 'msgid=TEST1234567')
        desc = self.message.get_props_description(['msgid', 'sender', 'rcpt_count'])
        self.assertEqual(desc, 'msgid=TEST1234567 sender=test@example.com rcpt_count=3')
        desc = self.message.get_props_description(['msgid', 'sender', 'rcpt_count'], ', ')
        self.assertEqual(desc, 'msgid=TEST1234567, sender=test@example.com, rcpt_count=3')
