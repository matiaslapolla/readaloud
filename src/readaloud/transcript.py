"""Find assistant text in Claude Code transcripts (ports the prototype's jq logic).

Transcripts are JSONL at ~/.claude-personal/projects/<enc>/<uuid>.jsonl (and the
~/.claude variant), where <enc> is the cwd with non-alphanumerics → '-'. The live
file is written concurrently, so the trailing line can be partial — we parse
line-by-line and skip bad lines. Assistant text = message.content[] where
type=="text", joined.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOTS = [
    Path.home() / ".claude-personal" / "projects",
    Path.home() / ".claude" / "projects",
]


def encode_cwd(cwd: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def _iter_objects(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # partial trailing line on the live file
    except OSError:
        return


def _assistant_text(obj: dict) -> str | None:
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return None
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, list):
        parts = [
            c.get("text", "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        text = "\n".join(p for p in parts if p)
    elif isinstance(content, str):
        text = content
    else:
        return None
    text = text.strip()
    return text or None


def candidate_transcripts(cwd: str) -> list[Path]:
    """This project's transcripts newest-first; fall back to all projects."""
    enc = encode_cwd(cwd)
    proj: list[Path] = []
    for root in ROOTS:
        d = root / enc
        if d.is_dir():
            proj.extend(d.glob("*.jsonl"))
    if proj:
        proj.sort(key=_mtime, reverse=True)
        return proj
    everything: list[Path] = []
    for root in ROOTS:
        if root.is_dir():
            everything.extend(root.glob("*/*.jsonl"))
    everything.sort(key=_mtime, reverse=True)
    return everything


def last_assistant_text(cwd: str, max_tries: int = 8) -> tuple[str | None, str]:
    """Walk candidates newest-first; return the first that yields assistant text.

    (The newest file by mtime can be a just-started/tool-only session with none.)
    """
    for i, cand in enumerate(candidate_transcripts(cwd)):
        if i >= max_tries:
            break
        last = None
        for obj in _iter_objects(cand):
            t = _assistant_text(obj)
            if t:
                last = t
        if last:
            return last, "last response"
    return None, "last response"


def newest_transcript() -> Path | None:
    """The globally most-recently-modified transcript (the active session)."""
    newest: Path | None = None
    best = -1.0
    for root in ROOTS:
        if not root.is_dir():
            continue
        for p in root.glob("*/*.jsonl"):
            m = _mtime(p)
            if m > best:
                best, newest = m, p
    return newest


def assistant_messages(path: Path) -> list[tuple[str, str]]:
    """All (uuid, text) assistant text messages in a file, in order."""
    out: list[tuple[str, str]] = []
    for obj in _iter_objects(path):
        t = _assistant_text(obj)
        if t:
            uuid = obj.get("uuid") or f"idx{len(out)}"
            out.append((uuid, t))
    return out


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return -1.0
