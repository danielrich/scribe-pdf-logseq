#!/bin/bash
# sync_calendar.sh - Sync Google Calendar PDF to/from Kindle Scribe
#
# This script:
# 1. Regenerates the calendar PDF with latest Google Calendar events
# 2. Copies it to the Kindle Scribe (preserving .sdr annotation data)
# 3. The fixed-grid layout means pen annotations stay aligned
#
# Can be run standalone or called from scribe_watcher.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_FOLDER="$(dirname "$SCRIPT_DIR")"

# Import configuration
CONFIG_FILE="$PARENT_FOLDER/settings/config.sh"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Configuration file not found. Please run setup.sh first."
    exit 1
fi
source "$CONFIG_FILE"

# Calendar-specific settings with defaults
CALENDAR_PDF_NAME="${CALENDAR_PDF_NAME:-Calendar}"
CALENDAR_MONTHS="${CALENDAR_MONTHS:-1}"

# Find the Kindle volume
KINDLE_VOLUME="${1:-}"
if [ -z "$KINDLE_VOLUME" ]; then
    for vol in /Volumes/*/; do
        vol_name="$(basename "$vol")"
        if echo "$vol_name" | grep -iq "$DEVICE_NAME_PATTERN"; then
            KINDLE_VOLUME="$vol"
            break
        fi
    done
fi

# Generate calendar PDFs
echo "=== Calendar Sync ==="
echo "Generating calendar PDFs..."

CURRENT_YEAR=$(date +%Y)
CURRENT_MONTH=$(date +%m)

for i in $(seq 0 $((CALENDAR_MONTHS - 1))); do
    # Calculate target month
    TARGET_MONTH=$((10#$CURRENT_MONTH + i))
    TARGET_YEAR=$CURRENT_YEAR
    while [ "$TARGET_MONTH" -gt 12 ]; do
        TARGET_MONTH=$((TARGET_MONTH - 12))
        TARGET_YEAR=$((TARGET_YEAR + 1))
    done
    TARGET_MONTH=$(printf "%02d" $TARGET_MONTH)

    PDF_NAME="${CALENDAR_PDF_NAME} ${TARGET_YEAR}-${TARGET_MONTH}.pdf"
    OUTPUT_PATH="$SOURCE_PDF_FOLDER/$PDF_NAME"

    echo "Generating: $PDF_NAME"
    python3 "$SCRIPT_DIR/generate_calendar.py" \
        --config "$CONFIG_FILE" \
        --month "${TARGET_YEAR}-${TARGET_MONTH}" \
        --output "$OUTPUT_PATH"

    # Copy to Kindle if connected
    if [ -n "$KINDLE_VOLUME" ] && [ -d "$KINDLE_VOLUME" ]; then
        KINDLE_DOCS="$KINDLE_VOLUME/documents"
        if [ -d "$KINDLE_DOCS" ]; then
            KINDLE_PDF="$KINDLE_DOCS/$PDF_NAME"
            echo "Copying to Kindle: $PDF_NAME"
            cp "$OUTPUT_PATH" "$KINDLE_PDF"
        else
            echo "Warning: documents/ folder not found on Kindle at $KINDLE_DOCS"
        fi
    fi
done

if [ -z "$KINDLE_VOLUME" ] || [ ! -d "$KINDLE_VOLUME" ]; then
    echo ""
    echo "Kindle not connected. PDFs generated locally at: $SOURCE_PDF_FOLDER"
    echo "Connect your Kindle and run again to push to device, or copy manually."
fi

echo "Calendar sync complete."
