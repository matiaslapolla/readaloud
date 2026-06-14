#!/usr/bin/env bash
# read-aloud.sh — speak the last assistant message (or a file) out loud.
#
# Source of text:
#   - No arg: the previous assistant response, pulled from the active session's
#     transcript (newest .jsonl for this project's cwd; falls back across recent
#     sessions until one yields assistant text).
#   - <path> arg: the contents of that file.
#
# Engines (READ_ALOUD_ENGINE: edge | say  — auto-detected, edge preferred):
#   - edge: Microsoft neural voices via `edge-tts` (natural; needs internet),
#           synthesized to an mp3 and played with `afplay`.
#   - say:  macOS built-in `say` (offline; robotic). Used as fallback if edge-tts
#           is missing or fails (e.g. no network).
#   - kokoro: reserved — not wired yet.
#
# Usage:
#   read-aloud.sh             speak the last assistant message
#   read-aloud.sh <path>      speak the contents of a file (markdown is cleaned up)
#   read-aloud.sh stop        stop any in-progress narration
#
# Env overrides:
#   READ_ALOUD_ENGINE     edge | say               (default: edge if available)
#   READ_ALOUD_VOICE      pin a voice for the engine in use
#   READ_ALOUD_RATE       say words-per-minute      (default: 190; say engine only)
#   READ_ALOUD_EDGE_RATE  edge speed, e.g. +10%     (default: +0%; edge engine only)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# ---- Stop: kill every playback path (driver first, so it can't start a new chunk) ----
if [ "${1:-}" = "stop" ]; then
  killed=0
  pkill -f read-aloud-driver.sh 2>/dev/null && killed=1
  pkill -f kokoro_synth.py 2>/dev/null && killed=1
  pkill -f 'edge-tts ' 2>/dev/null && killed=1
  for p in afplay say; do pkill -x "$p" 2>/dev/null && killed=1; done
  rm -rf "${TMPDIR:-/tmp}"/readaloud.* "${TMPDIR:-/tmp}"/readaloud-kokoro.* 2>/dev/null || true
  [ "$killed" = 1 ] && echo "read-aloud: stopped." || echo "read-aloud: nothing playing."
  exit 0
fi

# Sweep stale temp dirs from past runs that were killed mid-flight (>30 min old, so
# never an in-flight run). Cheap insurance against accumulation.
find "${TMPDIR:-/tmp}" -maxdepth 1 -type d -name 'readaloud*' -mmin +30 \
  -exec rm -rf {} + 2>/dev/null || true

# ---- Engine selection ---- (default: kokoro → edge → say)
ENGINE="${READ_ALOUD_ENGINE:-}"
if [ -z "$ENGINE" ]; then
  if command -v uv >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/kokoro_synth.py" ]; then ENGINE=kokoro
  elif command -v edge-tts >/dev/null 2>&1; then ENGINE=edge
  else ENGINE=say; fi
fi

# Curated natural edge-tts voices. The *Multilingual* ones also read ES/PT well.
EDGE_VOICES=(
  en-US-AvaMultilingualNeural
  en-US-AndrewMultilingualNeural
  en-US-EmmaMultilingualNeural
  en-US-BrianMultilingualNeural
  en-US-AriaNeural
  en-US-GuyNeural
  en-US-JennyNeural
)

# Pick a say voice: every installed Enhanced/Premium voice plus a curated set of
# decent standard ones. New voices you download are picked up automatically.
say_voice() {
  [ -n "${READ_ALOUD_VOICE:-}" ] && { printf '%s' "$READ_ALOUD_VOICE"; return; }
  local curated='Samantha|Daniel|Karen|Moira|Tessa|Allison|Ava|Zoe|Tom|Nathan|Susan|Evan|Joelle|Nicky|Aaron'
  local pool=() v
  while IFS= read -r v; do
    [ -n "$v" ] && pool+=("$v")
  done < <(say -v '?' 2>/dev/null | sed -E 's/ {2,}.*//' \
            | grep -iE "\((Enhanced|Premium)\)|^(${curated})$" | sort -u)
  if [ "${#pool[@]}" -gt 0 ]; then printf '%s' "${pool[$((RANDOM % ${#pool[@]}))]}"
  else printf '%s' "Samantha"; fi
}
edge_voice() {
  [ -n "${READ_ALOUD_VOICE:-}" ] && { printf '%s' "$READ_ALOUD_VOICE"; return; }
  printf '%s' "${EDGE_VOICES[$((RANDOM % ${#EDGE_VOICES[@]}))]}"
}

