import unittest
from unittest.mock import patch, Mock
import jwt
from app.webhook import Webhook
from app.message import Message
from app.conf import Config
from app.db import DbConnectionPool
from app.logging import Logging
from app._version import __version__ as app_version

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
        self.message.get_ratelimit()
        self.webhook = Webhook(self.conf, self.logger, self.message)

    # mock the requests.post method
    @patch('requests.post')
    def test_call(self, mock_post) -> None:
        # Create a mock response for the requests.post method
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.webhook.call()

        # Assert that requests.post was called with the expected URL, headers, and JSON data
        expected_url = 'https://example.com/api/policyd/test@example.com?token=34caa5c52fce98bc56fa3bfd8274a92328f09a6e0b27da2b5d89c1b5c5ed05c5'
        expected_headers = {'User-Agent': f'policyd-rate-guard/{app_version}'}
        expected_data = self.webhook.get_data()
        mock_post.assert_called_once_with(expected_url, headers=expected_headers, json=expected_data)


    def test_get_data(self) -> None:
        data = self.webhook.get_data()
        self.assertEqual(type(data).__name__, 'dict')
        self.assertEqual(data['msgid'], 'TEST1234567')
        self.assertEqual(data['sender'], 'test@example.com')
        self.assertEqual(data['quota'], 1000)

    def test_get_simple_token(self) -> None:
        secret = self.conf.get('WEBHOOK_SECRET')
        # hashlib.sha256(f'{secret}test@example.com'.encode('utf-8')).hexdigest()
        token = self.webhook.get_simple_token(secret)
        self.assertEqual(type(token).__name__, 'str')
        self.assertEqual(token, '34caa5c52fce98bc56fa3bfd8274a92328f09a6e0b27da2b5d89c1b5c5ed05c5')

    def test_get_jwt_token(self) -> None:
        secret = self.conf.get('WEBHOOK_SECRET')
        token = self.webhook.get_jwt_token(secret)
        self.assertEqual(type(token).__name__, 'str')
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        self.assertEqual(payload['sub'], 'test@example.com')
