#!/bin/bash
# scribe_watcher.sh - macOS device watcher for Kindle Scribe
#
# On macOS, the Kindle Scribe mounts as a volume under /Volumes/
# (typically /Volumes/Kindle). This script watches for that mount point.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_FOLDER="$(dirname "$SCRIPT_DIR")"

# Import configuration
CONFIG_FILE="$PARENT_FOLDER/settings/config.sh"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Configuration file not found. Please run setup.sh first."
    exit 1
fi
source "$CONFIG_FILE"

CONNECTED=false

echo "Watching for Kindle Scribe..."
echo "Connect your device with a USB cable to sync your notebooks."

while true; do
    # Look for a mounted volume matching the device name pattern
    # On macOS, Kindle mounts as /Volumes/Kindle (or similar)
    KINDLE_VOLUME=""
    for vol in /Volumes/*/; do
        vol_name="$(basename "$vol")"
        # Case-insensitive match against the device name pattern
        if echo "$vol_name" | grep -iq "$DEVICE_NAME_PATTERN"; then
            KINDLE_VOLUME="$vol"
            break
        fi
    done

    if [ -z "$KINDLE_VOLUME" ]; then
        if [ "$CONNECTED" = true ]; then
            CONNECTED=false
            echo "Kindle Scribe disconnection detected."
        fi
    else
        if [ "$CONNECTED" = false ]; then
            echo "Kindle Scribe connection detected at: $KINDLE_VOLUME"

            # Run the export script
            bash "$SCRIPT_PATH/export_from_scribe.sh" "$KINDLE_VOLUME"

            # Run the Logseq integration script if configured
            if [ "$UPDATE_LOGSEQ" = "Yes" ]; then
                bash "$SCRIPT_PATH/add_to_logseq.sh"
            fi

            CONNECTED=true
        fi
    fi

    # Wait before checking again
    sleep 5
done
