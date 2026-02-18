# Handwriting-to-Calendar Implementation Plan

## Overview

Read handwritten events from the Kindle Scribe calendar PDF and push them to Google Calendar. Fully automatic — plug in the Scribe and it works.

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `script/read_calendar.sh` | Shell wrapper, called by `scribe_watcher.sh` |
| `script/read_calendar.py` | Core logic: render, crop, detect, recognize, push |

### Modified Files

| File | Change |
|------|--------|
| `script/scribe_watcher.sh` | Add `read_calendar.sh` call after `sync_calendar.sh` |
| `script/scribe_watcher.ps1` | Same for Windows |
| `script/setup.sh` | Add config prompts for handwriting extraction |
| `script/setup.ps1` | Same for Windows |
| `requirements.txt` | Add `pymupdf`, `Pillow`, `anthropic` |

---

## Implementation: read_calendar.py

### Step 1: Find calendar PDFs on the Kindle

```python
def find_calendar_pdfs(kindle_mount: str, pdf_name_pattern: str) -> list[Path]:
    """
    Scan kindle_mount/documents/ for files matching the calendar naming
    convention (e.g., "Calendar 2025-03.pdf").

    Returns list of paths to calendar PDFs on the device.
    """
```

We look in `{kindle_mount}/documents/` for files matching the configured `CALENDAR_PDF_NAME` pattern. This is the same location `sync_calendar.sh` copies PDFs to.

### Step 2: Render PDF pages as images

```python
def render_page(pdf_path: Path, page_num: int = 0, dpi: int = 200) -> Image:
    """
    Render a PDF page to a PIL Image using pymupdf.

    The rendered image includes both the printed calendar content
    AND any pen annotation overlays from the Scribe.

    Args:
        pdf_path: Path to the calendar PDF on the Kindle
        page_num: Page index (calendars are single-page)
        dpi: Resolution. 200 is enough for handwriting recognition
             without being excessively large.
    """
```

Key decision: we render the **Kindle's copy** of the PDF (the one with `.sdr` annotation overlays), not our locally generated clean copy. pymupdf can render PDF pages that include annotation layers.

**Open question**: Does pymupdf render Kindle `.sdr` overlay data, or only standard PDF annotations? If `.sdr` data isn't embedded in the PDF itself, we may need to:
1. Check if Scribe writes annotations directly into the PDF (some firmware versions do)
2. If not, overlay the `.sdr` pen data ourselves (parse enough of the binary format to extract stroke coordinates and render them with Pillow)
3. Alternative: use the Scribe's "export with annotations" if available

**Testing needed on device**: Connect the Scribe, write on a calendar, and check whether the PDF file itself is modified or if all annotations live exclusively in `.sdr`.

### Step 3: Crop day cells from the grid

```python
# Grid constants — must match generate_calendar.py exactly
PAGE_WIDTH, PAGE_HEIGHT = 612, 792  # letter size in points
MARGIN_LEFT = 36       # 0.5 * 72
MARGIN_RIGHT = 36
MARGIN_TOP = 54        # 0.75 * 72
MARGIN_BOTTOM = 36
HEADER_HEIGHT = 43.2   # 0.6 * 72
DAY_HEADER_HEIGHT = 21.6  # 0.3 * 72
COLS = 7

def get_cell_bounds(year: int, month: int) -> dict[int, tuple[int, int, int, int]]:
    """
    Calculate pixel bounding boxes for each day cell.

    Returns dict mapping day number -> (x1, y1, x2, y2) in image coordinates.
    Accounts for DPI scaling between PDF points and rendered pixels.

    The grid layout is deterministic given the month (number of weeks
    determines row height), so we can compute this without parsing the PDF.
    """
```

The grid coordinates come directly from `generate_calendar.py`'s constants. We import them or duplicate them (with a shared constants module if we want to be clean about it). The number of weeks in the month determines `cell_height`, and then each cell's position is:

```
x = GRID_LEFT + col * CELL_WIDTH
y = GRID_TOP - DAY_HEADER_HEIGHT - (week_idx + 1) * cell_height
```

Scaled by `dpi / 72` to convert from PDF points to image pixels.

### Step 4: Detect cells with handwriting

