"""Voice Lab — browse the kokoro voices, preview them, set the default.

The killer feature and first vertical slice: it exercises the resident kokoro model,
playback, and the config layer. Kokoro is the only engine, so this is a straight
voice browser — pick a voice, preview it against the editable sample text, and make
it the default. The pane title carries kokoro's warming/unavailable badge.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from ..engines.base import EngineState

_BADGE = {
    EngineState.WARMING: "warming…",
    EngineState.UNAVAILABLE: "unavailable",
    EngineState.READY: "",
}


class VoiceLab(Screen):
    BINDINGS = [
        ("p", "preview", "Preview"),
        ("d", "set_default_voice", "Voice default"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_voice: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with Vertical(id="voices-pane"):
                yield Label("Voices", id="voices-title", classes="pane-title")
                yield DataTable(id="voices")
        yield Label("Sample text  (edit, then Preview)", classes="pane-title")
        yield Input(id="sample")
        with Horizontal(id="actions"):
            yield Button("▶ Preview", id="preview", variant="primary")
            yield Button("Set default voice", id="set-voice")
        yield Static("", id="status")
        yield Footer()

    # ---- setup ----
    def on_mount(self) -> None:
        self.config = self.app.config
        table = self.query_one("#voices", DataTable)
        table.cursor_type = "row"
        table.add_columns("Voice", "Note", "Default")
        self.query_one("#sample", Input).value = self.config.sample_text
        self._load_voices()
        self._set_status_idle()

    def _load_voices(self) -> None:
        table = self.query_one("#voices", DataTable)
        table.clear()
        default_voice = self.config.default_voice
        first = ""
        for v in self.app.engine.list_voices():
            mark = "★" if v.id == default_voice else ""
            table.add_row(v.label, v.note, mark, key=v.id)
            if not first:
                first = v.id
        self.current_voice = default_voice or first
        self._update_title()

    def _update_title(self) -> None:
        badge = _BADGE.get(self.app.engine_state(), "")
        suffix = f"  ({badge})" if badge else ""
        self.query_one("#voices-title", Label).update(f"Voices · kokoro{suffix}")

    def refresh_kokoro_state(self) -> None:
        """Refresh the warming/unavailable badge (kokoro finished warming, etc)."""
        try:
            self._update_title()
        except Exception:
            pass

    # ---- events ----
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None and event.row_key.value is not None:
            self.current_voice = event.row_key.value

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key is not None and event.row_key.value is not None:
            self.current_voice = event.row_key.value
        self.action_preview()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_preview()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "preview":
                self.action_preview()
            case "set-voice":
                self.action_set_default_voice()

    # ---- actions ----
    def action_preview(self) -> None:
        state = self.app.engine_state()
        if state == EngineState.UNAVAILABLE:
            self._status("⚠ kokoro unavailable — model failed to load")
            return
        voice = self.app.resolve_voice(self.current_voice)
        if not voice:
            self._status("⚠ no voice selected")
            return
        text = self.query_one("#sample", Input).value.strip() or self.config.sample_text
        # Persist edited sample text so it sticks across runs.
        if text != self.config.sample_text:
            self.config.sample_text = text
            self.app.save_config()
        warming = "  (warming… first audio may lag)" if state == EngineState.WARMING else ""
        self._status(f"▶ kokoro · {voice}{warming}")
        self.app.preview(voice, text)

    def action_set_default_voice(self) -> None:
        if not self.current_voice:
            return
        self.config.default_voice = self.current_voice
        self.app.save_config()
        self._load_voices()
        self._status(f"✓ default voice → {self.current_voice}")

    # ---- status line ----
    def _status(self, msg: str) -> None:
        self.query_one("#status", Static).update(msg)

    def _set_status_idle(self) -> None:
        self._status("Pick a voice ↑↓ · Preview (p/enter) · Set default (d) · Reader (2).")
