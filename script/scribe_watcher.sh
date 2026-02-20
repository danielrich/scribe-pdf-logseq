#!/bin/bash
# scribe_watcher.sh - macOS device watcher for Kindle Scribe
#
# Detects the Kindle Scribe via MTP (the Scribe uses MTP, not USB Mass
# Storage, so it doesn't mount under /Volumes/ on macOS).
#
# When the device is detected, runs the export and sync pipeline in a
# single shot (the Scribe drops off USB after each MTP session ends,
# so we do everything in one invocation).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_FOLDER="$(dirname "$SCRIPT_DIR")"

# Import configuration
CONFIG_FILE="$PARENT_FOLDER/settings/config.sh"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Configuration file not found. Please run setup.sh first."
    exit 1
fi
source "$CONFIG_FILE"

MTP_SCRIPT="$SCRIPT_DIR/mtp_pull.py"
if [ ! -f "$MTP_SCRIPT" ]; then
    echo "ERROR: mtp_pull.py not found at $MTP_SCRIPT"
    exit 1
fi

CONNECTED=false

echo "Watching for Kindle Scribe (via MTP)..."
echo "Connect your device with a USB cable to sync your notebooks."
echo "(Note: The Scribe uses MTP — it won't appear in /Volumes/)"

while true; do
    # Check for device via MTP (lightweight detect, no full connection)
    if python3 "$MTP_SCRIPT" --detect --quiet 2>/dev/null; then
        if [ "$CONNECTED" = false ]; then
            echo ""
            echo "$(date): Kindle Scribe detected!"

            # Run the export script (handles MTP download + conversion)
            bash "$SCRIPT_DIR/export_from_scribe.sh"

            # Run the Logseq integration script if configured
            if [ "$UPDATE_LOGSEQ" = "Yes" ]; then
                bash "$SCRIPT_DIR/add_to_logseq.sh"
            fi

            # Note: Calendar sync (push to Kindle) requires a separate
            # MTP connection. The Scribe will have dropped off USB after
            # export_from_scribe.sh finished. The user will need to
            # replug for calendar sync. TODO: integrate into mtp_pull.py
            # as a single-session operation.
            if [ "$SYNC_CALENDAR" = "Yes" ]; then
                echo "Calendar sync requires re-plugging the Scribe."
                echo "Run: bash $SCRIPT_DIR/sync_calendar.sh"
            fi

            CONNECTED=true
            echo "$(date): Sync complete. Waiting for next connection..."
        fi
    else
        if [ "$CONNECTED" = true ]; then
            CONNECTED=false
            echo "$(date): Kindle Scribe disconnected."
        fi
    fi

    sleep 5
done