```python
def has_handwriting(cell_image: Image, clean_cell_image: Image, threshold: float = 0.02) -> bool:
    """
    Compare the Kindle's rendered cell against a clean render of the
    locally generated PDF (no annotations).

    If the pixel difference exceeds the threshold, there's handwriting.

    This approach:
    - Handles cells that already have printed event text (we diff against
      the clean version, so printed text cancels out)
    - Works regardless of what the handwriting looks like
    - Simple and fast
    """
```

We render BOTH:
1. The Kindle's PDF (with annotations)
2. Our local clean PDF (without annotations)

Then diff each cell. Any significant difference = handwriting. This is better than trying to detect "ink" generically because cells may have printed event text.

### Step 5: Send to Claude vision API

```python
def recognize_handwriting(cell_image: Image, day: int, month: int, year: int,
                          existing_events: list[str]) -> dict | None:
    """
    Send a cell image to Claude's vision API for handwriting recognition.

    Returns structured event data:
    {
        "summary": "Dentist appointment",
        "time": "14:00",         # 24h format, or null for all-day
        "end_time": "15:00",     # optional
        "confidence": 0.92
    }

    Or None if the handwriting is not a calendar event.

    The prompt includes:
    - The date context (so Claude knows what day this cell represents)
    - Any existing Google Calendar events for that day (so Claude can
      distinguish between handwritten additions and annotations of
      existing events)
    """
```

Prompt design is critical. Something like:

```
This image is a cropped cell from a calendar for {weekday}, {month} {day}, {year}.
The cell may contain handwritten text added with a pen on a Kindle Scribe.

Existing typed events already on this day: {existing_events}

If there is handwritten text that represents a NEW calendar event (not just
annotations/marks on existing events), extract it as:
- summary: the event description
- time: start time in HH:MM 24h format (or null if all-day)
- end_time: end time if specified (or null)
- confidence: your confidence from 0.0 to 1.0

If the handwriting is not a new event (just doodles, checkmarks, underlines
on existing events, etc.), return null.

Respond in JSON only.
```

### Step 6: Push to Google Calendar

```python
def create_calendar_event(service, year: int, month: int, day: int,
                          event_data: dict) -> str:
    """
    Create a Google Calendar event via the API.

    Uses the EXISTING credentials/token from calendar sync setup.
    Requires calendar.events scope (read-write) — if the current token
    only has calendar.readonly, we'll need to re-authorize.

    Returns the created event ID.
    """
```

The current calendar sync uses `calendar.readonly` scope. We'll need `calendar.events` for write access. The setup script should handle the scope upgrade — delete the existing token and re-authorize.

### Step 7: Deduplication and history tracking

```python
HISTORY_FILE = "settings/calendar_read_history.json"

# Structure:
# {
#     "2025-03-15": [
#         {
#             "summary": "Dentist appointment",
#             "time": "14:00",
#             "google_event_id": "abc123",
#             "extracted_at": "2025-03-14T22:30:00"
#         }
#     ]
# }
```

Before creating an event, check:
1. Does Google Calendar already have a similar event on that day? (fuzzy match on summary)
2. Have we already extracted this entry in a previous sync? (check history file)

---

## CRITICAL DISCOVERY: macOS MTP Issue

**Date**: 2026-02-18
**Finding**: The Kindle Scribe uses **MTP (Media Transfer Protocol)**, NOT USB Mass Storage.

### What this means

- macOS does **not** natively support MTP
- The Scribe is detected as a USB device (`system_profiler SPUSBDataType` shows it) but does **not** mount under `/Volumes/`
- The original `scribe_watcher.sh` polling `/Volumes/` for a "Kindle" volume **will not work on macOS**
- The Windows version works because Windows has native MTP support (which the COM `Shell.Application` object uses)

### Device info from USB detection

```
Amazon: Kindle Scribe 32GB
Vendor ID: 0x1949 (Lab126)
Product ID: 0x9981
```

### Confirmed: libmtp can see the device

```bash
brew install libmtp
mtp-detect
```

Output confirms the device is recognized and the interface is MTP:
```
Device 0 (VID=1949 and PID=9981) is a Amazon Kindle Scribe 32GB.
Interface description contains the string "MTP"
Device recognized as MTP, no further probing.
```

