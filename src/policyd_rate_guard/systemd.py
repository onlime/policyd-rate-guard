"""Minimal systemd integration without dependencies: socket activation and sd_notify (READY/STOPPING)."""

import os
import socket
from collections.abc import MutableMapping

SD_LISTEN_FDS_START = 3


def listen_sockets(environ: MutableMapping[str, str] | None = None) -> list[socket.socket]:
    """Sockets passed by systemd socket activation (``LISTEN_FDS``), like ``sd_listen_fds(unset=1)``.

    The variables are removed afterwards, so child processes don't take over the sockets.
    """
    env = os.environ if environ is None else environ
    try:
        if int(env.get('LISTEN_PID', '0')) != os.getpid():
            return []
        count = int(env.get('LISTEN_FDS', '0'))
    except ValueError:
        return []
    finally:
        for key in ('LISTEN_PID', 'LISTEN_FDS', 'LISTEN_FDNAMES'):
            env.pop(key, None)
    sockets = []
    for fd in range(SD_LISTEN_FDS_START, SD_LISTEN_FDS_START + count):
        os.set_inheritable(fd, False)
        sockets.append(socket.socket(fileno=fd))
    return sockets


def notify(state: str, environ: MutableMapping[str, str] | None = None) -> bool:
    """Send a state like ``READY=1`` to systemd (``Type=notify``). No-op outside systemd."""
    env = os.environ if environ is None else environ
    address = env.get('NOTIFY_SOCKET')
    if not address:
        return False
    if address.startswith('@'):
        address = '\0' + address[1:]  # abstract namespace
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(state.encode())
    except OSError:
        return False
    return True
