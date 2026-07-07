"""User config + curated voice lists, persisted as TOML in the project dir.

Lives next to the code (the project's chosen layout). The live file `config.toml`
is gitignored; `config.example.toml` is committed as a template. Environment
variables (READ_ALOUD_*) still win at runtime so the old alias workflow keeps
behaving identically.
"""
from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

# project root = .../readaloud  (src/readaloud/config.py -> parents[2])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
EXAMPLE_PATH = PROJECT_ROOT / "config.example.toml"

DEFAULTS: dict[str, Any] = {
    "default_voice": "af_heart",
    # a=US, b=UK, e=ES; f/m = female/male. The *_latam ids re-accent the Spanish
    # voices to Latin-American Spanish (seseo + yeísmo) via espeak es-419.
    "voices": [
        "af_heart",
        "af_bella",
        "af_nicole",
        "am_michael",
        "am_fenrir",
        "bf_emma",
        "bm_george",
        "ef_dora_latam",
        "em_alex_latam",
        "em_santa_latam",
    ],
    "sample_text": "The quick brown fox jumps over the lazy dog. "
    "Pack my box with five dozen liquor jugs.",
}

# Config keys from the old multi-engine layout, dropped on load so save() won't
# rewrite them.
_LEGACY_KEYS = ("default_engine", "allow_edge", "edge_rate", "say_rate")


def _migrate_legacy(loaded: dict[str, Any]) -> dict[str, Any]:
    """Lift voice settings out of the old [engines.kokoro] block, drop dead keys.

    Configs written before kokoro became the only engine nested voices under
    `engines.kokoro`; keep the user's customizations by lifting them flat.
    """
    engines = loaded.pop("engines", None)
    if isinstance(engines, dict) and isinstance(engines.get("kokoro"), dict):
        k = engines["kokoro"]
        if k.get("default_voice"):
            loaded.setdefault("default_voice", k["default_voice"])
        if k.get("voices"):
            loaded.setdefault("voices", k["voices"])
    for dead in _LEGACY_KEYS:
        loaded.pop(dead, None)
    return loaded


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """Loaded config with env overrides applied at read time."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    # ---- load / save ----
    @classmethod
    def load(cls) -> "Config":
        data = copy.deepcopy(DEFAULTS)
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("rb") as fh:
                loaded = _migrate_legacy(tomllib.load(fh))
            data = _deep_merge(data, loaded)
        return cls(data)

    def save(self) -> None:
        with CONFIG_PATH.open("wb") as fh:
            tomli_w.dump(self._data, fh)

    # ---- accessors (env overrides win) ----
    @property
    def sample_text(self) -> str:
        return self._data["sample_text"]

    @sample_text.setter
    def sample_text(self, value: str) -> None:
        self._data["sample_text"] = value

    @property
    def pinned_voice(self) -> str | None:
        """READ_ALOUD_VOICE pins the voice at runtime (shell-alias parity)."""
        return os.environ.get("READ_ALOUD_VOICE") or None

    # ---- kokoro voices ----
    @property
    def default_voice(self) -> str:
        return self._data["default_voice"]

    @default_voice.setter
    def default_voice(self, value: str) -> None:
        self._data["default_voice"] = value

    @property
    def voices(self) -> list[str]:
        return list(self._data["voices"])

    def set_voices(self, voices: list[str]) -> None:
        self._data["voices"] = list(voices)

    def raw(self) -> dict[str, Any]:
        return self._data