### Solution options

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| **A. libmtp CLI tools** | Use `mtp-files`, `mtp-getfile`, `mtp-sendfile` directly | Already installed, works | CLI tools are slow, no filesystem mount |
| **B. FUSE + jmtpfs** | `brew install macfuse jmtpfs`, mount as `/Volumes/Kindle` | Scripts work as-is with `/Volumes/` polling | Requires macFUSE (kernel extension), security implications on modern macOS |
| **C. Python libmtp bindings** | Use `python-libmtp` or call libmtp CLI from Python | Fine-grained control, no FUSE needed | More code, different file access pattern |
| **D. OpenMTP (GUI)** | Use OpenMTP app for manual file transfer | Easy for users | Not scriptable, defeats automation goal |

### Recommended approach: Option A (libmtp CLI) with wrapper

Use libmtp CLI tools (`mtp-files`, `mtp-getfile`, `mtp-sendfile`) wrapped in a helper script. This avoids FUSE/kernel extension requirements and works now.

The scripts need to be refactored:
1. **`scribe_watcher.sh`**: Instead of polling `/Volumes/`, use `mtp-detect` to check for device
2. **`export_from_scribe.sh`**: Instead of `cp` from filesystem, use `mtp-getfile` to pull files
3. **`sync_calendar.sh`**: Instead of `cp` to filesystem, use `mtp-sendfile` to push PDFs
4. **New: `script/mtp_helper.sh`**: Common functions for MTP file operations (list, get, send)

### Updated file access pattern

```bash
# List files in a directory
mtp-files 2>&1 | grep "documents/"

# Download a file from Kindle
mtp-getfile <file_id> /local/path/output.pdf

# Upload a file to Kindle
mtp-sendfile /local/path/calendar.pdf /documents/

# Check if device is connected
mtp-detect 2>&1 | grep -q "Kindle Scribe" && echo "connected"
```

### TODO: Test on device

- [ ] Run `mtp-files` to see full file listing and understand file ID scheme
- [ ] Test `mtp-getfile` to pull a PDF from the Scribe
- [ ] Test `mtp-sendfile` to push a PDF to the Scribe
- [ ] Check if `.sdr` directories and their contents are visible via MTP
- [ ] Measure transfer speed for typical operations

---

## Open Questions (to test on the laptop with Scribe)

### Q0 (NEW): Can we access .sdr files via MTP?

**Test**: Run `mtp-files` and look for `.sdr` directories. MTP may hide them or they may not be accessible through the MTP interface.

```bash
mtp-files 2>&1 | grep -i sdr
```

If `.sdr` is not visible via MTP, we'll need to explore alternatives (e.g., use ADB if the Scribe supports it, or accept that annotation extraction requires a different approach).

### Q1: Does the Scribe embed annotations in the PDF or only in .sdr?

**Test**: Pull a PDF that has been annotated on the Scribe using `mtp-getfile`. Open it in Preview on the Mac.

- **If annotations are visible in the PDF**: pymupdf will render them directly. Simplest path.
- **If annotations are NOT visible**: They're in `.sdr` only. We'll need to either:
  - Pull the `.sdr` data via MTP and parse it
  - Render the `.sdr` strokes ourselves with Pillow onto the page image

### Q2: What's the .sdr directory structure for an annotated PDF?

**Test**: After writing on a PDF, check via MTP:
```bash
mtp-files 2>&1 | grep -A5 "Calendar"
```

Document the filenames, sizes, and structure of any `.sdr` related files.

### Q3: Scope upgrade — does deleting the token and re-authorizing work cleanly?

**Test**: Delete `settings/google_token.pickle`, change scope to `calendar.events`, run `generate_calendar.py`. Should trigger re-auth flow.

### Q4: Claude vision accuracy on Scribe handwriting

**Test**: Manually crop a few cells with handwriting, send to the API, check accuracy. This determines whether the approach is viable before building the full pipeline.

---

## Execution Order (Updated)

1. **MTP file access**: Test `mtp-files`, `mtp-getfile`, `mtp-sendfile` with the Scribe
2. **Refactor scripts for MTP**: Update watcher, export, and sync scripts to use libmtp instead of `/Volumes/` filesystem
3. **Answer Q0-Q2**: Check .sdr visibility and annotation embedding via MTP
4. **Build `read_calendar.py`**: Core pipeline (render → crop → diff → API → push)
5. **Build `read_calendar.sh`**: Shell wrapper with config
6. **Wire into watcher**: Add to `scribe_watcher.sh`
7. **Update setup scripts**: Add config prompts, dependency checks
8. **Test end-to-end**: Write on calendar, plug in, verify events appear in Google Calendar
