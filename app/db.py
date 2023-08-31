from importlib import import_module
import sys

def connect_database(conf: object):
    # TODO: Check if caching makes sense (only if simple possible)
    driver = conf.get('DB_DRIVER', 'pymysql')
    backend = import_module(driver)

    method = 'connect_{}'.format(driver.lower())
    return getattr(sys.modules[__name__], method)(conf, backend)


def connect_pymysql(conf: object, backend: object):
    return backend.connect(
        host=conf.get('DB_HOST', 'localhost'),
        user=conf.get('DB_USER', 'policyd-rate-guard'),
        password=conf.get('DB_PASSWORD', ''),
        database=conf.get('DB_DATABASE', 'policyd-rate-guard'),
        port=int(conf.get('DB_PORT', 3306)),
        cursorclass=backend.cursors.DictCursor
    )

def connect_sqlite3(conf: object, backend: object):
    connection = backend.connect(
        database=conf.get('DB_DATABASE', ':memory:'),
    )
    # https://docs.python.org/3/library/sqlite3.html#sqlite3.Row
    connection.row_factory = backend.Row
    return connection
