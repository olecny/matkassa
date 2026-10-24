#!/bin/bash
# Started by launchd once a week (see install.sh); can also be run by hand. Runs ingest/sync.sh, appends its output
# to ingest/logs/sync.log and writes ingest/logs/last-run.txt (OK/FEIL). A failure also shows a macOS notification.
# Tokens: sync.sh and rema.py never print them, git runs quietly without prompts, and anything token-shaped that
# still reaches the log is masked.
set -uo pipefail
APP="$(cd "$(dirname "$0")/../.." && pwd)"
LOGDIR="$APP/ingest/logs"
LOG="$LOGDIR/sync.log"
STATUS="$LOGDIR/last-run.txt"
mkdir -p "$LOGDIR"

export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never  # never hang on a password prompt in the background
unset GIT_TRACE GIT_TRACE_CURL GIT_CURL_VERBOSE GIT_TRACE_PACKET

mask() { sed -E 's/(github_pat_|ghp_|gho_|ghs_|ghu_)[A-Za-z0-9_]+/\1***/g; s/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+/eyJ***/g; s/AMf-v[A-Za-z0-9_-]+/AMf-v***/g'; }

started="$(date '+%Y-%m-%d %H:%M:%S')"
echo "=== $started start" >> "$LOG"
missing=""
for c in python3 git curl; do command -v "$c" >/dev/null 2>&1 || missing="$missing $c"; done
command -v brotli >/dev/null 2>&1 || python3 -c 'import brotli' 2>/dev/null || echo "Merk: brotli mangler, REMA-tilbud med strekkode hoppes over (brew install brotli)." >> "$LOG"

if [ -n "$missing" ]; then
  echo "Mangler i PATH ($PATH):$missing. Kjør ingest/launchd/install.sh på nytt." >> "$LOG"
  rc=127
  out="Mangler:$missing"
else
  out="$("$APP/ingest/sync.sh" 2>&1 | mask; exit "${PIPESTATUS[0]}")"
  rc=$?
  printf '%s\n' "$out" >> "$LOG"
fi
finished="$(date '+%Y-%m-%d %H:%M:%S')"
last="$(printf '%s\n' "$out" | grep -v '^$' | tail -1)"
echo "=== $finished slutt, kode $rc" >> "$LOG"

if [ "$rc" = 0 ]; then state=OK; else state=FEIL; fi
cat > "$STATUS" <<STATUS
status=$state
startet=$started
ferdig=$finished
kode=$rc
melding=$last
logg=$LOG
STATUS

if [ "$rc" != 0 ]; then
  msg="$(printf '%s' "$last" | tr '"\\' "'/" | cut -c1-180)"
  osascript -e "display notification \"$msg\" with title \"Matkassa: ukentlig synk feilet\" subtitle \"Se ingest/logs/sync.log\"" >/dev/null 2>&1 || true
fi

# Keep the log small: the last 2 000 lines are plenty for a weekly job.
if [ "$(wc -l < "$LOG")" -gt 2000 ]; then tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi
exit "$rc"
