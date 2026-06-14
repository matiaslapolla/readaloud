# readaloud

A terminal text-to-speech tool that reads your **last Claude Code response** (or any
file) out loud, with natural neural voices — a Textual **TUI** backed by an always-warm
**daemon**, so reads are sub-second with no per-call model load.

## What it does

- Reads the **previous assistant response** from the active session's transcript, or a
  **file** you pass it. Strips markdown/code/tags first.
- Three engines (auto-fallback):
  - **kokoro** (default) — local/offline neural model, private.
  - **edge** — Microsoft neural voices (needs internet, faster start).
  - **say** — macOS built-in (offline, robotic) — last-resort fallback.
- **Streams**: chunks text at sentence boundaries and plays chunk N while synthesizing
  N+1, so long docs start in seconds.
- **Always warm**: a headless daemon loads Kokoro once and serves reads over a Unix
  socket. The first read lazily spawns it (one-time ~8–13s load); every read after is
  sub-second. It idle-exits after ~30 min unused.
- **One audio owner**: the TUI is a thin client of the daemon. Open it to browse/preview
  voices (Voice Lab), watch the now-playing queue, and toggle auto-watch — all reads,
  whether from the TUI, the shell, or the Claude Code skill, flow through the one daemon.

## Install

Requires macOS, [`uv`](https://docs.astral.sh/uv/), and `afplay` (built in). From the
repo root:

```bash
./install.sh
```

This runs `uv sync`, installs the **read-aloud** Claude Code skill (into
`$CLAUDE_CONFIG_DIR` or `~/.claude`), and adds `readaloud` / `ra` shell aliases. It's
idempotent — safe to re-run after pulling. Restart your shell (or `source ~/.zshrc`)
afterwards.

## Usage

```bash
readaloud                 # open the TUI (Voice Lab, reader, auto-watch)
readaloud read            # read your last Claude Code response (warm)
readaloud read ./file.md  # read a file
readaloud stop            # stop playback
readaloud status          # what's playing / queued
readaloud daemon --stop   # stop the background daemon (also --status)
```

In Claude Code, the `/read-aloud` skill narrates the previous assistant message through
the same daemon.

### Voices & speed (cold-path env overrides)

`READ_ALOUD_ENGINE` (kokoro|edge|say), `READ_ALOUD_VOICE` (e.g. `af_heart`,
`en-US-AvaMultilingualNeural`), `READ_ALOUD_EDGE_RATE` (`+15%`), `READ_ALOUD_RATE`
(say wpm). When the TUI/daemon is running, engine/voice/speed come from the Voice Lab
and `config.toml` instead.

## Layout

- `src/readaloud/` — the app: `core` (engine + queue), `daemon` (headless warm owner),
  `client`/`cli` (socket client + `readaloud read|stop|status`), `app` + `screens/`
  (the TUI), `engines/` (kokoro/edge/say), `ipc` (socket protocol).
- `reference/` — the original shell prototype, still the last-ditch cold fallback.
- `skill/SKILL.md.tmpl` — the Claude Code skill manifest `install.sh` renders.
- `docs/HANDOFF.md` — design context and the hard-won macOS/TTS gotchas.

Config lives in `config.toml` (gitignored; `config.example.toml` is the template).
