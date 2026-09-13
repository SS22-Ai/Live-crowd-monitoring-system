#!/usr/bin/env bash
# Installs (or reinstalls) the launchd crash-restart supervisor for this
# checkout of the Event Crowd Monitor. See ../DEPLOYMENT.md for the full
# runbook. Safe to re-run: it always reinstalls cleanly rather than
# leaving a stale copy loaded from an old path.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE="$SCRIPT_DIR/com.eventcrowdmonitor.app.plist"
LABEL="com.eventcrowdmonitor.app"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "Project root: $PROJECT_ROOT"

if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "ERROR: $PROJECT_ROOT/.venv/bin/python not found — set up the venv first (see HANDOVER.md §4)." >&2
    exit 1
fi
if [ ! -f "$PROJECT_ROOT/config.local.yaml" ]; then
    echo "ERROR: $PROJECT_ROOT/config.local.yaml not found — this plist runs with" >&2
    echo "       CROWD_MONITOR_CONFIG=config.local.yaml, create it first (see HANDOVER.md §5)." >&2
    exit 1
fi

# launchd cannot create a missing parent directory for StandardOutPath/
# StandardErrorPath — it just fails to spawn the job with no explanation.
# Create logs/ (and data/, for the same reason the app itself would need
# it) before the agent ever tries to start.
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/data"

sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$TEMPLATE" > "$DEST"
plutil -lint "$DEST"

UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

# Unload first if already loaded, so a reinstall (e.g. after moving the
# project) doesn't leave a stale copy running against the old path.
if launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null; then
    # bootout returns before launchd has fully torn down the old service;
    # bootstrapping immediately after can race and fail with EIO (seen
    # live during testing). Poll until it's actually gone.
    for _ in $(seq 1 20); do
        launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
        sleep 0.5
    done
fi

launchctl bootstrap "$DOMAIN" "$DEST"

echo "Installed and started. Checking status..."
sleep 2
launchctl print "$DOMAIN/$LABEL" | grep -E "state|pid|last exit code" || true
echo "Full runbook: DEPLOYMENT.md"
