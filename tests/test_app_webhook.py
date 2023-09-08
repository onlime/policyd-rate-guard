import unittest
from app.webhook import Webhook
from app.message import Message
from app.conf import Config
from app.db import DbConnectionPool
from app.logging import Logging

class TestWebhook(unittest.TestCase):

    def setUp(self) -> None:
        self.conf = Config('.env.test')
        self.logger = Logging.get_logger(self.conf)
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
        self.webhook = Webhook(self.conf, self.logger, self.message)

    def test_get_simple_token(self) -> None:
        secret = self.conf.get('WEBHOOK_SECRET')
        # hashlib.sha256(f'{secret}test@example.com'.encode('utf-8')).hexdigest()
        token = self.webhook.get_simple_token(secret)
        self.assertEqual(token, '34caa5c52fce98bc56fa3bfd8274a92328f09a6e0b27da2b5d89c1b5c5ed05c5')
