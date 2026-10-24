#!/bin/bash
# Remove the weekly sync launchd agent. Logs in ingest/logs/ are kept.
set -euo pipefail
LABEL="no.matkassa.weekly-sync"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Fjernet $LABEL."
