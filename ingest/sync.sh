#!/bin/bash
# Fetch receipts on the Mac and push them to the private data repo the app syncs from.
# Usage: ingest/sync.sh   (needs `rema auth login` once; data repo is cloned into data/)
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${MATKASSA_DATA_REPO:-olecny/matkassa-data}"
DATA=data

if [ ! -d "$DATA/.git" ]; then
  git clone -q "https://github.com/$REPO.git" "$DATA" 2>/dev/null || { mkdir -p "$DATA"; git -C "$DATA" init -q -b main; git -C "$DATA" remote add origin "https://github.com/$REPO.git"; }
fi
git -C "$DATA" pull -q --ff-only 2>/dev/null || true

python3 ingest/rema.py --out "$DATA/spending.json"

cd "$DATA"
git add spending.json
if git diff --cached --quiet; then
  echo "Ingen endringer."
  exit 0
fi
git commit -qm "Kvitteringer $(date +%Y-%m-%d)"
git push -q -u origin main
echo "Pushet til $REPO."
