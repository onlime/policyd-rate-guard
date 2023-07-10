import unittest

from os import environ

from app.conf import Config

class TestConf(unittest.TestCase):

    def setUp(self) -> None:
        self.conf = Config('.env.test')

    def test_get(self) -> None:
        self.assertEqual(self.conf.get('DB_DRIVER'), 'pymysql')

    def test_get_array(self) -> None:
        self.assertEqual(self.conf.get_array('SOCKET'), ['127.0.0.1', '12526'])
