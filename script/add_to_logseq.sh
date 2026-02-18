#!/bin/bash
# add_to_logseq.sh - macOS Logseq integration
#
# Copies converted PDFs to Logseq assets folder,
# updates the markdown page with links, and optionally pushes to git.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_FOLDER="$(dirname "$SCRIPT_DIR")"

# Import configuration
CONFIG_FILE="$PARENT_FOLDER/settings/config.sh"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Configuration file not found. Please run setup.sh first."
    exit 1
fi
source "$CONFIG_FILE"

# Pull latest changes
git -C "$REPO_PATH" pull

# Ensure destination folder exists
mkdir -p "$DESTINATION_FOLDER"

# Ensure the markdown file exists
if [ ! -f "$MARKDOWN_FILE" ]; then
    mkdir -p "$(dirname "$MARKDOWN_FILE")"
    touch "$MARKDOWN_FILE"
fi

# Read existing markdown content
MARKDOWN_CONTENT=$(cat "$MARKDOWN_FILE")

# Track new references to add
NEW_REFERENCES=""

# Process each PDF file
for pdf in "$SOURCE_PDF_FOLDER"/*.pdf; do
    [ -f "$pdf" ] || continue

    pdf_name="$(basename "$pdf")"
    pdf_basename="${pdf_name%.pdf}"

    echo "$pdf_name"

    # Copy PDF to Logseq assets folder
    DEST_PATH="$DESTINATION_FOLDER/$pdf_name"
    cp "$pdf" "$DEST_PATH"

    # Stage the PDF in git
    git -C "$REPO_PATH" add "$DEST_PATH"

    # Build the markdown link
    RELATIVE_LINK="../assets/pdf/$pdf_name"
    LINK_TEXT="- ![$pdf_basename]($RELATIVE_LINK)"

    # Check if link already exists in the markdown content
    if ! echo "$MARKDOWN_CONTENT" | grep -qF "$LINK_TEXT"; then
        NEW_REFERENCES="$LINK_TEXT
$NEW_REFERENCES"
    fi
done

# If there are new references, prepend them to the markdown file
if [ -n "$NEW_REFERENCES" ]; then
    # Create updated content with new references at the top
    UPDATED_CONTENT="${NEW_REFERENCES}${MARKDOWN_CONTENT}"
    echo "$UPDATED_CONTENT" > "$MARKDOWN_FILE"
fi

# Git commit and push if configured
if [ "$GIT_LOGSEQ" = "Yes" ]; then
    git -C "$REPO_PATH" add "$MARKDOWN_FILE"
    git -C "$REPO_PATH" commit -m "Kindle Scribe Notebook Update"
    git -C "$REPO_PATH" push -u origin "$GIT_BRANCH"
fi

echo "PDF files have been moved to LogSeq assets and markdown file updated. ($MARKDOWN_FILE)"
