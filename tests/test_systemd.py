import fcntl
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

from policyd_rate_guard import systemd


def test_listen_sockets_without_activation() -> None:
    env = {'LISTEN_PID': '1', 'LISTEN_FDS': '1'}  # another process' sockets
    assert systemd.listen_sockets(env) == []
    assert env == {}
    assert systemd.listen_sockets({}) == []
    assert systemd.listen_sockets({'LISTEN_PID': 'x'}) == []


def test_listen_sockets_with_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    first = socket.create_server(('127.0.0.1', 0))
    second = socket.create_server(('127.0.0.1', 0))
    # make the two sockets consecutive (unused) fds, like systemd passes them from fd 3 on
    base = fcntl.fcntl(first.fileno(), fcntl.F_DUPFD, 500)
    with pytest.raises(OSError):
        os.fstat(base + 1)
    os.dup2(second.fileno(), base + 1)
    monkeypatch.setattr(systemd, 'SD_LISTEN_FDS_START', base)
    env = {'LISTEN_PID': str(os.getpid()), 'LISTEN_FDS': '2', 'LISTEN_FDNAMES': 'a:b'}
    sockets = systemd.listen_sockets(env)
    try:
        assert env == {}
        assert [s.getsockname() for s in sockets] == [first.getsockname(), second.getsockname()]
        assert not os.get_inheritable(sockets[0].fileno())
    finally:
        for sock in (*sockets, first, second):
            sock.close()


def test_notify() -> None:
    directory = Path(tempfile.mkdtemp(prefix='prg-', dir='/tmp'))  # short path for AF_UNIX
    path = directory / 'notify.sock'
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(str(path))
    try:
        assert systemd.notify('READY=1', {'NOTIFY_SOCKET': str(path)})
        assert receiver.recv(64) == b'READY=1'
    finally:
        receiver.close()
        path.unlink()
    assert not systemd.notify('READY=1', {})
    assert not systemd.notify('READY=1', {'NOTIFY_SOCKET': str(path)})
    directory.rmdir()


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='abstract sockets are Linux-only')
def test_notify_abstract_namespace() -> None:
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(f'\0prg-test-{os.getpid()}')
    try:
        assert systemd.notify('READY=1', {'NOTIFY_SOCKET': f'@prg-test-{os.getpid()}'})
        assert receiver.recv(64) == b'READY=1'
    finally:
        receiver.close()
