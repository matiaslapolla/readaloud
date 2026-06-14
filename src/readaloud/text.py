"""Text preparation for speech: clean markdown/tags, chunk for streaming.

Ports the proven sanitization from the shell prototype (read-aloud.sh) and the
chunking from kokoro_synth.py. Gotcha #2 is load-bearing: angle brackets crash
macOS `say`, so we strip XML/HTML-ish tags and stray `<`/`>` for *every* engine
(it also reads better on the neural engines).
"""
from __future__ import annotations

import re

_INLINE_CODE = re.compile(r"`[^`]*`")
_TAG = re.compile(r"<[^>]*>")
_BOLD = re.compile(r"\*\*([^*]*)\*\*")
_ITALIC = re.compile(r"\*([^*]*)\*")
_HEADING = re.compile(r"^#+[ \t]*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^>[ \t]*", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BULLET = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")


def clean_for_speech(text: str) -> str:
    """Strip code blocks, markdown, and tags so the spoken text reads naturally."""
    # Drop fenced code blocks entirely (toggling on each ``` line).
    kept: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            kept.append(line)
    s = "\n".join(kept)

    s = _INLINE_CODE.sub("", s)
    s = _TAG.sub("", s)
    s = _BOLD.sub(r"\1", s)
    s = _ITALIC.sub(r"\1", s)
    s = _HEADING.sub("", s)
    s = _BLOCKQUOTE.sub("", s)
    s = _LINK.sub(r"\1", s)
    s = _BULLET.sub(", ", s)
    # Stray brackets that survived (gotcha #2): drop them regardless of engine.
    s = s.replace("<", "").replace(">", "")
    return s.strip()


def chunk_text(text: str, max_chars: int = 500) -> list[str]:
    """Sentence-aware ~max_chars chunks so each synth call is small and starts fast.

    Streaming the first short chunk is what cuts time-to-first-audio from ~40s to
    a few seconds (gotcha #4) — keep this even with a warm model.
    """
    text = _WS.sub(" ", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    cur = ""
    for part in _SENTENCE_SPLIT.split(text):
        if not part:
            continue
        if cur and len(cur) + len(part) + 1 > max_chars:
            chunks.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def word_count(text: str) -> int:
    return len(text.split())