# Kokoro voices (local). a*=American, b*=British, *f_=female, *m_=male. Pin a
# Spanish voice (e.g. ef_dora) via READ_ALOUD_VOICE for Spanish text.
KOKORO_VOICES=( af_heart af_bella af_nicole am_michael am_fenrir bf_emma bm_george )
kokoro_voice() {
  [ -n "${READ_ALOUD_VOICE:-}" ] && { printf '%s' "$READ_ALOUD_VOICE"; return; }
  printf '%s' "${KOKORO_VOICES[$((RANDOM % ${#KOKORO_VOICES[@]}))]}"
}

# ---- Source the text ----
ARG="${1:-}"
if [ -n "$ARG" ]; then
  # File mode
  file="$ARG"
  case "$file" in                       # expand a leading ~ that wasn't shell-expanded
    "~")   file="$HOME" ;;
    "~/"*) file="$HOME/${file#\~/}" ;;
  esac
  [ -f "$file" ] || { echo "read-aloud: file not found: $ARG"; exit 1; }
  [ -r "$file" ] || { echo "read-aloud: cannot read file: $ARG"; exit 1; }
  text=$(cat "$file")
  src_label=$(basename "$file")
else
  # Transcript mode: the previous assistant response
  command -v jq >/dev/null 2>&1 || { echo "read-aloud: jq is required (brew install jq)"; exit 1; }

  # Candidate transcripts for THIS project (cwd), newest first. Claude encodes the
  # cwd into the project dir name by replacing non-alphanumerics with '-'.
  # || true: an unmatched glob makes ls exit non-zero, which pipefail+set -e would
  # otherwise treat as fatal at this assignment.
  enc=$(printf '%s' "$PWD" | sed 's/[^a-zA-Z0-9]/-/g')
  candidates=$(ls -t "$HOME"/.claude-personal/projects/"$enc"/*.jsonl \
                     "$HOME"/.claude/projects/"$enc"/*.jsonl 2>/dev/null) || true
  # Fallback: any project, newest first (e.g. cwd encoding miss).
  [ -z "$candidates" ] && candidates=$(ls -t "$HOME"/.claude-personal/projects/*/*.jsonl \
                                              "$HOME"/.claude/projects/*/*.jsonl 2>/dev/null) || true
  [ -z "$candidates" ] && { echo "read-aloud: no transcript found."; exit 1; }

  # Walk candidates newest-first; use the FIRST that yields assistant text — the
  # newest file by mtime can be a just-started/tool-call-only session with none yet.
  #   - fromjson? // empty: the live transcript is written concurrently, so its
  #     trailing line can be partial JSON; parse line-by-line, skip bad lines.
  #   - `if type=="array"` guards messages whose content is a plain string.
  text=""
  tried=0
  while IFS= read -r cand; do
    [ -n "$cand" ] || continue
    text=$(jq -R 'fromjson? // empty' "$cand" 2>/dev/null | jq -rs '
      [ .[]
        | select(.type == "assistant")
        | ((.message.content // [])
            | if type == "array" then map(select(.type == "text") | .text) | join("\n")
              else tostring end)
        | select(. != "")
      ] | last // ""' 2>/dev/null) || true
    tried=$((tried + 1))
    [ -n "$text" ] && break
    [ "$tried" -ge 8 ] && break
  done <<< "$candidates"
  src_label="last response"
fi

[ -z "$text" ] && { echo "read-aloud: nothing to read (no assistant text found in this project's recent sessions)."; exit 0; }

# ---- Clean up for listening: drop code blocks, strip markdown/tags ----
# NOTE: angle brackets crash macOS `say` (instant exit, no audio), so we strip
# XML/HTML-ish tags and stray < > regardless of engine — also nicer for edge-tts.
spoken=$(printf '%s' "$text" \
  | awk 'BEGIN{c=0} /^```/{c=!c; next} c==0{print}' \
  | sed -E \
      -e 's/`[^`]*`//g' \
      -e 's/<[^>]*>//g' \
      -e 's/\*\*([^*]*)\*\*/\1/g' \
      -e 's/\*([^*]*)\*/\1/g' \
      -e 's/^#+[[:space:]]*//' \
      -e 's/^>[[:space:]]*//' \
      -e 's/\[([^]]*)\]\([^)]*\)/\1/g' \
      -e 's/^[[:space:]]*[-*+][[:space:]]+/, /' \
  | tr -d '<>')
