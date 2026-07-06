"""readaloud Textual app: a thin client of the headless daemon (single audio owner).

The daemon owns the engines, the warm Kokoro model, the reader queue, and auto-watch.
The TUI never plays audio itself — on mount it ensures a daemon is running and then
drives it over the socket (read / preview / stop / auto-watch), polling `status` for
now-playing and the kokoro warm badge. Voice metadata (the picker) is built locally
from a config copy, which is cheap and needs no model; config edits are saved to disk
and the daemon is told to reload so reads stay coherent.

`main()` doubles as the client / daemon entry point: subcommands talk to (or spawn)
a running core instead of booting the TUI.
"""
from __future__ import annotations

import os
import sys

from textual.app import App

from .client import DaemonClient, ensure_daemon
from .config import Config
from .engines import build_engine
from .engines.base import EngineState
from .screens.reader import Reader
from .screens.voice_lab import VoiceLab


class ReadAloudApp(App):
    CSS_PATH = "readaloud.tcss"
    TITLE = "readaloud"

    BINDINGS = [
        ("1", "show_voice_lab", "Voice Lab"),
        ("2", "show_reader", "Reader"),
        ("r", "read_last", "Read last"),
        ("s", "stop", "Stop"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = Config.load()
        # A local engine instance exists only for voice metadata (list_voices /
        # availability) — no model load, no audio. The daemon owns synthesis.
        self.engine = build_engine(self.config)
        self.client = DaemonClient()
        self.voice_lab = VoiceLab()
        self.reader = Reader()
        self._kokoro_state = EngineState.WARMING

    def on_mount(self) -> None:
        self.install_screen(self.voice_lab, name="voicelab")
        self.install_screen(self.reader, name="reader")
        self.push_screen("voicelab")
        if not ensure_daemon():
            self.notify("Could not start the readaloud daemon — audio is unavailable.")
        self.set_interval(1.0, self._poll_daemon)

    def _poll_daemon(self) -> None:
        """Track the daemon's kokoro warm state to update the Voice Lab badge."""
        st = self.client.status()
        if not st or not st.get("ok"):
            return
        try:
            new = EngineState(st.get("kokoro", "warming"))
        except ValueError:
            return
        if new != self._kokoro_state:
            self._kokoro_state = new
            self.voice_lab.refresh_kokoro_state()

    # ---- metadata helpers (local; screens call these) ----
    def engine_state(self) -> EngineState:
        """Daemon truth for kokoro's warm state (unavailable if it can't load)."""
        if not self.engine.available():
            return EngineState.UNAVAILABLE
        return self._kokoro_state

    def resolve_voice(self, voice: str | None) -> str:
        if voice:
            return voice
        if self.config.pinned_voice:
            return self.config.pinned_voice
        return self.config.default_voice

    def save_config(self) -> None:
        """Persist config edits and tell the daemon to pick them up."""
        self.config.save()
        self.client.reload_config()

    # ---- actions forwarded to the daemon (screens call these) ----
    def set_autowatch(self, on: bool) -> None:
        self.client.set_autowatch(on)

    def preview(self, voice: str, text: str):
        return self.client.preview(voice, text)

    def read_last(self, cwd: str, interrupt: bool = True):
        return self.client.read_last(cwd)

    def now_and_queue(self):
        st = self.client.status()
        if not st or not st.get("ok"):
            return None, []
        return st.get("playing"), st.get("queue", [])

    def autowatch_active(self) -> bool:
        st = self.client.status()
        return bool(st and st.get("autowatch"))

    def status_dict(self) -> dict:
        return self.client.status() or {}

    def action_show_voice_lab(self) -> None:
        if self.screen is not self.voice_lab:
            self.switch_screen("voicelab")

    def action_show_reader(self) -> None:
        if self.screen is not self.reader:
            self.switch_screen("reader")

    def action_read_last(self) -> None:
        self.read_last(os.getcwd())

    def action_stop(self) -> None:
        self.client.stop()

    # The daemon is the shared owner — it keeps running (and idle-exits on its own)
    # after the TUI closes, so there's nothing to tear down here.


def main() -> None:
    argv = sys.argv[1:]
    if argv:
        # Any argument means client/daemon mode — never accidentally boot the TUI.
        if argv[0] == "daemon":
            from .daemon import run_daemon

            sys.exit(run_daemon(argv[1:]))

        from .cli import USAGE, run_client

        if argv[0] in {"read", "stop", "status"}:
            sys.exit(run_client(argv))
        print(USAGE)
        sys.exit(2)
    ReadAloudApp().run()


if __name__ == "__main__":
    main()
