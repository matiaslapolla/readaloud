"""Voice Lab — browse voices per engine, preview them, and configure availability.

The first vertical slice and the killer feature: it exercises the resident kokoro
model, the edge/say paths, playback, and the whole config layer. Left pane lists
engines (with a live warming/off/default badge); right pane lists the selected
engine's voices; the editable sample text is what Preview speaks.
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
    ListItem,
    ListView,
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
        ("m", "make_default_engine", "Engine default"),
        ("e", "toggle_engine", "Enable/disable"),
        ("x", "toggle_edge", "Allow edge"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_engine: str = ""
        self.current_voice: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with Vertical(id="engines-pane"):
                yield Label("Engines", classes="pane-title")
                yield ListView(id="engines")
            with Vertical(id="voices-pane"):
                yield Label("Voices", id="voices-title", classes="pane-title")
                yield DataTable(id="voices")
        yield Label("Sample text  (edit, then Preview)", classes="pane-title")
        yield Input(id="sample")
        with Horizontal(id="actions"):
            yield Button("▶ Preview", id="preview", variant="primary")
            yield Button("Set default voice", id="set-voice")
            yield Button("Make default engine", id="make-engine")
            yield Button("Toggle engine", id="toggle-engine")
        yield Static("", id="status")
        yield Footer()

    # ---- setup ----
    def on_mount(self) -> None:
        self.config = self.app.config
        self.current_engine = self.config.default_engine
        if self.current_engine not in self.config.engine_names():
            self.current_engine = self.config.engine_names()[0]

        table = self.query_one("#voices", DataTable)
        table.cursor_type = "row"
        table.add_columns("Voice", "Note", "Default")
        self.query_one("#sample", Input).value = self.config.sample_text

        self._build_engines()
        self._load_voices()
        self._set_status_idle()

    def _build_engines(self) -> None:
        lv = self.query_one("#engines", ListView)
        lv.clear()
        names = self.config.engine_names()
        for name in names:
            lv.append(
                ListItem(
                    Label(self._engine_label_text(name), id=f"engine-label-{name}"),
                    id=f"engine-{name}",
                )
            )
        if self.current_engine in names:
            lv.index = names.index(self.current_engine)

    def _engine_label_text(self, name: str) -> str:
        cfg = self.config.engine(name)
        engine = self.app.engines[name]
        line = f"{name}  ·  {engine.privacy}"
        if name == self.config.default_engine:
            line = "★ " + line
        flags = []
        if not cfg.enabled:
            flags.append("off")
        badge = _BADGE.get(self.app.engine_state(name), "")
        if badge:
            flags.append(badge)
        if flags:
            line += "   (" + ", ".join(flags) + ")"
        return line

    def _load_voices(self) -> None:
        table = self.query_one("#voices", DataTable)
        table.clear()
        engine = self.app.engines[self.current_engine]
        default_voice = self.config.engine(self.current_engine).default_voice
        voices = engine.list_voices()
        first = ""
        for v in voices:
            mark = "★" if v.id == default_voice else ""
            table.add_row(v.label, v.note, mark, key=v.id)
            if not first:
                first = v.id
        self.query_one("#voices-title", Label).update(f"Voices · {self.current_engine}")
        self.current_voice = default_voice or first

    def refresh_engine_states(self) -> None:
        """Update engine badges in place (called when kokoro finishes warming, etc)."""
        for name in self.config.engine_names():
            try:
                label = self.query_one(f"#engine-label-{name}", Label)
            except Exception:
                continue
            label.update(self._engine_label_text(name))

    # ---- events ----
    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if item is None or item.id is None:
            return
        name = item.id.removeprefix("engine-")
        if name and name != self.current_engine:
            self.current_engine = name
            self._load_voices()

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
            case "make-engine":
                self.action_make_default_engine()
            case "toggle-engine":
                self.action_toggle_engine()

    # ---- actions ----
    def action_preview(self) -> None:
        engine_name = self.current_engine
        state = self.app.engine_state(engine_name)
        if state == EngineState.UNAVAILABLE:
            why = " (edge disabled or offline)" if engine_name == "edge" else ""
            self._status(f"⚠ {engine_name} unavailable{why}")
            return
        voice = self.app.resolve_voice(engine_name, self.current_voice)
        if not voice:
            self._status(f"⚠ no voice selected for {engine_name}")
            return
        text = self.query_one("#sample", Input).value.strip() or self.config.sample_text
        # Persist edited sample text so it sticks across runs.
        if text != self.config.sample_text:
            self.config.sample_text = text
            self.app.save_config()
        warming = (
            "  (warming… first audio may lag)"
            if engine_name == "kokoro" and state == EngineState.WARMING
            else ""
        )
        self._status(f"▶ {engine_name} · {voice}{warming}")
        self.app.preview(engine_name, voice, text)

    def action_set_default_voice(self) -> None:
        if not self.current_voice:
            return
        self.config.set_engine_default_voice(self.current_engine, self.current_voice)
        self.app.save_config()
        self._load_voices()
        self._status(f"✓ default {self.current_engine} voice → {self.current_voice}")

    def action_make_default_engine(self) -> None:
        self.config.default_engine = self.current_engine
        self.app.save_config()
        self.refresh_engine_states()
        self._status(f"✓ default engine → {self.current_engine}")

    def action_toggle_engine(self) -> None:
        cfg = self.config.engine(self.current_engine)
        self.config.set_engine_enabled(self.current_engine, not cfg.enabled)
        self.app.save_config()
        self.refresh_engine_states()
        state = "enabled" if not cfg.enabled else "disabled"
        self._status(f"✓ {self.current_engine} {state}")

    def action_toggle_edge(self) -> None:
        self.config.allow_edge = not self.config.allow_edge
        self.app.save_config()
        self.refresh_engine_states()
        posture = "allowed (cloud)" if self.config.allow_edge else "blocked (local only)"
        self._status(f"✓ edge {posture}")

    # ---- status line ----
    def _status(self, msg: str) -> None:
        self.query_one("#status", Static).update(msg)

    def _set_status_idle(self) -> None:
        self._status(
            "Pick engine ↑↓ · voice ↑↓ · Preview (p/enter) · Reader screen (2)."
        )
