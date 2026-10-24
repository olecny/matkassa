#!/bin/bash
# Fetch YOUR receipts (REMA 1000 and/or Trumf) on your Mac and deliver them to where the app reads them:
#   * your Matkassa account (Supabase), if you ran `python3 ingest/cloud.py login`   ← no GitHub key needed
#   * and/or your PRIVATE GitHub data repo (Mer → Synk fra Mac), if MATKASSA_DATA_REPO is set (the older path).
# Each source is optional and only used if you logged in to it yourself:
#   REMA:  rema1000-cli (`rema auth login`)            Trumf: `node ingest/trumf-login.mjs`
# A source that fails (e.g. an expired login) is reported, the others still run. See ingest/README.md.
# Usage: ingest/sync.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${MATKASSA_ENV_FILE:-ingest/.env}"  # tests point this at /dev/null
if [ -z "${MATKASSA_DATA_REPO:-}" ] && [ -f "$ENV_FILE" ]; then
  MATKASSA_DATA_REPO="$(grep -E '^MATKASSA_DATA_REPO=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')"
fi
REPO="${MATKASSA_DATA_REPO:-}"
CLOUD_SESSION="${MATKASSA_CLOUD_SESSION:-$HOME/.matkassa/supabase_session.json}"
TRUMF_STATE="${MATKASSA_TRUMF_STATE:-$HOME/.matkassa/trumf_state.json}"

use_cloud=0; [ -f "$CLOUD_SESSION" ] && use_cloud=1
use_repo=0; [ -n "$REPO" ] && use_repo=1
if [ "$use_cloud" = 0 ] && [ "$use_repo" = 0 ]; then
  echo "Ingen mottaker: logg inn med 'python3 ingest/cloud.py login' (Matkassa-konto) eller sett MATKASSA_DATA_REPO=brukernavn/repo i ingest/.env." >&2
  exit 1
fi
if [ "$use_repo" = 1 ] && ! [[ "$REPO" =~ ^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$ ]]; then
  echo "MATKASSA_DATA_REPO må være brukernavn/repo (ditt PRIVATE repo)." >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
failed=""
got=0

# ---- sources ----
if [ -f "$HOME/.rema1000/tokens.json" ] || grep -qs '^REMA_FIREBASE_REFRESH_TOKEN=' "$ENV_FILE"; then
  if python3 ingest/rema.py --out "$WORK/rema.json"; then got=$((got + 1)); else failed="$failed REMA"; fi
fi
if [ -f "$TRUMF_STATE" ]; then
  rc=0
  python3 ingest/trumf.py --out "$WORK/trumf.json" || rc=$?
  if [ "$rc" = 0 ]; then got=$((got + 1))
  elif [ "$rc" = 2 ]; then failed="$failed Trumf(logg inn på nytt: node ingest/trumf-login.mjs)"
  else failed="$failed Trumf"; fi
fi
if [ "$got" = 0 ]; then
  echo "Ingen kilder ga kvitteringer.${failed:+ Feilet:$failed}" >&2
  echo "Logg inn hos REMA (rema auth login) og/eller Trumf (node ingest/trumf-login.mjs) først." >&2
  exit 1
fi
python3 ingest/merge.py "$WORK/spending.json" "$WORK/rema.json" "$WORK/trumf.json"

# ---- delivery ----
if [ "$use_cloud" = 1 ]; then
  python3 ingest/cloud.py upload "$WORK/spending.json" || failed="$failed konto-opplasting"
fi

if [ "$use_repo" = 1 ]; then
  # Receipts are personal data: refuse to push to a repo anyone can read. An anonymous API call sees a public
  # repo (200) but not a private one (404).
  code="$(curl -s -o /dev/null -w '%{http_code}' "https://api.github.com/repos/$REPO" || true)"
  if [ "$code" = "200" ]; then
    echo "Stopper: $REPO er OFFENTLIG. Gjør repoet privat før du synker kvitteringer dit." >&2
    exit 1
  fi
  DATA=data
  if [ ! -d "$DATA/.git" ]; then
    git clone -q "https://github.com/$REPO.git" "$DATA" || {
      echo "Klarte ikke å klone $REPO. Finnes repoet, og er git logget inn mot GitHub?" >&2
      exit 1
    }
  fi
  remote="$(git -C "$DATA" remote get-url origin)"
  case "$remote" in
    *"$REPO"|*"$REPO.git") ;;
    *) echo "data/ peker på $remote, ikke $REPO. Flytt eller slett data/ og kjør igjen." >&2; exit 1 ;;
  esac
  git -C "$DATA" pull -q --ff-only 2>/dev/null || true
  cp "$WORK/spending.json" "$DATA/spending.json"
  # Offers with barcodes are optional: a failure here (e.g. brotli missing) must not stop the receipt sync.
  if [ -f "$WORK/rema.json" ]; then
    python3 ingest/rema.py --offers "$DATA/rema-offers.json" || echo "Hoppet over REMA-tilbud med strekkode." >&2
  fi
  (
    cd "$DATA"
    git add spending.json
    [ -f rema-offers.json ] && git add rema-offers.json
    if git diff --cached --quiet; then
      echo "Ingen endringer i $REPO."
    else
      git commit -qm "Kvitteringer $(date +%Y-%m-%d)"
      git push -q -u origin HEAD
      echo "Pushet til $REPO."
    fi
  )
fi

if [ -n "$failed" ]; then
  echo "Ferdig, men feilet:$failed" >&2
  exit 3
fi
echo "Ferdig."
