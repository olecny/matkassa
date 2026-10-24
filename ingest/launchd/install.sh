#!/bin/bash
# Install the weekly receipt + REMA-offer sync as a launchd agent for the current macOS user.
#   ingest/launchd/install.sh            # Sunday 20:00 (change with MATKASSA_SYNC_WEEKDAY=0-6 (0 = Sunday), _HOUR, _MINUTE)
#   ingest/launchd/install.sh --run-now  # also run it once right away (launchctl kickstart)
# Re-run after moving the folder or installing python3/git/brotli somewhere else (the PATH is fixed at install).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/../.." && pwd)"
LABEL="no.matkassa.weekly-sync"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
WEEKDAY="${MATKASSA_SYNC_WEEKDAY:-0}"
HOUR="${MATKASSA_SYNC_HOUR:-20}"
MINUTE="${MATKASSA_SYNC_MINUTE:-0}"
DOMAIN="gui/$(id -u)"

[[ "$WEEKDAY" =~ ^[0-7]$ && "$HOUR" =~ ^[0-9]{1,2}$ && "$MINUTE" =~ ^[0-9]{1,2}$ ]] || { echo "Ugyldig tidspunkt." >&2; exit 1; }
grep -qE '^MATKASSA_DATA_REPO=[A-Za-z0-9-]+/[A-Za-z0-9._-]+' "$APP/ingest/.env" 2>/dev/null \
  || { echo "Sett MATKASSA_DATA_REPO=brukernavn/repo i ingest/.env først (se ingest/README.md)." >&2; exit 1; }

# launchd starts jobs with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin); add where python3, git, brotli and gh live.
path=""
for c in python3 git brotli gh curl; do
  p="$(command -v "$c" 2>/dev/null || true)"
  [ -n "$p" ] && path="$path:$(dirname "$p")"
  [ -z "$p" ] && [ "$c" != gh ] && [ "$c" != brotli ] && { echo "Fant ikke $c i PATH." >&2; exit 1; }
done
PATH_FOR_JOB="$(printf '%s' "${path#:}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" | tr ':' '\n' | awk 'NF && !seen[$0]++' | paste -sd: -)"

mkdir -p "$APP/ingest/logs" "$HOME/Library/LaunchAgents"
chmod +x "$HERE/run-sync.sh" "$APP/ingest/sync.sh"
/usr/bin/python3 -I - "$HERE/matkassa-weekly-sync.plist.template" "$DEST" "$LABEL" "$APP" "$WEEKDAY" "$HOUR" "$MINUTE" "$PATH_FOR_JOB" <<'PY'
import sys
from xml.sax.saxutils import escape
src, dest, label, app, wd, h, m, path = sys.argv[1:]
t = open(src, encoding="utf-8").read()
for k, v in {"__LABEL__": label, "__APP_DIR__": app, "__WEEKDAY__": str(int(wd)), "__HOUR__": str(int(h)),
             "__MINUTE__": str(int(m)), "__PATH__": path}.items():
    t = t.replace(k, escape(v))
open(dest, "w", encoding="utf-8").write(t)
PY
plutil -lint -s "$DEST"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DEST"
launchctl enable "$DOMAIN/$LABEL"
days=(søndag mandag tirsdag onsdag torsdag fredag lørdag søndag)
printf 'Installert: %s\nKjører hver %s kl. %02d:%02d. Logg: ingest/logs/sync.log, status: ingest/logs/last-run.txt\n' \
  "$DEST" "${days[$WEEKDAY]}" "$HOUR" "$MINUTE"
if [ "${1:-}" = "--run-now" ]; then
  launchctl kickstart -k "$DOMAIN/$LABEL"
  echo "Startet en kjøring nå. Følg med: tail -f ingest/logs/sync.log"
fi
