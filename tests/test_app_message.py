import unittest

from app.message import Message

from app.conf import Config
from database.db import connect_database
from app.logging import get_logger

class TestMessage(unittest.TestCase):

    def setUp(self) -> None:
        self.conf = Config('.env.test')
        self.logger = get_logger(self.conf)
        self.db = connect_database(self.conf)
        self.message = Message(
            'test@example.com',
            '127.0.0.127',
            3,
            'test',
            'test@example.com',
            'to_test@example.com',
            'cc_test@example.com',
            'bcc_test@example.com',
            self.db,
            self.conf,
            self.logger,
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
        self.message.cursor.execute('SELECT count(*) as count FROM messages WHERE msgid = %s', ('test',))
        result = self.message.cursor.fetchone()
        old_count = result['count']
        self.message.get_ratelimit()
        self.message.is_blocked()
        self.message.store()
        self.message.cursor.execute('SELECT count(*) as count FROM messages WHERE msgid = %s', ('test',))
        result = self.message.cursor.fetchone()
        self.assertEqual(result['count'], old_count + 1)