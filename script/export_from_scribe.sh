#!/bin/bash
# export_from_scribe.sh - macOS notebook extraction and conversion
#
# On macOS, the Kindle Scribe is mounted as a regular volume, so we can
# access notebooks directly via the filesystem (no COM objects needed).
#
# Usage: export_from_scribe.sh [kindle_volume_path]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_FOLDER="$(dirname "$SCRIPT_DIR")"

# Import configuration
CONFIG_FILE="$PARENT_FOLDER/settings/config.sh"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Configuration file not found. Please run setup.sh first."
    exit 1
fi
source "$CONFIG_FILE"

# Accept Kindle volume path as argument or try to find it
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

if [ -z "$KINDLE_VOLUME" ] || [ ! -d "$KINDLE_VOLUME" ]; then
    echo "Kindle Scribe is not connected. Please connect your device and try again."
    exit 1
fi

echo "Found Kindle at: $KINDLE_VOLUME"

# Path to notebooks on the device
NOTEBOOKS_PATH="$KINDLE_VOLUME/$INTERNAL_STORAGE_FOLDER_NAME/$NOTEBOOKS_FOLDER_NAME"

if [ ! -d "$NOTEBOOKS_PATH" ]; then
    echo "'.notebooks' folder not found at: $NOTEBOOKS_PATH"
    echo "Make sure your Kindle Scribe has notebooks on it."
    exit 1
fi

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

# Function to compute SHA-256 hash of a file
get_file_hash() {
    shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
}

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

# Loop through each folder in .notebooks
for folder in "$NOTEBOOKS_PATH"/*/; do
    [ -d "$folder" ] || continue

    folder_name="$(basename "$folder")"

    # Check if folder name matches GUID pattern
    if ! echo "$folder_name" | grep -qE "$GUID_PATTERN"; then
        continue
    fi

    # Look for the nbk file
    NBK_FILE="$folder/$NBK_FILE_NAME"
    if [ ! -f "$NBK_FILE" ]; then
        continue
    fi

    # Get or generate label
    label=$(json_get "$folder_name")
    if [ -z "$label" ]; then
        timestamp=$(date "+%Y/%m/%d %H:%M:%S")
        label="Scribe Notebook $timestamp"
        json_set "$folder_name" "$label"
    fi

    # Create GUID folder in destination
    GUID_FOLDER="$DESTINATION_PATH/$folder_name"
    mkdir -p "$GUID_FOLDER"

    # Destination for the nbk file copy
    DEST_NBK="$GUID_FOLDER/$NBK_FILE_NAME"

    # Check if file has changed using hash comparison
    PREVIOUS_HASH=""
    if [ -f "$DEST_NBK" ]; then
        PREVIOUS_HASH=$(get_file_hash "$DEST_NBK")
    fi

    # Copy the nbk file from the Kindle
    cp "$NBK_FILE" "$DEST_NBK"

    CURRENT_HASH=$(get_file_hash "$DEST_NBK")

    if [ "$CURRENT_HASH" = "$PREVIOUS_HASH" ] && [ -n "$PREVIOUS_HASH" ]; then
        echo "Notebook unchanged - $DEST_NBK"
        continue
    fi

    echo "Notebook change detected. Processing: $DEST_NBK"

    # Convert nbk to epub using Calibre KFX Input plugin
    OUTPUT_EPUB="$OUTPUT_EPUB_DIRECTORY/${folder_name}.epub"
    echo "Executing: $CALIBRE_PATH -r \"$PLUGIN_NAME\" -- \"$GUID_FOLDER\" \"$OUTPUT_EPUB\""
    "$CALIBRE_PATH" -r "$PLUGIN_NAME" -- "$GUID_FOLDER" "$OUTPUT_EPUB"

    # Convert epub to pdf
    SAFE_LABEL=$(sanitize_filename "$label")
    OUTPUT_PDF="$SOURCE_PDF_FOLDER/${SAFE_LABEL}.pdf"
    echo "Executing: $EBOOK_CONVERT_PATH \"$OUTPUT_EPUB\" \"$OUTPUT_PDF\""
    "$EBOOK_CONVERT_PATH" "$OUTPUT_EPUB" "$OUTPUT_PDF"
done

echo "Notebook conversion complete."
