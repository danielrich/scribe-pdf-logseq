
# Kindle Scribe to Logseq Automation (Windows & macOS)

This repository contains scripts to automate exporting notebooks from a Kindle Scribe, converting them to PDF, and integrating them into Logseq.

The script can be left running. When you want to sync the notebooks from your Kindle Scribe, simply plug it in through USB. The script will watch for the connection, check for any new or changed notebooks, convert them to PDF, and add them to the LogSeq page "Scribe Notebooks.md".

## Overview

The main script (`scribe_watcher.ps1` on Windows, `scribe_watcher.sh` on macOS) monitors for the connection of a Kindle Scribe device, exports the notebooks, converts them to PDF, and integrates them into Logseq.

## Video



https://github.com/user-attachments/assets/55797896-2540-46be-9f95-76dddee1c81a


## Prerequisites

Ensure the following are installed:

1. **Calibre**: An e-book manager. [Info Here](https://calibre-ebook.com/)
2. **KFX Input Plugin**: Required for handling Kindle formats. [Info Here](https://www.mobileread.com/forums/showthread.php?t=291290).
3. **LogSeq**: The main intent is to add the Notebooks converted to pdf to logseq. It can also be used without logseq to just generate the pdfs from your notebooks. [Info here](https://logseq.com/)

---

## macOS Setup

### Install Prerequisites

1. **Install Calibre** from [calibre-ebook.com](https://calibre-ebook.com/download_osx) or via Homebrew:
   ```bash
   brew install --cask calibre
   ```

2. **Install the KFX Input Plugin** in Calibre:
   - Open Calibre
   - Go to Preferences > Plugins > Get new plugins
   - Search for "KFX Input" and install it
   - Or download from [MobileRead](https://www.mobileread.com/forums/showthread.php?t=291290) and install manually

3. **Install LogSeq** (optional) from [logseq.com](https://logseq.com/)

### macOS Scripts

| Script | Description |
|--------|-------------|
| `setup.sh` | Interactive configuration wizard. Run this first. |
| `scribe_watcher.sh` | Watches for Kindle Scribe USB connection and triggers sync. |
| `export_from_scribe.sh` | Extracts notebooks from the Kindle and converts them to PDF via Calibre. |
| `add_to_logseq.sh` | Copies PDFs to Logseq assets and updates the Scribe Notebooks page. |

### macOS Usage

1. Run the setup script to create your configuration:
   ```bash
   cd script
   bash setup.sh
   ```

2. Start the watcher:
   ```bash
   bash script/scribe_watcher.sh
   ```

3. Connect your Kindle Scribe via USB. The script will automatically detect it, export notebooks, and sync to Logseq.

### How It Works on macOS

On macOS, the Kindle Scribe mounts as a standard volume under `/Volumes/` (typically `/Volumes/Kindle`). The watcher script polls for this mount point every 5 seconds. When detected, it accesses the notebooks directly through the filesystem — no special drivers or COM objects needed.

---

## Windows Setup

### Windows Scripts

| Script | Description |
|--------|-------------|
| `setup.ps1` | Interactive configuration wizard. Run this first. |
| `scribe_watcher.ps1` | Watches for Kindle Scribe USB connection and triggers sync. |
| `export_from_scribe.ps1` | Extracts notebooks from the Kindle and converts them to PDF via Calibre. |
| `add_to_logseq.ps1` | Copies PDFs to Logseq assets and updates the Scribe Notebooks page. |

### Windows Usage

1. Ensure all prerequisites are installed and paths are correctly set in the scripts.
2. Run `setup.ps1` script
3. Run the `scribe_watcher.ps1` script. The script will detect the device, export notebooks, convert them to PDF, and integrate them into Logseq.
4. Connect your Kindle Scribe to the computer.

---

## Google Calendar Sync (macOS)

Automatically generate a monthly calendar PDF with your Google Calendar events and push it to your Kindle Scribe. Write on the calendar with your pen, and when events update, the PDF regenerates with the same fixed layout — your handwritten annotations stay in place.

### How It Works

1. The script generates a monthly calendar PDF using a **fixed grid layout**
2. Google Calendar events appear as text within each day's cell
3. The PDF is copied to the Kindle Scribe's `documents/` folder
4. You write on the calendar with the Scribe's pen
5. Next sync: the PDF regenerates with updated events, **same layout coordinates**
6. The Scribe's pen annotations are stored in `.sdr` sidecar files as position-based overlays, so they stay aligned

### Setup

1. **Install Python dependencies:**
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Set up Google Calendar API credentials:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project (or use an existing one)
   - Enable the **Google Calendar API**
   - Go to Credentials > Create Credentials > OAuth client ID
   - Choose "Desktop app"
   - Download the credentials JSON file
   - Save it as `settings/credentials.json`

   The first time you run the calendar sync, it will open a browser window to authorize access. After that, a token is cached locally.

3. **Run setup.sh** and say "Yes" to the calendar sync option.

### Usage

**Automatic (via watcher):** If calendar sync is enabled in setup, it runs automatically when the Kindle connects.

**Manual:**
```bash
# Generate and push to connected Kindle
bash script/sync_calendar.sh

# Generate a specific month
python3 script/generate_calendar.py --month 2025-03 --output my_calendar.pdf

# Without Google Calendar (blank calendar or local events only)
python3 script/generate_calendar.py --no-google --output my_calendar.pdf
```

### Local Events File (Alternative to Google)

If you don't want to use the Google Calendar API, you can create a `settings/events.json` file:

```json
[
    {"date": "2025-03-15", "display": "Dentist 2pm", "summary": "Dentist"},
    {"date": "2025-03-20", "display": "Team lunch", "summary": "Team lunch"}
]
```

Events from both Google Calendar and the local JSON file are merged.

### Important Notes

- The calendar uses a **pixel-perfect fixed grid layout**. This is critical — if the layout shifts, your pen annotations will be misaligned.
- The PDF is regenerated from scratch each sync. Your handwritten annotations persist because they're stored separately by the Scribe in `.sdr` files, not in the PDF itself.
- You can generate up to 3 months ahead (configured during setup).

---

## Customizing the PDF Label

### Modifying Labels via `notebook_labels.json`

You can manually modify the labels of specific notebooks in the `notebook_labels.json` file. This JSON file maps unique notebook identifiers to custom labels. The specified label will be used as the filename for the corresponding PDF when generated.

#### Example

```json
{
    "12345-abcde-67890": "Project Ideas",
    "67890-fghij-12345": "Meeting Notes"
}
```

In this example, the notebook with the ID `12345-abcde-67890` will generate a PDF named `Project Ideas.pdf`, and the notebook with the ID `67890-fghij-12345` will generate a PDF named `Meeting Notes.pdf`.

### Customizing the PDF Filename in Script

The script uses these labels when setting the PDF filename. By updating the `notebook_labels.json` file, you control the naming of the output PDF files.

## Troubleshooting

- **Calibre Not Found**: Verify the Calibre paths in your configuration.
  - macOS default: `/Applications/calibre.app/Contents/MacOS/calibre-debug`
  - Windows default: `C:\Program Files\Calibre2\calibre-debug.exe`
- **Kindle Not Detected**:
  - macOS: Check that your Kindle appears under `/Volumes/` when plugged in. Run `ls /Volumes/` to verify.
  - Windows: Check that the device name pattern matches the connected device's name in File Explorer.
- **Permission Denied (macOS)**: Make scripts executable with `chmod +x script/*.sh`

## Contributions

Fork this repository and submit pull requests for improvements or additions.


## Recognition

This is just a script for convenience, all the actual heavy lifting is done by the [Calibre KFX plugin](https://www.mobileread.com/forums/showthread.php?t=291290), thank you jhowell, and everyone that contributed in [this thread ](https://www.mobileread.com/forums/showthread.php?t=353901).


## License

This project is licensed under the MIT License.
