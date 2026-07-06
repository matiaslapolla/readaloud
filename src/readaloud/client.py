"""Socket client to a running readaloud core (the daemon, or a TUI hosting one).

Two users:
- the CLI (`readaloud read|stop|status`) — thin one-shot commands.
- the TUI, which runs as a pure client of the daemon so there's a single audio
  owner and one warm model. `DaemonClient` is the typed surface it drives.

`ensure_daemon()` lazily spawns the headless daemon and waits for it to bind, so
the first read/preview after boot warms once and everything after is sub-second.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

from .ipc import SOCKET_PATH


def send(req: dict, timeout: float = 5.0) -> dict | None:
    """One request → one JSON response. None if nothing is serving the socket."""
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(timeout)
        c.connect(str(SOCKET_PATH))
        c.sendall((json.dumps(req) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = c.recv(4096)
            if not chunk:
                break
            data += chunk
        c.close()
        return json.loads(data.decode() or "{}")
    except (OSError, json.JSONDecodeError):
        return None


def ping() -> bool:
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(0.3)
        c.connect(str(SOCKET_PATH))
        c.close()
        return True
    except OSError:
        return False


def ensure_daemon(timeout: float = 8.0) -> bool:
    """Make sure a core is serving the socket; spawn the daemon if not."""
    if ping():
        return True
    try:
        subprocess.Popen(
            [sys.executable, "-m", "readaloud.daemon"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach: outlives the spawning process
        )
    except OSError:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ping():
            return True
        time.sleep(0.1)
    return False


class DaemonClient:
    """Typed wrapper the TUI uses to drive the daemon over the socket."""

    def read_last(self, cwd: str) -> dict | None:
        return send({"cmd": "read-last", "cwd": cwd})

    def read_file(self, path: str) -> dict | None:
        abspath = os.path.abspath(os.path.expanduser(path))
        return send({"cmd": "read-file", "path": abspath})

    def preview(self, voice: str, text: str) -> dict | None:
        return send({"cmd": "preview", "voice": voice, "text": text})

    def stop(self) -> dict | None:
        return send({"cmd": "stop"})

    def status(self) -> dict | None:
        return send({"cmd": "status"})

    def set_autowatch(self, on: bool) -> dict | None:
        return send({"cmd": "set-autowatch", "on": on})

    def reload_config(self) -> dict | None:
        return send({"cmd": "reload-config"})