words=$(printf '%s' "$spoken" | wc -w | tr -d ' ')

# ---- Playback (each returns 0 if narration started, non-zero to fall through) ----

speak_say() {  # inline arg, NOT `say -f` (which is silent on some macOS setups)
  local v; v="$(say_voice)"
  pkill -x say 2>/dev/null || true
  nohup say -v "$v" -r "${READ_ALOUD_RATE:-190}" "$spoken" >/dev/null 2>&1 &
  echo "read-aloud: speaking ${src_label} (~${words} words, ${v} via say, ${READ_ALOUD_RATE:-190} wpm). 'stop' to cancel."
}

# Launch a detached streaming driver and wait for its `ok` marker. Args:
#   $1 label  $2 max-wait-ticks (×0.2s)  $3... command to run
# Returns 0 if `ok` appeared (live), 1 if the driver died first (failed).
_run_driver() {
  local label="$1" ticks="$2"; shift 2
  pkill -f read-aloud-driver.sh 2>/dev/null || true
  pkill -f kokoro_synth.py 2>/dev/null || true
  pkill -x afplay 2>/dev/null || true
  nohup "$@" >/dev/null 2>&1 &
  local dpid=$! i
  for ((i=0; i<ticks; i++)); do
    [ -f "$WORK/ok" ] && { echo "read-aloud: ▶ playing ${src_label} (${label}). 'stop' to cancel."; return 0; }
    kill -0 "$dpid" 2>/dev/null || return 1
    sleep 0.2
  done
  echo "read-aloud: ▶ playing ${src_label} (${label}, slow start). 'stop' to cancel."  # assume live
  return 0
}

speak_edge() {
  command -v edge-tts >/dev/null 2>&1 || return 1
  local v; v="$(edge_voice)"
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/readaloud.XXXXXX")
  printf '%s' "$spoken" > "$WORK/text.txt"
  echo "read-aloud: synthesizing ${src_label} (~${words} words, ${v} via edge-tts)…"
  _run_driver "${v}, edge" 50 bash "$SCRIPT_DIR/read-aloud-driver.sh" "$v" "${READ_ALOUD_EDGE_RATE:-+0%}" "$WORK"
}

speak_kokoro() {
  command -v uv >/dev/null 2>&1 || return 1
  local v; v="$(kokoro_voice)"
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/readaloud-kokoro.XXXXXX")
  printf '%s' "$spoken" > "$WORK/text.txt"
  echo "read-aloud: loading Kokoro (local) for ${src_label} (~${words} words, ${v})…"
  _run_driver "${v}, Kokoro local" 150 uv run "$SCRIPT_DIR/kokoro_synth.py" "$v" "$WORK"
}

# Dispatch with graceful fallback: the chosen engine, then the next best, then say.
case "$ENGINE" in
  kokoro) speak_kokoro || { echo "read-aloud: Kokoro unavailable — trying edge."; speak_edge || speak_say; } ;;
  edge)   speak_edge   || { echo "read-aloud: edge unavailable — falling back to say."; speak_say; } ;;
  say)    speak_say ;;
  *)      echo "read-aloud: unknown engine '$ENGINE' (use kokoro, edge, or say)."; exit 1 ;;
esac
