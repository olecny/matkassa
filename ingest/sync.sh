#!/bin/bash
# Fetch YOUR receipts (and REMA's barcode offers) on your Mac and push them to YOUR private data repo,
# which the app syncs from (Mer → Synk fra Mac). Works for any user: own REMA login, own repo.
#
# One-time setup (see ingest/README.md):
#   1. rema auth login                      # rema1000-cli, your own phone number
#   2. create a PRIVATE GitHub repo, e.g. <you>/matkassa-data
#   3. echo 'MATKASSA_DATA_REPO=<you>/matkassa-data' >> ingest/.env
# Usage: ingest/sync.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${MATKASSA_DATA_REPO:-}" ] && [ -f ingest/.env ]; then
  MATKASSA_DATA_REPO="$(grep -E '^MATKASSA_DATA_REPO=' ingest/.env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')"
fi
REPO="${MATKASSA_DATA_REPO:-}"
if ! [[ "$REPO" =~ ^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$ ]]; then
  echo "Sett MATKASSA_DATA_REPO=brukernavn/repo (ditt PRIVATE repo) i ingest/.env eller miljøet." >&2
  exit 1
fi

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

python3 ingest/rema.py --out "$DATA/spending.json"
# Offers with barcodes are optional: a failure here (e.g. brotli missing) must not stop the receipt sync.
python3 ingest/rema.py --offers "$DATA/rema-offers.json" || echo "Hoppet over REMA-tilbud med strekkode." >&2

cd "$DATA"
git add spending.json
[ -f rema-offers.json ] && git add rema-offers.json
if git diff --cached --quiet; then
  echo "Ingen endringer."
  exit 0
fi
git commit -qm "Kvitteringer $(date +%Y-%m-%d)"
git push -q -u origin HEAD
echo "Pushet til $REPO."
