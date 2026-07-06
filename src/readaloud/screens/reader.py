"""Reader — now-playing, the pending queue, and the auto-watch toggle.

Polls the daemon's status a few times a second to render now-playing + queue (the
TUI is a client; the daemon owns the queue). Auto-watch flips the daemon's session
watcher on/off.
"""
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Static,
    Switch,
)


class Reader(Screen):
    BINDINGS = [
        ("r", "read_last", "Read last"),
        ("w", "toggle_watch", "Auto-watch"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._last_labels: list[str] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="reader-main"):
            yield Label("Now playing", classes="pane-title")
            yield Static("— idle —", id="now")
            with Horizontal(id="watch-row"):
                yield Label("Auto-watch active session", classes="inline-label")
                yield Switch(id="autowatch")
            yield Label("Queue", classes="pane-title")
            yield ListView(id="queue")
        with Horizontal(id="reader-actions"):
            yield Button("▶ Read last response", id="read-last", variant="primary")
            yield Button("⏹ Stop", id="stop")
        yield Static("", id="reader-status")
        yield Footer()

    def on_mount(self) -> None:
        # Reflect the daemon's current auto-watch state (it may already be on from
        # a prior session). Setting .value fires on_switch_changed — that's a no-op
        # re-send, which is fine.
        self.query_one("#autowatch", Switch).value = self.app.autowatch_active()
        self.set_interval(0.3, self._refresh)

    def _refresh(self) -> None:
        now, pending = self.app.now_and_queue()
        self.query_one("#now", Static).update(self._fmt_now(now))
        if pending != self._last_labels:
            self._last_labels = pending
            lv = self.query_one("#queue", ListView)
            lv.clear()
            for label in pending:
                lv.append(ListItem(Label(label)))

    @staticmethod
    def _fmt_now(now) -> str:
        if not now:
            return "— idle —"
        line = (
            f"▶ {now['label']}   ·   {now['engine']} · {now['voice']}"
            f"   ({now['words']} words)"
        )
        if now.get("chunks"):
            line += f"   [{now.get('chunk', 0)}/{now['chunks']}]"
        return line

    # ---- events ----
    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "autowatch":
            self.app.set_autowatch(event.value)
            msg = (
                "Auto-watch ON — new responses in the active session will be read."
                if event.value
                else "Auto-watch off."
            )
            self.query_one("#reader-status", Static).update(msg)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "read-last":
            self.action_read_last()
        elif event.button.id == "stop":
            self.app.action_stop()
            self.query_one("#reader-status", Static).update("Stopped; queue cleared.")

    # ---- actions ----
    def action_read_last(self) -> None:
        resp = self.app.read_last(os.getcwd())
        if resp and resp.get("ok"):
            msg = (
                f"▶ queued {resp['label']} "
                f"({resp['words']} words, {resp['engine']} · {resp['voice']})"
            )
        elif resp is None:
            msg = "daemon unavailable"
        else:
            msg = resp.get("error", "nothing to read in this project's recent sessions")
        self.query_one("#reader-status", Static).update(msg)

    def action_toggle_watch(self) -> None:
        sw = self.query_one("#autowatch", Switch)
        sw.value = not sw.value  # fires on_switch_changed
