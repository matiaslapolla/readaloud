"""Headless always-warm daemon: a ReadAloudCore + IPC socket, no UI.

The point: kill the cold start. The CLI client spawns this lazily on the first
`readaloud read` when nothing is serving the socket; it loads Kokoro once and stays
resident, so that first read pays the one-time ~8-13s model load and every read
after is sub-second. To avoid holding the model's memory forever, it shuts itself
down after a stretch with no requests and nothing playing.

Run modes:
- ``readaloud daemon``         -> run in the foreground (used detached by the client).
- ``readaloud daemon --stop``  -> ask a running daemon to exit cleanly.
- ``readaloud daemon --status``-> print the running daemon's status JSON.
"""
from __future__ import annotations

import json
import os
import signal
import threading
import time

from .core import ReadAloudCore
from .ipc import SOCKET_PATH, IPCServer

# Idle = no IPC request AND nothing playing/queued for this many seconds.
IDLE_TIMEOUT = float(os.environ.get("READALOUD_DAEMON_IDLE", "1800"))  # 30 min
_POLL = 5.0


def run_daemon(argv: list[str] | None = None) -> int:
    argv = argv or []
    if "--stop" in argv:
        return _send_simple("shutdown")
    if "--status" in argv:
        return _send_simple("status", echo=True)

    core = ReadAloudCore()
    core.start()

    stop_event = threading.Event()
    server = IPCServer(core, on_shutdown=stop_event.set)
    if not server.start():
        # Someone else already owns the socket — they're the warm one.
        core.shutdown()
        return 0

    # Warm Kokoro in the background; the socket answers immediately for edge/say,
    # and the first kokoro read blocks on the load (shared lock with this warmup).
    threading.Thread(target=core.warm_kokoro, name="warm", daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop_event.set())

    try:
        while not stop_event.is_set():
            stop_event.wait(_POLL)
            if stop_event.is_set():
                break
            if core.is_busy():
                continue
            if time.monotonic() - server.last_activity > IDLE_TIMEOUT:
                break
    finally:
        server.stop()
        core.shutdown()
    return 0


def _send_simple(cmd: str, echo: bool = False) -> int:
    """Fire a one-shot command at a running daemon; quiet no-op if none is up."""
    import socket

    if not SOCKET_PATH.exists():
        print("readaloud: no daemon running.")
        return 0
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(3.0)
        c.connect(str(SOCKET_PATH))
        c.sendall((json.dumps({"cmd": cmd}) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = c.recv(4096)
            if not chunk:
                break
            data += chunk
        c.close()
    except OSError:
        print("readaloud: no daemon running.")
        return 0
    if echo:
        print(data.decode().strip())
    elif cmd == "shutdown":
        print("readaloud: daemon stopping.")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(run_daemon(sys.argv[1:]))
