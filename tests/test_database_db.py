import unittest

from app.conf import Config

from database.db import connect_database

class TestDatabase(unittest.TestCase):

        def test_sqlite3_connect_database(self) -> None:
            conf = {
                'DB_DRIVER': 'sqlite3',
                'DB_DATABASE': ':memory:'
            }
            conn = connect_database(conf)
            self.assertIsNotNone(conn)
            conn.close()

        def test_pymysql_connect_database(self) -> None:
            conf = Config('.env.test')
            conn = connect_database(conf)
            self.assertIsNotNone(conn)
            conn.close()
