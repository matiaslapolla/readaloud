# readaloud — Handoff / Context

Context dump for the session that will design and build the TUI. Read this first.

## 1. Goal

Turn the working `readaloud` shell prototype into a **full TUI app**: a richer,
interactive terminal experience for reading Claude Code responses (and files) aloud
with natural neural voices. Architecture/stack is **open and to be discussed** — do not
assume one yet.

## 2. What exists today (the prototype in `reference/`)

Four files, currently also installed as a Claude Code skill at
`~/.claude/skills/read-aloud/`:

- `read-aloud.sh` — entrypoint. Resolves source text, sanitizes it, picks engine+voice,
  dispatches playback with a fallback chain. Subcommands: `<none>` (last response),
  `<path>` (file), `stop`.
- `read-aloud-driver.sh` — edge-tts streaming player (chunk → afplay while synth next).
- `kokoro_synth.py` — Kokoro streaming player (PEP 723 inline deps, run via `uv run`;
  loads model once, threaded afplay queue with backpressure).
- `SKILL.md` — the skill manifest / usage.

Invoked in a real terminal via zsh aliases `readaloud` / `ra` (in `~/.zshrc`). It must
run in the user's terminal, NOT inside the Claude Code harness (see gotchas).

### Source-of-text logic
- **No arg:** read the active session's transcript. Transcripts live at
  `~/.claude-personal/projects/<enc>/<uuid>.jsonl` (and `~/.claude/projects/...`), where
  `<enc>` = cwd with non-alphanumerics → `-`. Walk candidates **newest-first** and use
  the first whose **last assistant message has text** (newest file by mtime can be a
  just-started/tool-only session with none yet). Assistant text = `.message.content[]`
  where `.type=="text"`, joined. Parse JSONL line-by-line (`fromjson? // empty`) because
  the live file's trailing line can be partial.
- **`<path>` arg:** read that file (supports `~`, relative paths).

### Engines (env `READ_ALOUD_ENGINE`; default chain kokoro → edge → say)
- **kokoro** (default): local/offline, private. `uv run kokoro_synth.py`. Voices
  `af_heart af_bella af_nicole am_michael am_fenrir bf_emma bm_george` (a=US, b=UK,
  f/m gender; Spanish needs an `ef_*` voice). ~8–13s to first audio (model+libs load
  per run — the main UX wart).
- **edge**: `edge-tts` (MS neural). Voices `en-US-*Neural`, the `*Multilingual` ones
  read ES/PT too. ~2–3s to first audio. Needs internet; text goes to Microsoft.
- **say**: macOS built-in, offline, robotic. Auto-fallback only.

### Shared behavior
- Random voice per run; `READ_ALOUD_VOICE` pins one.
- Speed: `READ_ALOUD_EDGE_RATE=+15%` (edge), `READ_ALOUD_RATE=240` wpm (say).
- Streaming: sentence-aware ~600-char chunks; play chunk N while synthesizing N+1.
- `stop` = `pkill` the driver(s) + afplay/edge-tts/say + sweep temp dirs.
- Temp dirs under `$TMPDIR/readaloud*`; self-clean on normal exit + >30min sweep at start.

## 3. Hard-won gotchas (DO NOT regress these)

These cost a lot to find. Preserve them in any rewrite.

1. **macOS `say -f <file>` produces NO audio** on this Mac (fg or bg); stdin pipe too.
   Only inline `say "text"` works. → pass text as an argument.
2. **Angle brackets `<` `>` crash `say`** (instant exit, no audio). Prompt files full of
   `<context>`/`<task>` tags triggered it. → strip `<[^>]*>` tags + stray `<>` (good for
   all engines anyway).
3. **Backgrounded `say` launched from inside the Claude Code harness gets reaped** when
   the tool call returns → silent. Must run in the user's own shell/terminal. (afplay
   from edge/kokoro is fine because it's a detached child of the terminal.)
4. **edge-tts single-request synth of a long doc ≈ 42s** before any audio. Chunked
   streaming cut time-to-first-audio to ~3s. Same idea applies to kokoro.
5. **Kokoro loads the model per invocation** (~8–13s: torch + spaCy + model). The clean
   fix is a **warm resident daemon** (load once, serve over socket/FIFO → sub-second
   subsequent reads). This is the top candidate feature for the TUI.
6. **BSD `mktemp`** (macOS) needs the `XXXXXX` at the **end** of the template (no
   `.txt` suffix), else it doesn't substitute.
7. **bash 3.2 compatibility** (macOS default `/usr/bin/bash`): no `mapfile`; use
   `$RANDOM`, process substitution, C-style `for ((;;))`.
8. **`@file` mentions in Claude expand to file *contents*, not a path** — when reading a
   file, the literal path must be passed.
9. **`set -euo pipefail` + globbing**: an unmatched glob makes `ls` exit non-zero and
   trips the script; guard assignments with `|| true`.

## 4. Dependencies / environment

- macOS (tested on Tahoe / Darwin 25, Apple Silicon).
- `uv` (`~/.local/bin/uv`) — runs kokoro (PEP723) and installed `edge-tts`
  (`uv tool install edge-tts`).
- `espeak-ng` (brew) — kokoro g2p fallback.
- `jq` — transcript parsing.
- `afplay` (built-in) — plays mp3/wav.
- Kokoro model: `hexgrad/Kokoro-82M`, auto-downloaded to HF cache on first run (~156s
  first time incl. torch/spaCy install; cached after).
- Python 3.13 available.

## 5. Open questions for the design discussion

- **Stack**: Ink (React/TS — fits user's React+TS background), Textual (Python — fits
  the kokoro engine, same process can host the model daemon), ratatui (Rust), or
  bubbletea (Go)? Trade-offs around the warm Kokoro daemon matter here.
- **Warm Kokoro daemon**: how to load once and stay resident (autostart? lifecycle?
  socket protocol?). This is the biggest latency win.
- **Features to scope**: live playback queue + now-playing, pause/resume/scrub, voice &
  engine picker, history of past reads (re-listen), settings persistence, maybe a
  "watch the active session and offer to read each new response" mode.
- **Relationship to the skill**: does the TUI replace the `readaloud` alias + skill, or
  sit alongside? Keep the proven scripts as the engine layer, or reimplement?
- **Privacy posture**: default kokoro (local) vs edge (sends text to MS) — surface this
  clearly in the UI.

## 6. Pointers

- Working scripts: `reference/`.
- User's global conventions: `~/.claude-personal/CLAUDE.md` (Next.js/TS/Vercel stack,
  reuse-before-invent, thin slices, context7 for library docs).
- Memory note: `read-aloud-skill` in the personal memory index.
