import unittest
from app.conf import Config
from app.db import DbConnectionPool


class TestDatabase(unittest.TestCase):

    def test_sqlite3_connection(self) -> None:
        conf = {
            'DB_DRIVER': 'sqlite3',
            'DB_DATABASE': ':memory:'
        }
        db_pool = DbConnectionPool(conf)
        conn = db_pool.connection()
        self.assertIsNotNone(conn)
        conn.close()

    def test_pymysql_connection(self) -> None:
        conf = Config('.env.test')
        db_pool = DbConnectionPool(conf)
        conn = db_pool.connection()
        self.assertIsNotNone(conn)
        conn.close()
