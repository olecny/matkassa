#!/bin/bash
# Install the Matkassa helper (ingest/helper.py) as a launchd agent for the current macOS user, so the app's
# "Koble til REMA" button (Mer → Kjeder) can reach this Mac. It listens on 127.0.0.1:47321 only.
#   ingest/launchd/install-helper.sh             # install + start, then show the pairing code to paste in the app
#   ingest/launchd/install-helper.sh --dry-run   # only write and check the plist (MATKASSA_HELPER_PLIST=path), no launchctl
# Re-run after moving the folder or installing python3/rema somewhere else (the PATH is fixed at install).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/../.." && pwd)"
LABEL="no.matkassa.helper"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
DEST="${MATKASSA_HELPER_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}"
DOMAIN="gui/$(id -u)"

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "Fant ikke python3 i PATH." >&2; exit 1; }
# launchd starts jobs with a minimal PATH; sync.sh needs python3, git, curl (and brotli, rema if installed).
path=""
for c in python3 git curl brotli rema; do
  p="$(command -v "$c" 2>/dev/null || true)"
  [ -n "$p" ] && path="$path:$(dirname "$p")"
done
PATH_FOR_JOB="$(printf '%s' "${path#:}:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" | tr ':' '\n' | awk 'NF && !seen[$0]++' | paste -sd: -)"

mkdir -p "$APP/ingest/logs" "$(dirname "$DEST")"
/usr/bin/python3 -I - "$HERE/matkassa-helper.plist.template" "$DEST" "$LABEL" "$APP" "$PY" "$PATH_FOR_JOB" <<'PY'
import sys
from xml.sax.saxutils import escape
src, dest, label, app, py, path = sys.argv[1:]
t = open(src, encoding="utf-8").read()
for k, v in {"__LABEL__": label, "__APP_DIR__": app, "__PYTHON__": py, "__PATH__": path}.items():
    t = t.replace(k, escape(v))
open(dest, "w", encoding="utf-8").write(t)
PY
plutil -lint -s "$DEST"
if [ "$DRY" = 1 ]; then echo "Skrev $DEST (dry run, ikke startet)."; exit 0; fi

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DEST"
launchctl enable "$DOMAIN/$LABEL"
echo "Installert: $DEST"
echo "Hjelperen kjører nå på http://127.0.0.1:47321 (bare denne Mac-en). Logg: ingest/logs/helper.log"
echo
command -v rema >/dev/null 2>&1 || [ -x "$HOME/.local/bin/rema" ] || echo "Merk: rema1000-cli (rema) er ikke installert ennå. Se ingest/README.md." >&2
"$PY" -I "$APP/ingest/helper.py" pair
