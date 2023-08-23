from importlib import import_module
import sys

def connect_database(conf):
    # TODO: Check if caching makes sense (only if simple possible)
    driver = conf.get('DB_DRIVER', 'pymysql')
    backend = import_module(driver)

    method = 'connect_{}'.format(driver.lower())
    connection, cursor = getattr(sys.modules[__name__], method)(conf, backend)
    return { 'connection': connection, 'cursor': cursor }


def connect_pymysql(conf, backend):
    connection = backend.connect(
        host=conf.get('DB_HOST', 'localhost'),
        port=int(conf.get('DB_PORT', 3306)),
        user=conf.get('DB_USER', 'root'),
        password=conf.get('DB_PASSWORD', ''),
        database=conf.get('DB_DATABASE', 'test'),
    )
    cursor = connection.cursor(backend.cursors.DictCursor)
    return connection, cursor

def connect_sqlite3(conf, backend):
    connection = backend.connect(conf.get('DB_DATABASE', ':memory:'))
    connection.row_factory = backend.Row
    cursor = connection.cursor()
    return connection, cursor
