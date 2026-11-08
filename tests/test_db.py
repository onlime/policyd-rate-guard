from policyd_rate_guard.config import DbSettings
from policyd_rate_guard.db import connect_kwargs, session_statements


def test_connect_over_unix_socket_or_tcp() -> None:
    unix = connect_kwargs(DbSettings(unix_socket='/run/mysqld/mysqld.sock', password='secret'))
    assert unix['unix_socket'] == '/run/mysqld/mysqld.sock'
    assert 'host' not in unix
    assert 'port' not in unix
    tcp = connect_kwargs(DbSettings(host='db.example.net', port=3307))
    assert (tcp['host'], tcp['port']) == ('db.example.net', 3307)
    assert 'unix_socket' not in tcp
    for kwargs in (unix, tcp):
        assert kwargs['connect_timeout'] > 0
        assert kwargs['read_timeout'] > 0
        assert kwargs['write_timeout'] > 0
        assert kwargs['autocommit'] is False


def test_session_statements() -> None:
    assert session_statements(DbSettings(lock_wait_timeout=7)) == [
        'SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED',
        'SET SESSION innodb_lock_wait_timeout = 7',
        'SET SESSION lock_wait_timeout = 7',
    ]
