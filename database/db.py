from importlib import import_module

def connect_database(self, conf):
    driver = conf.get('DB_DRIVER', 'pymysql')
    backend = import_module(driver)

    self.connection = backend.connect(
        host=conf.get('DB_HOST', 'localhost'),
        port=conf.get('DB_PORT', 3306),
        user=conf.get('DB_USER', 'root'),
        password=conf.get('DB_PASSWORD', ''),
        database=conf.get('DB_DATABASE', 'test'),
        cursorclass=backend.cursors.DictCursor
    )
