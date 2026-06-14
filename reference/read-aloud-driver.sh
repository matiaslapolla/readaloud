#!/usr/bin/env bash
# read-aloud-driver.sh — edge-tts streaming player (used by read-aloud.sh).
# Chunks text at sentence boundaries, then plays each chunk while pre-synthesizing
# the next, so audio starts after the FIRST small chunk instead of the whole doc.
#
#   read-aloud-driver.sh <voice> <edge-rate> <workdir>
#     workdir contains text.txt; the driver writes chunk mp3s there and touches:
#       <workdir>/ok    after the first chunk synthesizes successfully
#       (driver simply exits if the first synth fails — caller detects via the
#        process dying without an `ok` marker, and falls back to `say`)
#
# Stopped by: pkill -f read-aloud-driver.sh  (plus pkill afplay / edge-tts).
set -uo pipefail

voice="${1:?voice}"; rate="${2:?rate}"; work="${3:?workdir}"
txt="$work/text.txt"
[ -r "$txt" ] || exit 1
trap 'rm -rf "$work"' EXIT INT TERM

# Chunk into ~600-char pieces, breaking after sentence punctuation where possible.
chunks=()
while IFS= read -r line; do
  [ -n "$line" ] && chunks+=("$line")
done < <(awk -v max=600 '
  { l=$0; gsub(/[[:space:]]+/," ",l); para = para " " l }
  END {
    gsub(/^ +/,"",para)
    while (length(para) > 0) {
      if (length(para) <= max) { print para; break }
      chunk = substr(para,1,max); pos = 0
      for (i=length(chunk); i>1; i--) { c=substr(chunk,i,1); if (c=="."||c=="!"||c=="?") { pos=i; break } }
      if (pos < max/2) pos = max
      print substr(para,1,pos); para = substr(para,pos+1); gsub(/^ +/,"",para)
    }
  }' "$txt")

total=${#chunks[@]}
[ "$total" -eq 0 ] && exit 0

synth() { # $1 index  $2 text  -> returns non-zero if the mp3 is empty/failed
  edge-tts --voice "$voice" --rate="$rate" --text "$2" --write-media "$work/$1.mp3" >/dev/null 2>&1 || true
  [ -s "$work/$1.mp3" ]
}

synth 0 "${chunks[0]}" || exit 1   # first chunk failed (offline?) -> exit, no `ok`
touch "$work/ok"                   # signal the caller that playback is live

i=0
while [ "$i" -lt "$total" ]; do
  nx=$((i + 1))
  spid=""
  if [ "$nx" -lt "$total" ]; then         # pre-synthesize next while this one plays
    ( synth "$nx" "${chunks[$nx]}" ) &
    spid=$!
  fi
  [ -s "$work/$i.mp3" ] && afplay "$work/$i.mp3"
  [ -n "$spid" ] && wait "$spid" 2>/dev/null || true
  i=$nx
done
