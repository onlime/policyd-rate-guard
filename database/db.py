from importlib import import_module
import sys

def connect_database(conf):
    driver = conf.get('DB_DRIVER', 'pymysql')
    backend = import_module(driver)

    return getattr(sys.modules[__name__], 'connect_%s' % driver)(conf, backend)


def connect_pymysql(conf, backend):
    return backend.connect(
        host=conf.get('DB_HOST', 'localhost'),
        port=int(conf.get('DB_PORT', 3306)),
        user=conf.get('DB_USER', 'root'),
        password=conf.get('DB_PASSWORD', ''),
        database=conf.get('DB_DATABASE', 'test'),
    )

def connect_sqlite3(conf, backend):
    return backend.connect(conf.get('DB_DATABASE', ':memory:'))
