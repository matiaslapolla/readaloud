"""Unix-socket server so a quick `readaloud read` from any shell reuses the warm
model in a running core — sub-second instead of an 8-13s cold start.

Hosted by either the headless daemon or the TUI. It talks to a ReadAloudCore
directly: the core's Playlist is thread-safe, so queuing a read happens straight
on the socket thread (no UI-thread hop). If another instance already owns the
socket, start() returns False and the host runs without serving IPC.

`last_activity` (monotonic) is bumped on every handled request so the daemon can
idle-shut-down. A `shutdown` command lets a client stop the daemon cleanly.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

SOCKET_PATH = Path(tempfile.gettempdir()) / "readaloud.sock"


class IPCServer:
    def __init__(self, core, on_shutdown: Callable[[], None] | None = None) -> None:
        self.core = core
        self.on_shutdown = on_shutdown
        self.last_activity = time.monotonic()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> bool:
        if SOCKET_PATH.exists():
            if _ping(SOCKET_PATH):
                return False  # another instance is live
            _unlink(SOCKET_PATH)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(str(SOCKET_PATH))
        except OSError:
            return False
        s.listen(8)
        s.settimeout(0.5)
        self._sock = s
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return True

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    conn.settimeout(2.0)
                    line = _recv_line(conn)
                    resp = self._handle(json.loads(line)) if line else {"ok": False}
                except Exception as e:  # noqa: BLE001 — report, don't crash the server
                    resp = {"ok": False, "error": str(e)}
                try:
                    conn.sendall((json.dumps(resp) + "\n").encode())
                except OSError:
                    pass

    def _handle(self, req: dict) -> dict:
        self.last_activity = time.monotonic()
        cmd = req.get("cmd")
        core = self.core
        if cmd == "status":
            return {"ok": True, **core.status_dict()}
        if cmd == "stop":
            core.stop()
            return {"ok": True}
        if cmd == "shutdown":
            if self.on_shutdown is not None:
                self.on_shutdown()
            return {"ok": True}
        if cmd == "read-last":
            return self._enqueue(core.read_last_job(req.get("cwd") or os.getcwd()))
        if cmd == "read-file":
            return self._enqueue(core.read_file_job(req.get("path", "")))
        if cmd == "read-text":
            return self._enqueue(core.read_text_job(req.get("text", "")))
        if cmd == "preview":
            # Explicit engine+voice from the Voice Lab; barges in over any read.
            job = core._make_job(
                req.get("text", ""), "preview", req.get("engine"), req.get("voice")
            )
            return self._enqueue(job)
        if cmd == "set-autowatch":
            core.set_autowatch(bool(req.get("on")))
            return {"ok": True}
        if cmd == "reload-config":
            core.reload_config()
            return {"ok": True}
        return {"ok": False, "error": f"unknown cmd: {cmd!r}"}

    def _enqueue(self, job) -> dict:
        if job is None:
            return {"ok": False, "error": "nothing to read"}
        self.core.enqueue(job, True)
        return {
            "ok": True,
            "label": job.label,
            "engine": job.engine,
            "voice": job.voice,
            "words": job.words,
        }

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        _unlink(SOCKET_PATH)


def _ping(path: Path) -> bool:
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(0.3)
        c.connect(str(path))
        c.close()
        return True
    except OSError:
        return False


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _recv_line(conn: socket.socket) -> str:
    data = b""
    while not data.endswith(b"\n"):
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    return data.decode("utf-8", errors="replace").strip()
