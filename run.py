import os
import sentry_sdk
import socket
import threading
from app.conf import Config
from app.handler import Handler
from app.logging import get_logger
from database.db import connect_database

class Daemon:

    def __init__(self) -> None:
        self.conf = Config()
        self.logger = get_logger(self.conf)
        self.db = connect_database(self.conf)
        # TODO: Improve socket configuration parsing
        self.socket_conf = self.conf.get_array('SOCKET', '127.0.0.1,10033')
        self.init_sentry()
        self.run()

    def init_sentry(self) -> None:
        sentry_dsn = self.conf.get('SENTRY_DSN')
        if sentry_dsn:
            sentry_sdk.init(
                dsn=sentry_dsn,
                environment=self.conf.get('SENTRY_ENVIRONMENT', 'dev'),
            )
            # In addition to (auto-detected) server_name, provide FQDN as tag
            sentry_sdk.set_tag('fqdn', socket.getfqdn())

    def run(self) -> None:
        """Run server"""
        self.open_socket()
        while True:
            try:
                conn, addr = self.socket.accept()
                threading.Thread(
                    target=Handler,
                    args=(conn, addr, self.conf, self.logger, self.db)
                ).start()
            except KeyboardInterrupt:
                break
        self.close_socket()

    def open_socket(self) -> None:
        """Open socket for communications"""
        socket_conf = self.socket_conf
        if len(socket_conf) == 1:
            # TODO: Create socket directory if it does not exist
            try:
                os.remove(socket_conf[0])
            except OSError:
                if os.path.exists(socket_conf[0]): # pragma: no cover
                    raise
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.bind(socket_conf[0])
            os.chmod(socket_conf[0], 0o666)
        elif ':' in socket_conf[0]:
            self.socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            self.socket.bind((socket_conf[0], int(socket_conf[1])))
        elif '.' in socket_conf[0]:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.bind((socket_conf[0], int(socket_conf[1])))
        else:
            raise ValueError('Invalid socket configuration')
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.listen(5)

    def close_socket(self) -> None:
        """Close socket"""
        self.socket.close()
        socket_conf = self.socket_conf
        if len(socket_conf) == 1:
            try:
                os.remove(socket_conf[0])
            except OSError as error:
                self.logger.error('run.py - Error removing socket file: %s', error)

if __name__ == '__main__': # pragma: no cover
    Daemon()
