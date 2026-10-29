#!/bin/bash
# Remove the Matkassa helper launchd agent. The pairing code (~/.matkassa/helper-pair.json), the REMA login
# (~/.rema1000/) and the logs are kept; delete the pairing file too with --forget.
set -euo pipefail
LABEL="no.matkassa.helper"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
[ "${1:-}" = "--forget" ] && rm -f "$HOME/.matkassa/helper-pair.json" "$HOME/.matkassa/helper-state.json"
echo "Fjernet $LABEL."
