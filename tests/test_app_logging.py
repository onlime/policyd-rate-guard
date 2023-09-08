import unittest
from app.conf import Config
from app.logging import Logging

class TestAppLogging(unittest.TestCase):

    def test_get_logger(self) -> None:
        conf = Config('.env.test')
        logger = Logging.get_logger(conf)
        self.assertEqual(logger.level, 40)
