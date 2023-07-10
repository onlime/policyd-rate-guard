import unittest
from unittest.mock import MagicMock

from os import environ, path
from socket import socket, AF_INET, AF_INET6, SOCK_STREAM

from run import Server

class TestServer(unittest.TestCase):

    def setUp(self) -> None:
        Server.run = MagicMock(return_value=None)

    def test_init(self) -> None:
        server = Server()
        self.assertIsInstance(server, Server)

    def test_file_socket(self) -> None:
        environ['SOCKET'] = '/tmp/policyd-rate-guard.sock'
        server = Server()
        server.open_socket()
        exists = path.exists('/tmp/policyd-rate-guard.sock')
        server.close_socket()
        self.assertTrue(exists)

    def test_ipv4_socket(self) -> None:
        environ['SOCKET'] = '127.0.0.1,12345'
        server = Server()
        server.open_socket()
        sock = socket(AF_INET, SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', 12345))
        sock.close()
        server.close_socket()
        self.assertEqual(result, 0)

    def test_ipv6_socket(self) -> None:
        environ['SOCKET'] = '::1,12345'
        server = Server()
        server.open_socket()
        sock = socket(AF_INET6, SOCK_STREAM)
        result = sock.connect_ex(('::1', 12345))
        sock.close()
        server.close_socket()
        self.assertEqual(result, 0)
