from importlib import import_module
from dbutils.pooled_db import PooledDB

class DbConnectionPool:
    def __init__(self, conf: object):
        self.driver = conf.get('DB_DRIVER', 'pymysql').lower()
        self.backend = import_module(self.driver)
        db_config = getattr(self, 'get_dbconfig_' + self.driver)(conf)

        self.pool = PooledDB(
            creator=self.backend, # pymysql or sqlite3
            mincached=int(conf.get('DB_POOL_MINCACHED', 0)),
            maxcached=int(conf.get('DB_POOL_MAXCACHED', 10)),
            maxshared=int(conf.get('DB_POOL_MAXSHARED', 10)),
            maxusage=int(conf.get('DB_POOL_MAXUSAGE', 10000)),
            # maxconnections=int(conf.get('DB_POOL_MAXCONNECTIONS', 20)),
            **db_config
        )
    
    def connection(self):
        connection = self.pool.connection()
        if self.driver == 'sqlite3':
            # https://docs.python.org/3/library/sqlite3.html#sqlite3.Row
            connection.row_factory = self.backend.Row
        return connection


    def get_dbconfig_pymysql(self, conf: object) -> dict:
        return {
            'host': conf.get('DB_HOST', 'localhost'),
            'user': conf.get('DB_USER', 'policyd-rate-guard'),
            'password': conf.get('DB_PASSWORD', ''),
            'database': conf.get('DB_DATABASE', 'policyd-rate-guard'),
            'port': int(conf.get('DB_PORT', 3306)),
            'cursorclass': self.backend.cursors.DictCursor
        }

    def get_dbconfig_sqlite3(self, conf: object) -> dict:
        return {
            'database': conf.get('DB_DATABASE', ':memory:'),
        }
