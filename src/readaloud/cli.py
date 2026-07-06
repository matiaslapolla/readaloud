"""`readaloud read|stop|status` client — talks to the warm core over the socket.

This is what the `ra` / `readaloud` shell alias and the read-aloud skill call. The
socket is served by whichever core is up: the TUI if it's open, otherwise a headless
daemon. On the first `read` with nothing serving, the client lazily spawns the
daemon (one-time model load, then warm forever). Kokoro is the only engine and a hard
requirement — if the daemon can't come up, reads fail cleanly rather than falling back.
"""
from __future__ import annotations

import itertools
import json
import os
import sys
import time

from .client import ensure_daemon, send

USAGE = (
    "usage: readaloud [read [PATH] [--no-follow] | stop | status | daemon]"
    "   (no args = launch the TUI)"
)


def run_client(argv: list[str]) -> int:
    cmd = argv[0]
    if cmd == "read":
        rest = argv[1:]
        follow = "--no-follow" not in rest and "-q" not in rest
        paths = [a for a in rest if not a.startswith("-")]
        path = paths[0] if paths else None
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
        # Nothing is serving the socket (and, for read, the daemon wouldn't start).
        if cmd == "status":
            print("readaloud: not running.")
            return 0
        if cmd == "stop":
            print("readaloud: nothing playing (daemon not running).")
            return 0
        print("readaloud: couldn't reach or start the daemon — is kokoro installed? try `uv sync`.")
        return 1

    if not resp.get("ok"):
        print(f"readaloud: {resp.get('error', 'failed')}")
        return 1
    if cmd == "read":
        # Follow the read live only for an interactive terminal — piped output
        # (scripts, the read-aloud skill) stays fire-and-forget so nothing blocks.
        if follow and sys.stdout.isatty():
            return _follow(resp)
        print(
            f"readaloud: ▶ {resp.get('label')} "
            f"({resp.get('words')} words, {resp.get('engine')} · {resp.get('voice')}) [warm]"
        )
    elif cmd == "stop":
        print("readaloud: stopped.")
    elif cmd == "status":
        print(json.dumps(resp, indent=2))
    return 0


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_BAR_WIDTH = 22


def _follow(resp: dict) -> int:
    """Poll the daemon and render a live progress bar until this read finishes.

    Progress is tracked at text-chunk granularity, so `chunk/chunks` is honest even
    while later chunks are still being synthesized. Ctrl-C detaches the view; the
    daemon keeps playing (that's the one audio owner) — `readaloud stop` silences it.
    """
    label = resp.get("label", "")
    engine, voice = resp.get("engine", ""), resp.get("voice", "")
    total = int(resp.get("chunks") or 0)
    spin = itertools.cycle(_SPINNER)
    start = time.monotonic()
    seen = False  # have we seen our own read in the now-playing slot yet?
    completed = False  # did it play all the way through (vs. barge-in / daemon loss)?
    try:
        while True:
            elapsed = time.monotonic() - start
            st = send({"cmd": "status"})
            if st is None:
                break  # daemon went away
            playing = st.get("playing")
            if playing and playing.get("label") == label:
                seen = True
                chunk = int(playing.get("chunk") or 0)
                total = int(playing.get("chunks") or total)
                _render(next(spin), label, chunk, total, elapsed, engine, voice)
            elif playing and playing.get("label") != label:
                break  # a different read barged in — stop watching quietly
            elif seen:
                completed = True  # our read left the now-playing slot: finished
                break
            elif elapsed > 6.0:
                break  # never started (empty / already finished) — don't hang
            time.sleep(0.15)
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        print("readaloud: still reading in the background — `readaloud stop` to silence.")
        return 0
    if completed:
        _render_done(label, total, time.monotonic() - start)
    elif seen:
        sys.stdout.write("\n")  # leave the partial bar on its own line, no false ✓
    return 0


def _render(spin: str, label: str, chunk: int, total: int, elapsed: float, engine, voice) -> None:
    frac = chunk / total if total else 0.0
    filled = int(_BAR_WIDTH * frac)
    bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
    line = (
        f"\r{spin} {_trim(label, 22):<22} [{bar}] {int(frac * 100):3d}%  "
        f"{chunk}/{total}  {_clock(elapsed)}  {engine}·{voice}\033[K"
    )
    sys.stdout.write(line)
    sys.stdout.flush()


def _render_done(label: str, total: int, elapsed: float) -> None:
    sys.stdout.write(
        f"\r✓ {_trim(label, 40)}  ({total} chunks · {_clock(elapsed)})\033[K\n"
    )
    sys.stdout.flush()


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _clock(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
