"""`readaloud read|stop|status` client — talks to the warm core over the socket.

This is what the `ra` / `readaloud` shell alias and the read-aloud skill call. The
socket is served by whichever core is up: the TUI if it's open, otherwise a headless
daemon. On the first `read` with nothing serving, the client lazily spawns the
daemon (one-time model load, then warm forever). The prototype script remains only
as a last-ditch fallback if the daemon can't come up.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from .client import ensure_daemon, send
from .config import PROJECT_ROOT

FALLBACK_SCRIPT = PROJECT_ROOT / "reference" / "read-aloud.sh"

USAGE = "usage: readaloud [read [PATH] | stop | status | daemon]   (no args = launch the TUI)"


def run_client(argv: list[str]) -> int:
    cmd = argv[0]
    if cmd == "read":
        path = argv[1] if len(argv) > 1 else None
        req = (
            {"cmd": "read-file", "path": os.path.abspath(os.path.expanduser(path))}
            if path
            else {"cmd": "read-last", "cwd": os.getcwd()}
        )
    elif cmd == "stop":
        req = {"cmd": "stop"}
    elif cmd == "status":
        req = {"cmd": "status"}
    else:
        print(USAGE)
        return 2

    resp = send(req)
    if resp is None and cmd == "read":
        # Nothing serving the socket — spin up the warm daemon, then retry.
        if ensure_daemon():
            resp = send(req)
    if resp is None:
        return _fallback(argv)  # daemon unavailable — cold path (or no-op)

    if not resp.get("ok"):
        print(f"readaloud: {resp.get('error', 'failed')}")
        return 1
    if cmd == "read":
        print(
            f"readaloud: ▶ {resp.get('label')} "
            f"({resp.get('words')} words, {resp.get('engine')} · {resp.get('voice')}) [warm]"
        )
    elif cmd == "stop":
        print("readaloud: stopped.")
    elif cmd == "status":
        print(json.dumps(resp, indent=2))
    return 0


def _fallback(argv: list[str]) -> int:
    if not FALLBACK_SCRIPT.exists():
        print("readaloud: no running app and no fallback script found.")
        return 1
    cmd = argv[0]
    args = ["bash", str(FALLBACK_SCRIPT)]
    if cmd == "read" and len(argv) > 1:
        args.append(argv[1])
    elif cmd == "stop":
        args.append("stop")
    elif cmd == "status":
        print("readaloud: not running (no warm app).")
        return 0
    sys.stderr.write("readaloud: app not running — cold start via fallback script.\n")
    return subprocess.call(args)
