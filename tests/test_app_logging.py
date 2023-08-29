import unittest

from app.conf import Config

from app.logging import get_logger

class TestAppLogging(unittest.TestCase):

    def test_get_logger(self) -> None:
        conf = Config('.env.test')
        logger = get_logger(conf)
        self.assertEqual(logger.level, 40)
