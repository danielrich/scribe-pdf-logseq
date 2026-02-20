#!/bin/bash
# export_from_scribe.sh - macOS notebook extraction and conversion
#
# Uses mtp_pull.py to download notebooks from the Kindle Scribe via MTP,
# then converts them to PDF via Calibre's KFX Input plugin.
#
# Usage: export_from_scribe.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_FOLDER="$(dirname "$SCRIPT_DIR")"

# Import configuration
CONFIG_FILE="$PARENT_FOLDER/settings/config.sh"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Configuration file not found. Please run setup.sh first."
    exit 1
fi
source "$CONFIG_FILE"

# Ensure output directories exist
mkdir -p "$DESTINATION_PATH"
mkdir -p "$OUTPUT_EPUB_DIRECTORY"
mkdir -p "$SOURCE_PDF_FOLDER"
mkdir -p "$SETTINGS_DIRECTORY"

# JSON labels file
JSON_FILE="$SETTINGS_DIRECTORY/notebook_labels.json"

# Initialize JSON file if it doesn't exist
if [ ! -f "$JSON_FILE" ]; then
    echo "{}" > "$JSON_FILE"
fi

# Function to read a value from the JSON labels file
json_get() {
    local key="$1"
    python3 -c "
import json, sys
with open('$JSON_FILE') as f:
    data = json.load(f)
print(data.get('$key', ''))
" 2>/dev/null
}

# Function to set a value in the JSON labels file
json_set() {
    local key="$1"
    local value="$2"
    python3 -c "
import json
with open('$JSON_FILE', 'r') as f:
    data = json.load(f)
data['$key'] = '$value'
with open('$JSON_FILE', 'w') as f:
    json.dump(data, f, indent=4)
" 2>/dev/null
}

# Function to sanitize a filename (remove characters invalid for filenames)
sanitize_filename() {
    echo "$1" | sed 's/[<>:"\/\\|?*]//g'
}

# --- Step 1: Download notebooks from Scribe via MTP ---

echo "Downloading notebooks from Kindle Scribe via MTP..."
MTP_SCRIPT="$SCRIPT_DIR/mtp_pull.py"

if [ ! -f "$MTP_SCRIPT" ]; then
    echo "ERROR: mtp_pull.py not found at $MTP_SCRIPT"
    exit 1
fi

# pull-notebooks handles: connect, find .notebooks, download changed nbk files
# It uses SHA256 hashing internally to skip unchanged notebooks
PULL_OUTPUT=$(python3 "$MTP_SCRIPT" --pull-notebooks "$DESTINATION_PATH" --json 2>/tmp/mtp_pull_stderr.txt)
PULL_EXIT=$?

# Show MTP status messages
cat /tmp/mtp_pull_stderr.txt

if [ $PULL_EXIT -ne 0 ]; then
    echo "ERROR: Failed to pull notebooks from Scribe."
    exit 1
fi

# Parse the JSON output to get list of downloaded (new/changed) notebooks
# Format: [{"guid": "...", "path": "...", "size": 123}, ...]
CHANGED_GUIDS=$(echo "$PULL_OUTPUT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for nb in data:
    print(nb['guid'])
" 2>/dev/null)

if [ -z "$CHANGED_GUIDS" ]; then
    echo "All notebooks up to date. Nothing to convert."
    exit 0
fi

# --- Step 2: Convert changed notebooks to PDF ---

echo "$CHANGED_GUIDS" | while IFS= read -r folder_name; do
    [ -z "$folder_name" ] && continue

    GUID_FOLDER="$DESTINATION_PATH/$folder_name"

    # Get or generate label
    label=$(json_get "$folder_name")
    if [ -z "$label" ]; then
        timestamp=$(date "+%Y/%m/%d %H:%M:%S")
        label="Scribe Notebook $timestamp"
        json_set "$folder_name" "$label"
    fi

    echo "Processing: $folder_name ($label)"

    # Convert nbk to epub using Calibre KFX Input plugin
    OUTPUT_EPUB="$OUTPUT_EPUB_DIRECTORY/${folder_name}.epub"
    echo "  NBK -> EPUB: $CALIBRE_PATH -r \"$PLUGIN_NAME\" -- \"$GUID_FOLDER\" \"$OUTPUT_EPUB\""
    "$CALIBRE_PATH" -r "$PLUGIN_NAME" -- "$GUID_FOLDER" "$OUTPUT_EPUB"

    if [ $? -ne 0 ]; then
        echo "  ERROR: Calibre conversion failed for $folder_name"
        continue
    fi

    # Convert epub to pdf
    SAFE_LABEL=$(sanitize_filename "$label")
    OUTPUT_PDF="$SOURCE_PDF_FOLDER/${SAFE_LABEL}.pdf"
    echo "  EPUB -> PDF: $EBOOK_CONVERT_PATH \"$OUTPUT_EPUB\" \"$OUTPUT_PDF\""
    "$EBOOK_CONVERT_PATH" "$OUTPUT_EPUB" "$OUTPUT_PDF"

    if [ $? -ne 0 ]; then
        echo "  ERROR: ebook-convert failed for $folder_name"
        continue
    fi

    echo "  Done: $OUTPUT_PDF"
done

echo "Notebook conversion complete."
